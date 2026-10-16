"""SQLite bazani GitHub Gist'ga zaxiralash va tiklash.

MUAMMO
    Render'ning bepul tarifida disk VAQTINCHA (ephemeral): har deploy,
    qayta ishga tushish yoki uxlashdan keyin `bot.db` yo'qoladi — ya'ni
    foydalanuvchilar, suhbat tarixi, test natijalari o'chib ketadi.

YECHIM (shu modul)
    Baza davriy ravishda GitHub Gist'ga (bepul, xususiy) zaxiralanadi va
    bot qayta ishga tushganda avtomatik tiklanadi. SQLite kodi o'zgarmaydi —
    barcha so'rovlar avvalgidek ishlaydi.

Nega Gist?
    * bepul, qo'shimcha server kerak emas
    * xususiy (secret) gist — faqat token bilan ko'rinadi
    * oddiy: faqat GitHub token + bitta gist id

Alternativalar (README'da batafsil):
    * Render Persistent Disk (pullik) — eng oson, lekin bepul tarifda yo'q
    * tashqi PostgreSQL (Neon/Supabase) — eng mustahkam, lekin kod
      o'zgarishini talab qiladi (aiosqlite -> asyncpg)

Kerakli muhit o'zgaruvchilari:
    BACKUP_ENABLED=true
    GITHUB_TOKEN=ghp_...      (klassik PAT, `gist` scope bilan)
    GIST_ID=...               (ixtiyoriy: bo'lmasa avtomatik yaratiladi)
    BACKUP_INTERVAL_SECONDS=3600
    RESTORE_ON_START=true
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp

log = logging.getLogger("backup")

GIST_API = "https://api.github.com/gists"
BACKUP_FILENAME = "bot.db.b64.gz"
# Kanal ro'yxatining ALOHIDA matnli nusxasi (DB tiklanmasa ham kanallar
# saqlanib qolishi uchun "ikkinchi kamar").
CHANNELS_REPLICA_FILENAME = "channels.json"
GIST_DESCRIPTION = "AI Manager Bot — SQLite backup (avtomatik)"


class BackupError(RuntimeError):
    """Zaxiralash/tiklash bilan bog'liq xatolik."""


def _snapshot(src: str, dst: str) -> None:
    """SQLite'dan izchil (consistent) nusxa oladi.

    `VACUUM INTO` WAL rejimida ham xavfsiz: bot yozib turganda ham
    buzilmagan, to'liq nusxa beradi (faylni oddiy `cp` qilishdan farqli).
    SQLite >= 3.27 talab qiladi (Python 3.11 bilan birga keladi).
    """
    conn = sqlite3.connect(src)
    try:
        conn.execute("VACUUM INTO ?", (dst,))
    finally:
        conn.close()


