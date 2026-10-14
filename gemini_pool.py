"""Multi-key / multi-model Gemini pool.

* Round-robin over API keys, walking models on the outside.
* Failover: 429 -> 60s cooldown, 401/403 -> 30min, 5xx -> 20s,
  404 -> the MODEL is dead for the rest of the process lifetime.
* 400 (bad request) is non-retryable and raised immediately.
"""
import asyncio
import base64
import json
import logging
import time

import aiohttp

from config import (
    GEMINI_API_KEYS,
    GEMINI_IMAGE_MODELS,
    GEMINI_MODELS,
    COOLDOWN_SECONDS,
    REQUEST_TIMEOUT,
)

log = logging.getLogger("gemini")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class AllKeysFailed(Exception):
    """Raised when no key could serve the request."""


class KeyState:
    __slots__ = ("key", "index", "cooldown_until", "fails", "wins")

    def __init__(self, key, index):
        self.key = key
        self.index = index
        self.cooldown_until = 0.0
        self.fails = 0
        self.wins = 0

    @property
    def short(self):
        return f"{self.key[:6]}...{self.key[-4:]}" if len(self.key) > 12 else "***"

    def available(self):
        return time.time() >= self.cooldown_until

    def cool(self, seconds, reason):
        self.cooldown_until = time.time() + seconds
        self.fails += 1
        log.warning("key %s cooling %ss (%s)", self.short, seconds, reason)


