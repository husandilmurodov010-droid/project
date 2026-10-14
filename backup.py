"""SQLite -> GitHub Gist periodic backup / restore.

Render's free tier has an ephemeral disk: bot.db disappears on every deploy or
restart. We push a consistent snapshot (VACUUM INTO -> gzip -> base64) to a
secret gist and restore it on boot. base64 is required because the Gist API
only accepts text files.
"""
import asyncio
import base64
import gzip
import logging
import os
import sqlite3
import tempfile

import aiohttp

from config import (
    BACKUP_ENABLED,
    BACKUP_INTERVAL_SECONDS,
    DB_PATH,
    GIST_ID,
    GITHUB_TOKEN,
    RESTORE_ON_START,
)

log = logging.getLogger("backup")

API = "https://api.github.com"
FILENAME = "bot.db.b64.gz"


class BackupManager:
    def __init__(self, db_path=None, token=None, gist_id=None, interval=None):
        self.db_path = db_path or DB_PATH
        self.token = token if token is not None else GITHUB_TOKEN
        self.gist_id = gist_id if gist_id is not None else GIST_ID
        self.interval = int(interval if interval is not None else BACKUP_INTERVAL_SECONDS)
        self.count = 0
        self.last_backup = None
        self.last_error = None
        self._task = None

    @property
    def enabled(self):
        return bool(BACKUP_ENABLED and self.token)

    # ------------------------------------------------------------- snapshot
    def _snapshot_b64(self):
        """VACUUM INTO a temp file, gzip + base64 it. Safe while the bot writes."""
        tmp = tempfile.NamedTemporaryFile(prefix="botdb_", suffix=".db", delete=False)
        tmp.close()
        try:
            src = sqlite3.connect(self.db_path)
            try:
                src.execute("VACUUM INTO ?", (tmp.name,))
            finally:
                src.close()
            with open(tmp.name, "rb") as f:
                raw = f.read()
            return base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _restore_b64(self, payload):
        raw = gzip.decompress(base64.b64decode(payload))
        tmp = tempfile.NamedTemporaryFile(prefix="restore_", suffix=".db", delete=False)
        tmp.write(raw)
        tmp.close()
        os.replace(tmp.name, self.db_path)
        return len(raw)

    # ------------------------------------------------------------- gist I/O
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json"}

    async def upload(self):
        if not self.enabled:
            return False
        payload = await asyncio.to_thread(self._snapshot_b64)
        files = {FILENAME: {"content": payload}}
        async with aiohttp.ClientSession() as s:
            if self.gist_id:
                url = f"{API}/gists/{self.gist_id}"
                async with s.patch(url, headers=self._headers(), json={"files": files}) as r:
                    ok = r.status in (200, 201)
                    if not ok:
                        self.last_error = f"PATCH {r.status}: {(await r.text())[:180]}"
                        return False
            else:
                desc = "AI Manager Bot - SQLite backup (auto-generated)"
                async with s.post(f"{API}/gists", headers=self._headers(),
                                  json={"description": desc, "public": False, "files": files}) as r:
                    if r.status not in (200, 201):
                        self.last_error = f"POST {r.status}: {(await r.text())[:180]}"
                        return False
                    data = await r.json()
                    self.gist_id = data.get("id")
                    log.warning("YANGI GIST YARATILDI: %s - bu id'ni env (GIST_ID) sifatida saqlang!", self.gist_id)
        self.count += 1
        self.last_backup = _now()
        self.last_error = None
        log.info("zaxiralandi (#%d) -> gist %s", self.count, self.gist_id)
        return True

    async def download(self):
        if not (self.token and self.gist_id):
            return False
        async with aiohttp.ClientSession() as s:
            url = f"{API}/gists/{self.gist_id}"
            async with s.get(url, headers=self._headers()) as r:
                if r.status != 200:
                    log.warning("gist olinmadi: HTTP %s", r.status)
                    return False
                data = await r.json()
        f = (data.get("files") or {}).get(FILENAME)
        if not f or not f.get("raw_url"):
            log.info("gist'da zaxira fayli yo'q")
            return False
        async with aiohttp.ClientSession() as s:
            async with s.get(f["raw_url"]) as r:
                if r.status != 200:
                    return False
                payload = await r.text()
        size = await asyncio.to_thread(self._restore_b64, payload)
        log.info("baza zaxiradan tiklandi (%.1f KB)", size / 1024.0)
        self.count += 1
        return True

    async def restore_on_start(self):
        if not (RESTORE_ON_START and self.token and self.gist_id):
            log.info("baza mavjud - tiklash shart emas")
            return False
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 0:
            log.info("lokal baza mavjud - tiklash o'tkazib yuborildi")
            return False
        try:
            return await self.download()
        except Exception as e:
            log.warning("tiklash amalga oshmadi: %s", e)
            return False

    # ------------------------------------------------------------- loop
    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.upload()
            except Exception as e:
                self.last_error = str(e)[:200]
                log.warning("zaxiralash xatosi: %s", e)

    def start(self):
        if not self.enabled:
            return
        if self.interval < 60:
            self.interval = 60
        self._task = asyncio.create_task(self._loop())
        log.info("gist zaxirasi yoqildi (har %ss)", self.interval)

    def stop(self):
        if self._task:
            self._task.cancel()

    def status(self):
        return {
            "backup_enabled": self.enabled,
            "backup_count": self.count,
            "last_backup": self.last_backup,
            "backup_error": self.last_error,
            "gist_id": self.gist_id or None,
        }


def _now():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
