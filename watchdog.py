"""Runtime watchdog: watches memory growth and event-loop lag.

If memory exceeds the configured ceiling the process exits cleanly so that
start.sh restarts it (far better than an uncontrolled OOM kill).
"""
import asyncio
import gc
import logging
import os
import sys
import time

from config import WATCHDOG_GC_EVERY, WATCHDOG_INTERVAL, WATCHDOG_MEMORY_LIMIT_MB

log = logging.getLogger("watchdog")

try:
    import resource

    def _rss_mb():
        """Resident set size in MB (Linux reports KiB, macOS reports bytes)."""
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return usage / (1024.0 * 1024.0)
        return usage / 1024.0
except Exception:  # pragma: no cover
    def _rss_mb():
        return 0.0


class Watchdog:
    def __init__(self, interval=WATCHDOG_INTERVAL, memory_limit_mb=WATCHDOG_MEMORY_LIMIT_MB,
                 gc_every=WATCHDOG_GC_EVERY):
        self.interval = max(30, int(interval))
        self.memory_limit_mb = int(memory_limit_mb)
        self.gc_every = max(1, int(gc_every))
        self.checks = 0
        self.memory_mb = 0.0
        self.memory_peak_mb = 0.0
        self.loop_lag_ms = 0.0
        self.restarts = 0
        self._task = None

    async def _loop(self):
        while True:
            started = time.monotonic()
            await asyncio.sleep(self.interval)

            self.memory_mb = round(_rss_mb(), 1)
            self.memory_peak_mb = max(self.memory_peak_mb, self.memory_mb)
            self.checks += 1

            if self.checks % self.gc_every == 0:
                gc.collect()

            if self.memory_limit_mb and self.memory_mb > self.memory_limit_mb:
                log.error("MEMORY LIMIT EXCEEDED: %.0f MB > %s MB -> clean restart",
                          self.memory_mb, self.memory_limit_mb)
                self.restarts += 1
                await asyncio.sleep(0.5)
                os._exit(42)

            drift = (time.monotonic() - started - self.interval) * 1000.0
            self.loop_lag_ms = round(drift, 1)
            if drift > 5000:
                log.warning("event loop lag %.0f ms detected", drift)
            else:
                log.debug("watchdog ok: rss=%.1f MB lag=%.0f ms", self.memory_mb, drift)

    def start(self):
        if self.interval <= 0:
            return
        self._task = asyncio.create_task(self._loop())
        log.info("watchdog started (interval=%ss limit=%sMB)", self.interval, self.memory_limit_mb or "off")

    def stop(self):
        if self._task:
            self._task.cancel()

    def status(self):
        return {
            "memory_mb": self.memory_mb,
            "memory_peak_mb": self.memory_peak_mb,
            "loop_lag_ms": self.loop_lag_ms,
            "watchdog_checks": self.checks,
        }