class GeminiPool:
    def __init__(self, keys=None, models=None, image_models=None):
        keys = keys if keys is not None else GEMINI_API_KEYS
        self.keys = [KeyState(k, i) for i, k in enumerate(keys)]
        self.models = list(models or GEMINI_MODELS)
        self.image_models = list(image_models or GEMINI_IMAGE_MODELS)
        self.dead_models = set()
        self.cursor = 0
        self.requests_total = 0
        self.errors_total = 0

    # ------------------------------------------------------------- helpers
    @property
    def n_keys(self):
        return len(self.keys)

    def _ordered_keys(self):
        """Round-robin start point, then everyone else still in cooldown order."""
        if not self.keys:
            return []
        n = len(self.keys)
        order = [self.keys[(self.cursor + i) % n] for i in range(n)]
        now = time.time()
        return sorted(order, key=lambda k: (0 if k.cooldown_until <= now else 1, k.cooldown_until))

    def _advance(self, used):
        if not self.keys:
            return
        self.cursor = (used.index + 1) % len(self.keys)

    def available_models(self, pool):
        return [m for m in pool if m not in self.dead_models]

    # ------------------------------------------------------------- public API
    async def generate(self, contents, system_instruction=None, temperature=0.7,
                       max_output_tokens=2048, models=None, json_mode=False):
        """Return the model's text answer.

        contents: Gemini 'contents' list, e.g.
            [{"role": "user", "parts": [{"text": "hi"}]}]
        """
        if not self.keys:
            raise AllKeysFailed("Hech qanday Gemini kaliti sozlanmagan.")

        pool = self.available_models(models or self.models)
        if not pool:
            # every model marked dead -> reset and try once more
            self.dead_models.clear()
            pool = list(models or self.models)

        body_base = {"contents": contents, "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }}
        if system_instruction:
            body_base["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if json_mode:
            body_base["generationConfig"]["responseMimeType"] = "application/json"

        last_error = None
        for model in pool:
            for attempt in range(2):
                for ks in self._ordered_keys():
                    if not ks.available() and attempt == 0:
                        continue
                    try:
                        text = await self._call(model, ks.key, body_base)
                        ks.wins += 1
                        self._advance(ks)
                        self.requests_total += 1
                        return text
                    except _ModelDead as e:
                        log.warning("model %s dead: %s", model, e)
                        self.dead_models.add(model)
                        last_error = e
                        break
                    except _KeyProblem as e:
                        ks.cool(e.cooldown, e.reason)
                        self.errors_total += 1
                        last_error = e
                        continue
                    except _Fatal as e:
                        self.errors_total += 1
                        raise
                else:
                    # inner loop finished without break -> try a short wait once
                    if attempt == 0 and self.keys:
                        soonest = min((k.cooldown_until for k in self.keys), default=0)
                        wait = min(max(soonest - time.time(), 0), 65)
                        if wait > 0:
                            log.info("all keys cooling, waiting %.1fs", wait)
                            await asyncio.sleep(wait)
                            continue
                    break
            else:
                continue

        raise AllKeysFailed(str(last_error) if last_error else "Barcha kalitlar va modellar ishlamadi.")

    async def generate_image(self, prompt):
        """Generate an image, return raw bytes (PNG/JPEG)."""
        if not self.keys:
            raise AllKeysFailed("Hech qanday Gemini kaliti sozlanmagan.")
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        pool = self.available_models(self.image_models) or list(self.image_models)
        last_error = None
        for model in pool:
            for ks in self._ordered_keys():
                try:
                    return await self._call_image(model, ks.key, body)
                except _ModelDead as e:
                    self.dead_models.add(model)
                    last_error = e
                    break
                except _KeyProblem as e:
                    ks.cool(e.cooldown, e.reason)
                    last_error = e
                    continue
                except _Fatal as e:
                    last_error = e
                    raise AllKeysFailed(str(e))
        raise AllKeysFailed(str(last_error) if last_error else "Rasm yaratilmadi.")

    # ------------------------------------------------------------- transport
    async def _post(self, model, key, body):
        url = f"{API_ROOT}/{model}:generateContent?key={key}"
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, json=body) as r:
                data = await r.json(content_type=None)
                return r.status, data

    async def _call(self, model, key, body):
        status, data = await self._post(model, key, body)
        self._classify(model, status, data)
        try:
            cands = data.get("candidates") or []
            parts = cands[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError):
            raise _Fatal(f"Kutilmagan javob formati: {json.dumps(data)[:200]}")

    async def _call_image(self, model, key, body):
        status, data = await self._post(model, key, body)
        self._classify(model, status, data)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            for p in parts:
                inline = p.get("inlineData") or p.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        except (KeyError, IndexError, TypeError):
            pass
        raise _Fatal("Model rasm qaytarmadi.")

    @staticmethod
    def _classify(model, status, data):
        if status == 200:
            return
        msg = ""
        try:
            msg = (data.get("error") or {}).get("message", "")
        except AttributeError:
            msg = str(data)[:200]
        if status == 404 or "no longer available" in msg or "not found" in msg.lower():
            raise _ModelDead(f"HTTP {status}: {msg[:160]}")
        if status == 429:
            raise _KeyProblem("quota/rate limit", cooldown=COOLDOWN_SECONDS)
        if status in (401, 403):
            raise _KeyProblem(f"auth ({status})", cooldown=1800)
        if 500 <= status < 600:
            raise _KeyProblem(f"server {status}", cooldown=20)
        if status == 400:
            raise _Fatal(f"HTTP 400: {msg[:200]}")
        raise _KeyProblem(f"HTTP {status}", cooldown=30)

    # ------------------------------------------------------------- status
    def status(self):
        now = time.time()
        return {
            "keys": self.n_keys,
            "keys_ready": sum(1 for k in self.keys if k.available()),
            "models": len(self.models),
            "models_dead": sorted(self.dead_models),
            "requests_total": self.requests_total,
            "errors_total": self.errors_total,
            "keys_detail": [
                {
                    "key": k.short,
                    "ready": k.available(),
                    "cooldown_s": max(0, round(k.cooldown_until - now)),
                    "wins": k.wins,
                    "fails": k.fails,
                }
                for k in self.keys
            ],
        }


class _ModelDead(Exception):
    pass


class _KeyProblem(Exception):
    def __init__(self, reason, cooldown=60):
        super().__init__(reason)
        self.reason = reason
        self.cooldown = cooldown


class _Fatal(Exception):
    pass


pool = GeminiPool()