class BackupManager:
    """GitHub Gist orqali DB zaxiralash/tiklash menejeri."""

    def __init__(
        self,
        db_path: str,
        token: str = "",
        gist_id: str = "",
        interval: int = 3600,
        restore_on_start: bool = True,
        filename: str = BACKUP_FILENAME,
    ) -> None:
        self.db_path = db_path
        self.token = (token or "").strip()
        self.gist_id = (gist_id or "").strip()
        # Gist id'ni lokal faylda ham saqlaymiz: env (GIST_ID) berilmagan
        # bo'lsa ham bir marta yaratilgan gist qayta ishlatiladi (yangi gist
        # yaratib yuborilmaydi).
        self.gist_id_file = str(Path(db_path).with_suffix(".gistid"))
        if not self.gist_id:
            self.gist_id = self._load_local_gist_id()
        self.interval = max(300, int(interval))
        self.restore_on_start = bool(restore_on_start)
        self.filename = filename

        self.last_backup_at: float = 0.0
        self.backup_count: int = 0
        self.last_error: Optional[str] = None
        self._timeout = aiohttp.ClientTimeout(total=90)

    # ------------------------------------------------------------------ #
    # Holat
    # ------------------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def stats(self) -> dict[str, Any]:
        return {
            "backup_enabled": self.enabled,
            "backup_count": self.backup_count,
            "backup_interval": self.interval,
            "gist_id": self.gist_id or None,
            "last_backup": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_backup_at))
                if self.last_backup_at
                else None
            ),
            "last_error": self.last_error,
        }

    def last_backup_human(self) -> str:
        if not self.last_backup_at:
            return "hali zaxiralanmagan"
        delta = int(time.time() - self.last_backup_at)
        return f"{delta}s oldin ({time.strftime('%H:%M:%S', time.localtime(self.last_backup_at))})"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-manager-bot",
        }

    # ------------------------------------------------------------------ #
    # Gist id'ni lokal saqlash (env bo'lmasa ham barqaror ishlash uchun)
    # ------------------------------------------------------------------ #
    def _load_local_gist_id(self) -> str:
        try:
            p = Path(self.gist_id_file)
            if p.exists():
                val = p.read_text(encoding="utf-8").strip()
                if val:
                    log.info("Gist id lokal fayldan olindi: %s", val)
                    return val
        except Exception as exc:  # noqa: BLE001
            log.debug("Lokal gist id'ni o'qib bo'lmadi: %s", exc)
        return ""

    def _save_local_gist_id(self) -> None:
        if not self.gist_id:
            return
        try:
            Path(self.gist_id_file).write_text(self.gist_id, encoding="utf-8")
            log.info("Gist id lokal faylga yozildi: %s", self.gist_id_file)
        except Exception as exc:  # noqa: BLE001
            log.debug("Lokal gist id'ni yozib bo'lmadi: %s", exc)

    @staticmethod
    def _db_is_empty(path: str) -> bool:
        """Bazada na foydalanuvchi, na kanal bo'lsa — "bo'sh" hisoblanadi.

        Bunday bazani zaxiradan tiklash XAVFSIZ: yo'qotadigan ma'lumot yo'q.
        """
        try:
            conn = sqlite3.connect(path)
            try:
                users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                chans = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            finally:
                conn.close()
            return (int(users) + int(chans)) == 0
        except Exception:  # noqa: BLE001
            # Jadval yo'q / fayl buzuq — tiklashga urinish foydali.
            return True

    # ------------------------------------------------------------------ #
    # Kanal ro'yxati replikasi (channels.json) — qo'shimcha kafolat
    # ------------------------------------------------------------------ #
    async def push_channels(self, channels: list[dict[str, Any]]) -> bool:
        """Kanallar ro'yxatini gist'dagi `channels.json` nusxasiga yozadi."""
        if not self.enabled:
            return False
        try:
            gist_id = await self.ensure_gist()
        except Exception as exc:  # noqa: BLE001
            log.error("Kanal nusxasi: gist tayyorlanmadi: %s", exc)
            return False
        payload = json.dumps(
            {"saved_at": time.time(), "channels": channels},
            ensure_ascii=False, indent=1,
        )
        body = {"files": {CHANNELS_REPLICA_FILENAME: {"content": payload}}}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.patch(
                    f"{GIST_API}/{gist_id}", headers=self._headers(), json=body
                ) as resp:
                    if resp.status >= 400:
                        text = (await resp.text())[:200]
                        log.error("Kanal nusxasini yozishda xato %s: %s", resp.status, text)
                        return False
        except Exception as exc:  # noqa: BLE001
            log.error("Kanal nusxasini yozishda tarmoq xatosi: %s", exc)
            return False
        log.info("Kanal nusxasi saqlandi: %d ta kanal", len(channels))
        return True

    async def pull_channels(self) -> list[dict[str, Any]]:
        """gist'dagi `channels.json` nusxasini o'qiydi (bo'lmasa — bo'sh ro'yxat)."""
        if not self.enabled:
            return []
        gist_id = self.gist_id or self._load_local_gist_id()
        if not gist_id:
            return []
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(
                    f"{GIST_API}/{gist_id}", headers=self._headers()
                ) as resp:
                    if resp.status >= 400:
                        return []
                    data = await resp.json()
                files = data.get("files") or {}
                f = files.get(CHANNELS_REPLICA_FILENAME)
                if not f:
                    return []
                content = f.get("content") or ""
                if f.get("truncated") or not content:
                    raw_url = f.get("raw_url") or ""
                    if raw_url:
                        async with session.get(
                            raw_url, headers={"User-Agent": "ai-manager-bot"}
                        ) as rr:
                            content = await rr.text()
        except Exception as exc:  # noqa: BLE001
            log.error("Kanal nusxasini o'qishda xato: %s", exc)
            return []
        try:
            obj = json.loads(content or "{}")
            chans = obj.get("channels") or []
            log.info("Kanal nusxasidan %d ta kanal o'qildi.", len(chans))
            return chans
        except Exception as exc:  # noqa: BLE001
            log.error("Kanal nusxasini tahlil qilishda xato: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Gist
    # ------------------------------------------------------------------ #
    async def ensure_gist(self) -> str:
        """Gist id bo'lmasa — yangi (xususiy) gist yaratadi va id'sini qaytaradi."""
        if self.gist_id:
            return self.gist_id

        if not self.enabled:
            raise BackupError("GITHUB_TOKEN berilmagan.")

        body = {
            "description": GIST_DESCRIPTION,
            "public": False,
            "files": {self.filename: {"content": "{}"}},
        }
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(GIST_API, headers=self._headers(), json=body) as resp:
                if resp.status >= 400:
                    text = (await resp.text())[:300]
                    raise BackupError(f"Gist yaratishda xato {resp.status}: {text}")
                data = await resp.json()

        self.gist_id = data.get("id", "")
        self._save_local_gist_id()
        log.warning(
            "YANGI GIST YARATILDI: %s — bu id'ni env (GIST_ID) sifatida saqlang!",
            self.gist_id,
        )
        return self.gist_id

    # ------------------------------------------------------------------ #
    # Push (zaxiralash)
    # ------------------------------------------------------------------ #
    async def push(self) -> bool:
        """Bazani gist'ga zaxiralaydi. Muvaffaqiyatli bo'lsa True."""
        if not self.enabled:
            log.debug("Zaxiralash o'chirilgan (token yo'q).")
            return False

        src = Path(self.db_path)
        if not src.exists():
            log.warning("Zaxiralash uchun baza topilmadi: %s", src)
            return False

        tmp = Path(tempfile.gettempdir()) / f"aibot_backup_{int(time.time() * 1000)}.db"
        try:
            # 1) Izchil nusxa (bloklovchi IO -> alohida thread)
            try:
                await asyncio.to_thread(_snapshot, str(src), str(tmp))
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"snapshot: {exc}"
                log.error("Nusxa olishda xato: %s", exc)
                return False

            # 2) Siqish + base64 (gist faqat matn qabul qiladi)
            raw = await asyncio.to_thread(tmp.read_bytes)
            payload = await asyncio.to_thread(
                lambda b: base64.b64encode(gzip.compress(b, 9)).decode("ascii"), raw
            )
        finally:
            tmp.unlink(missing_ok=True)

        # 3) Gist'ga yozish
        try:
            gist_id = await self.ensure_gist()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            log.error("Gist tayyorlashda xato: %s", exc)
            return False

        body = {
            "description": GIST_DESCRIPTION,
            "files": {
                self.filename: {
                    "content": payload,
                }
            },
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.patch(
                    f"{GIST_API}/{gist_id}", headers=self._headers(), json=body
                ) as resp:
                    if resp.status >= 400:
                        text = (await resp.text())[:300]
                        self.last_error = f"HTTP {resp.status}: {text}"
                        log.error("Zaxiralashda xato %s: %s", resp.status, text)
                        return False
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            log.error("Zaxiralashda tarmoq xatosi: %s", exc)
            return False

        self.last_backup_at = time.time()
        self.backup_count += 1
        self.last_error = None
        log.info(
            "✅ Baza zaxiralandi: %.1f KB (xom %.1f KB, gist=%s)",
            len(payload) / 1024,
            len(raw) / 1024,
            gist_id,
        )
        return True

    # ------------------------------------------------------------------ #
    # Pull (tiklash)
    # ------------------------------------------------------------------ #
    async def pull(self) -> bool:
        """Gist'dagi zaxiradan bazani tiklaydi. Muvaffaqiyatli bo'lsa True."""
        if not self.enabled or not self.gist_id:
            log.info("Tiklash o'tkazib yuborildi (token yoki GIST_ID yo'q).")
            return False

        content = ""
        raw_url = ""
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(
                    f"{GIST_API}/{self.gist_id}", headers=self._headers()
                ) as resp:
                    if resp.status == 404:
                        log.warning("Gist topilmadi (GIST_ID=%s).", self.gist_id)
                        return False
                    if resp.status >= 400:
                        text = (await resp.text())[:300]
                        self.last_error = f"HTTP {resp.status}"
                        log.error("Zaxiradan o'qishda xato %s: %s", resp.status, text)
                        return False
                    data = await resp.json()

                files = data.get("files") or {}
                f = files.get(self.filename)
                if not f:
                    log.warning("Gist ichida '%s' fayli yo'q.", self.filename)
                    return False

                content = f.get("content") or ""
                # Gist API 1 MB dan katta fayllar uchun content'ni bo'sh
                # qaytaradi (truncated=true) — to'liq matn raw_url'da.
                if f.get("truncated") or not content:
                    raw_url = f.get("raw_url") or ""

                if raw_url:
                    async with session.get(
                        raw_url, headers={"User-Agent": "ai-manager-bot"}
                    ) as rr:
                        if rr.status >= 400:
                            log.error("raw_url'dan o'qishda xato %s", rr.status)
                            return False
                        content = await rr.text()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            log.error("Tiklashda tarmoq xatosi: %s", exc)
            return False

        if not content.strip() or content.strip() == "{}":
            log.info("Zaxira bo'sh — tiklanadigan ma'lumot yo'q.")
            return False

        # Ochish
        try:
            packed = base64.b64decode(content)
            raw = gzip.decompress(packed)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"decode: {exc}"
            log.error("Zaxirani ochishda xato: %s", exc)
            return False

        # Yozish (eski WAL/SHM qoldiqlarini tozalab)
        dst = Path(self.db_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{dst}{suffix}").unlink(missing_ok=True)
        try:
            await asyncio.to_thread(dst.write_bytes, raw)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"write: {exc}"
            log.error("Zaxirani yozishda xato: %s", exc)
            return False

        log.info("✅ Baza zaxiradan tiklandi: %.1f KB -> %s", len(raw) / 1024, dst)
        return True

    async def restore_if_needed(self, force: bool = False) -> bool:
        """Bazani zaxiradan tiklaydi.

        Tiklash SHARTLARI (restart/deploy'da kanallar yo'qolmasligi uchun):
          1) baza fayli umuman yo'q (yangi konteyner), YOKI
          2) baza bor, lekin BO'SH (na foydalanuvchi, na kanal) — bu holat
             yangi konteynerda bootstrap bo'sh fayl yaratganda yuz beradi,
          3) `force=True`.

        Baza ma'lumotli bo'lsa — TEGILMAYDI (ma'lumot yo'qolmaydi).
        """
        if not self.enabled:
            log.info("Tiklash o'chirilgan (GITHUB_TOKEN yo'q).")
            return False

        if not self.gist_id:
            self.gist_id = self._load_local_gist_id()

        exists = Path(self.db_path).exists()
        if exists and not force and not self._db_is_empty(self.db_path):
            log.info("Baza mavjud va ma'lumotli — tiklash shart emas (%s).", self.db_path)
            return False

        if not self.gist_id:
            log.warning(
                "GIST_ID berilmagan va lokal fayl ham yo'q — tiklab bo'lmaydi. "
                "Render env'ga GIST_ID qo'shing yoki birinchi backup'ni kuting."
            )
            return False

        reason = "force" if force else ("baza yo'q" if not exists else "baza bo'sh")
        log.info("Zaxiradan tiklanmoqda (sabab: %s)...", reason)
        return await self.pull()

    # ------------------------------------------------------------------ #
    # Fon vazifasi
    # ------------------------------------------------------------------ #
    async def loop(self) -> None:
        """Davriy zaxiralash sikli (asyncio task sifatida ishga tushiriladi)."""
        if not self.enabled:
            log.info("Zaxiralash o'chirilgan (GITHUB_TOKEN berilmagan).")
            return

        log.info("Zaxiralash yoqilgan: har %ds da GitHub Gist'ga.", self.interval)
        await asyncio.sleep(20)  # bot to'liq ishga tushishini kutish

        # Ishga tushgach darhol bir marta zaxiralaymiz — shunda baza
        # tez orada gist'da paydo bo'ladi (va tiklash uchun mavjud bo'ladi).
        try:
            await self.push()
        except Exception as exc:  # noqa: BLE001
            log.error("Boshlang'ich zaxiralashda xato: %s", exc)

        while True:
            try:
                await self.push()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.error("Zaxiralash siklida kutilmagan xato: %s", exc)
            await asyncio.sleep(self.interval)
