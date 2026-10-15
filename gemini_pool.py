"""Gemini API kalitlar puli + model zaxira zanjiri.

Xususiyatlari:
  * Round-robin: har bir so'rov navbatdagi kalitdan boshlanadi.
  * Failover: kalit 429/5xx/xato bersa, avtomatik keyingi kalitga o'tadi.
  * Model fallback: model 404/429/503 bersa, keyingi modelga o'tadi.
  * Cooldown: limitga yetgan kalit vaqtincha "sovutiladi" va o'tkazib yuboriladi.
  * Async-safe: asyncio.Lock bilan himoyalangan.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Optional

import aiohttp

log = logging.getLogger("gemini")


class AllKeysFailedError(RuntimeError):
    """Barcha kalit/model kombinatsiyalari muvaffaqiyatsiz bo'lganda ko'tariladi."""


class GeminiPool:
    def __init__(
        self,
        keys: list[str],
        models: list[str] | str,
        base_url: str,
        timeout: int = 90,
        max_retries_per_key: int = 2,
        cooldown_seconds: int = 60,
    ) -> None:
        if not keys:
            raise ValueError("Kamida bitta Gemini API kalit kerak.")
        if isinstance(models, str):
            models = [models]
        if not models:
            raise ValueError("Kamida bitta model kerak.")

        self.keys = keys
        self.models = models
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries_per_key = max_retries_per_key
        self.cooldown_seconds = cooldown_seconds

        self._idx = 0
        self._lock = asyncio.Lock()
        self._cooldown_until: dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------ #
    # Sessiya
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------ #
    # Kalit tanlash
    # ------------------------------------------------------------------ #
    async def _pick_key(self) -> str:
        """Navbatdagi, cooldown'da bo'lmagan kalitni qaytaradi."""
        async with self._lock:
            n = len(self.keys)
            now = time.time()
            for _ in range(n):
                key = self.keys[self._idx % n]
                self._idx = (self._idx + 1) % n
                if self._cooldown_until.get(key, 0.0) <= now:
                    return key
            key = min(self.keys, key=lambda k: self._cooldown_until.get(k, 0.0))
            wait = max(0.0, self._cooldown_until.get(key, 0.0) - now)
            log.warning("Barcha kalitlar cooldown'da, %.1fs kutiladi.", wait)
            return key

    def _mask(self, key: str) -> str:
        return f"{key[:8]}...{key[-4:]}" if len(key) > 14 else "***"

    def _cool(self, key: str) -> None:
        self._cooldown_until[key] = time.time() + self.cooldown_seconds

    # ------------------------------------------------------------------ #
    # Asosiy so'rov
    # ------------------------------------------------------------------ #
    async def _post(self, key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.start()
        url = f"{self.base_url}/{path}"
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        assert self._session is not None
        async with self._session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status == 200:
                return await resp.json()
            raise _HttpError(resp.status, text)

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        history: Optional[list[dict[str, Any]]] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
    ) -> str:
        """Matn (yoki matn+rasm) so'rovi.

        `history` — oldingi suhbat qatlamlari: [{"role": "user"|"assistant",
        "text": "..."}]. Ular Gemini'ning ko'p bosqichli `contents` maydoniga
        qo'shiladi, shunda model oldingi gaplarni eslab qoladi.

        Avval har bir model uchun barcha kalitlar sinaladi; model ishlamasa
        (404/429/503), keyingi modelga o'tiladi.
        """
        contents: list[dict[str, Any]] = []
        if history:
            for turn in history:
                t = str(turn.get("text") or "").strip()
                if not t:
                    continue
                # Gemini rollari: "user" va "model" (assistant -> model).
                role = "model" if turn.get("role") in ("assistant", "model") else "user"
                contents.append({"role": role, "parts": [{"text": t[:4000]}]})

        parts: list[dict[str, Any]] = [{"text": prompt}]
        if image_bytes:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image_mime,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                }
            )
        contents.append({"role": "user", "parts": parts})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        last_error: Optional[Exception] = None

        for model in self.models:
            path = f"models/{model}:generateContent"
            for _ in range(len(self.keys) * self.max_retries_per_key):
                key = await self._pick_key()
                try:
                    data = await self._post(key, path, payload)
                    text = _extract_text(data)
                    if text:
                        log.info("Javob olindi (model=%s, kalit=%s).", model, self._mask(key))
                        return text
                    last_error = RuntimeError("Bo'sh javob qaytdi.")
                except _HttpError as exc:
                    last_error = exc
                    if exc.status in (429, 500, 502, 503, 504):
                        log.warning(
                            "model=%s kalit=%s xato %s — cooldown + keyingi kalit.",
                            model, self._mask(key), exc.status,
                        )
                        self._cool(key)
                    elif exc.status in (400, 403, 404):
                        # 404 = model mavjud emas -> keyingi modelga o'tamiz.
                        log.warning(
                            "model=%s kalit=%s rad etildi (%s) — keyingi model.",
                            model, self._mask(key), exc.status,
                        )
                        self._cool(key)
                        break  # bu modelni tashlab, keyingi modelga o'tamiz
                    else:
                        log.error("model=%s kalit=%s kutilmagan xato %s.",
                                  model, self._mask(key), exc.status)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    log.warning("model=%s kalit=%s tarmoq xatosi: %s",
                                model, self._mask(key), exc)
                    self._cool(key)

        raise AllKeysFailedError(f"Barcha kalit/model muvaffaqiyatsiz: {last_error}")

    async def generate_image(self, prompt: str, *, count: int = 1) -> list[bytes]:
        """Imagen orqali rasm generatsiyasi (ixtiyoriy)."""
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": count},
        }
        path = "models/imagen-3.0-generate-002:predict"
        last_error: Optional[Exception] = None
        for _ in range(len(self.keys)):
            key = await self._pick_key()
            try:
                data = await self._post(key, path, payload)
                images: list[bytes] = []
                for pred in data.get("predictions", []):
                    b64 = pred.get("bytesBase64Encoded")
                    if b64:
                        images.append(base64.b64decode(b64))
                if images:
                    return images
                last_error = RuntimeError("Rasm qaytmadi.")
            except _HttpError as exc:
                last_error = exc
                self._cool(key)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                self._cool(key)
        raise AllKeysFailedError(f"Rasm generatsiyasi muvaffaqiyatsiz: {last_error}")


class _HttpError(Exception):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:300]}")


def _extract_text(data: dict[str, Any]) -> str:
    """Gemini javobidan matnni ajratib oladi."""
    try:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", []) or []
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        return ""
