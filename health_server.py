"""Health-check + keep-alive HTTP server for Render web services.

Endpoints:  /health  /ready  /ping  /status  /
"""
import logging
import time

from aiohttp import web

log = logging.getLogger("health")

STARTED_AT = time.time()


class HealthServer:
    """Tiny aiohttp app exposing the bot's liveness and readiness."""

    def __init__(self, port, state_provider=None):
        self.port = int(port)
        self.state_provider = state_provider or (lambda: {})
        self.runner = None
        self.ready = False

    # ------------------------------------------------------------- handlers
    async def _health(self, request):
        return web.json_response(self._payload(status="ok"))

    async def _ready(self, request):
        payload = self._payload(status="ok" if self.ready else "starting")
        return web.json_response(payload, status=200 if self.ready else 503)

    async def _ping(self, request):
        return web.Response(text="ok")

    async def _status(self, request):
        return web.json_response(self._payload(status="ok", full=True))

    async def _root(self, request):
        return web.json_response({"service": "ai-manager-bot", "endpoints": [
            "/health", "/ready", "/ping", "/status"]})

    def _payload(self, status, full=False):
        base = {"status": status, "ready": self.ready}
        try:
            extra = self.state_provider() or {}
        except Exception as e:  # never let the health endpoint 500
            log.warning("state provider failed: %s", e)
            extra = {}
        base.update(extra)
        base["uptime_s"] = round(time.time() - STARTED_AT)
        if full:
            base["uptime_human"] = _human(base["uptime_s"])
        else:
            base.pop("keys_detail", None)
        return base

    # ------------------------------------------------------------- lifecycle
    def build(self):
        app = web.Application()
        app.router.add_get("/", self._root)
        app.router.add_get("/health", self._health)
        app.router.add_get("/ready", self._ready)
        app.router.add_get("/ping", self._ping)
        app.router.add_get("/status", self._status)
        return app

    async def start(self):
        self.runner = web.AppRunner(self.build(), access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        log.info("health server listening on 0.0.0.0:%s", self.port)

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()


def _human(seconds):
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m}m {sec}s"
