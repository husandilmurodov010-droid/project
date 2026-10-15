"""Health-check / keep-alive HTTP server (Render Web Service uchun).

Nega kerak?
    Render'ning BEPUL Web Service tarifi ~15 daqiqa kelgan so'rov
    bo'lmasa "uxlaydi" (spin down). Bot polling bilan ishlasa ham, tashqi
    HTTP so'rov kelmasa uxlab qoladi. Bu kichik aiohttp server:
      * Render'ning health check'iga javob beradi (deploy "healthy" bo'ladi)
      * tashqi keep-alive xizmati (UptimeRobot / cron-job.org) uchun
        yengil endpoint beradi — shu bilan servis uxlamaydi
      * botning holatini (DB, kalitlar, uptime) HTTP orqali ko'rsatadi

Endpointlar:
    GET /        — oddiy HTML sahifa (200)
    GET /health  — JSON holat, DOIM 200 (Render health check shu yerga)
    GET /healthz — /health bilan bir xil (alias)
    GET /ready   — tayyor bo'lsa 200, aks holda 503 (qat'iy tekshiruv)
    GET /ping    — eng yengil javob: "ok" (keep-alive uchun, 200)
    GET /status  — batafsil JSON (uptime, so'rovlar, DB, kalitlar)

Server bot bilan BITTA event loop'da, alohida asyncio task sifatida
ishlaydi — shuning uchun botni bloklamaydi.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import aiohttp
from aiohttp import web

log = logging.getLogger("health")

# Jarayon ishga tushgan vaqt (uptime hisoblash uchun)
START_TIME = time.time()


def _human(seconds: float) -> str:
    """Sekundni odam o'qiydigan ko'rinishga o'giradi (masalan '2h 5m 3s')."""
    total = int(max(0.0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


class HealthState:
    """Bot holatini HTTP orqali ko'rsatish uchun umumiy holat obyekti.

    bot.py ishga tushganda `ready` ni True qiladi va `detail` ga qo'shimcha
    ma'lumot (kalitlar soni, model soni, DB yo'li) yozadi.
    """

    def __init__(self) -> None:
        self.ready: bool = False
        self.detail: dict[str, Any] = {}
        self.requests: int = 0
        self.pings: int = 0
        self.last_request_at: float = 0.0
        self.bot_username: str = ""

    def touch(self) -> None:
        """Har bir kelgan so'rovda chaqiriladi."""
        self.requests += 1
        self.last_request_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        idle = round(now - self.last_request_at, 2) if self.last_request_at else None
        return {
            "status": "ok" if self.ready else "starting",
            "ready": self.ready,
            "bot": self.bot_username or None,
            "uptime_seconds": round(now - START_TIME, 3),
            "uptime_human": _human(now - START_TIME),
            "requests_total": self.requests,
            "keepalive_pings": self.pings,
            "idle_seconds": idle,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            **self.detail,
        }


state = HealthState()


# --------------------------------------------------------------------------- #
# Handlerlar
# --------------------------------------------------------------------------- #
async def _index(request: web.Request) -> web.Response:
    state.touch()
    snap = state.snapshot()
    ok = snap["ready"]
    badge = "&#9989; ishlayapti" if ok else "&#9203; ishga tushmoqda"
    html = f"""<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Manager Bot — status</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 40px 20px; background: #0f172a; color: #e2e8f0; }}
  .card {{ max-width: 620px; margin: 0 auto; background: #1e293b; border-radius: 14px;
          padding: 28px 30px; box-shadow: 0 10px 30px rgba(0,0,0,.35); }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .sub {{ color: #94a3b8; font-size: 14px; margin-bottom: 22px; }}
  .badge {{ display: inline-block; padding: 6px 14px; border-radius: 999px; font-weight: 600;
           font-size: 14px; background: {'#064e3b' if ok else '#78350f'};
           color: {'#6ee7b7' if ok else '#fcd34d'}; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }}
  td {{ padding: 8px 0; border-bottom: 1px solid #334155; }}
  td:first-child {{ color: #94a3b8; }}
  code {{ background: #0f172a; padding: 2px 6px; border-radius: 5px; font-size: 13px; }}
  a {{ color: #60a5fa; }}
</style>
</head>
<body>
  <div class="card">
    <h1>🤖 AI Manager Bot</h1>
    <div class="sub">Kamida 24/7 uzluksiz ishlash uchun health-check serveri</div>
    <div class="badge">{badge}</div>
    <table>
      <tr><td>Bot</td><td><code>{snap['bot'] or '—'}</code></td></tr>
      <tr><td>Uptime</td><td>{snap['uptime_human']}</td></tr>
      <tr><td>Gemini kalitlar</td><td>{snap.get('keys', '—')}</td></tr>
      <tr><td>Modellar</td><td>{snap.get('models', '—')}</td></tr>
      <tr><td>Baza</td><td><code>{snap.get('db', '—')}</code></td></tr>
      <tr><td>Zaxiralash (Gist)</td><td>{'✅ yoqilgan' if snap.get('backup_enabled') else '⛔ o&#39;chirilgan'}</td></tr>
      <tr><td>HTTP so'rovlar</td><td>{snap['requests_total']}</td></tr>
      <tr><td>Tekshirilgan</td><td>{snap['checked_at']}</td></tr>
    </table>
    <p style="margin-top:20px;font-size:13px;color:#94a3b8">
      Endpointlar: <a href="/health">/health</a> · <a href="/ready">/ready</a> ·
      <a href="/ping">/ping</a> · <a href="/status">/status</a>
    </p>
  </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def _health(request: web.Request) -> web.Response:
    """Render health check + keep-alive uchun: jarayon tirik bo'lsa DOIM 200."""
    state.touch()
    return web.json_response(state.snapshot(), status=200)


async def _ready(request: web.Request) -> web.Response:
    """Qat'iy tekshiruv: bot to'liq tayyor bo'lmasa 503."""
    state.touch()
    return web.json_response(state.snapshot(), status=200 if state.ready else 503)


async def _ping(request: web.Request) -> web.Response:
    """Eng yengil javob (keep-alive pingerlar uchun)."""
    state.touch()
    state.pings += 1
    return web.Response(text="ok", content_type="text/plain", charset="utf-8")


async def _status(request: web.Request) -> web.Response:
    state.touch()
    return web.json_response(state.snapshot(), status=200)


# --------------------------------------------------------------------------- #
# Serverni ishga tushirish
# --------------------------------------------------------------------------- #
async def start_health_server(
    port: int,
    host: str = "0.0.0.0",
    access_log: bool = False,
) -> Optional[web.AppRunner]:
    """Health server'ni ishga tushiradi. `port <= 0` bo'lsa o'chiq qoladi.

    Qaytaradi: `web.AppRunner` (to'xtatish uchun `await runner.cleanup()`),
    o'chirilgan bo'lsa `None`.
    """
    if not port or port <= 0:
        log.info("Health server o'chirilgan (PORT=%s).", port)
        return None

    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/healthz", _health)
    app.router.add_get("/ready", _ready)
    app.router.add_get("/ping", _ping)
    app.router.add_get("/status", _status)

    runner = web.AppRunner(app, access_log=None if not access_log else log)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Health server tayyor: http://%s:%d/health", host, port)
    return runner


async def keepalive_loop(url: str, interval: int = 600) -> None:
    """O'z-o'zini ping qilish (Render uxlab qolmasligi uchun qo'shimcha himoya).

    Render'da `RENDER_EXTERNAL_URL` avtomatik beriladi — shu tufayli tashqi
    xizmat (UptimeRobot) bo'lmasa ham servis uyg'oq qoladi. Bu funksiya
    asosiy himoya emas, qo'shimcha qatlam: ba'zi holatlarda tashqi pinger
    ancha ishonchli ishlaydi.
    """
    if not url:
        log.info("Self-ping o'chirilgan (URL berilmagan).")
        return

    interval = max(60, int(interval))
    log.info("Self-ping yoqildi: %s (har %ds)", url, interval)

    # Bot to'liq ishga tushishini kutish
    await asyncio.sleep(30)

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    state.pings += 1
                    log.debug("self-ping -> %s (%s)", url, resp.status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("self-ping xato: %s", exc)
            await asyncio.sleep(interval)
