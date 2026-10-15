"""Watchdog — 24/7 uzluksiz ishlash uchun barqarorlik qatlami.

Nega kerak?
    Bot kunlab (haftalab) to'xtovsiz ishlaganda ikki xavf bor:
      1) Xotira oqib ketishi (memory leak) -> OOM-kill -> bot o'lib qoladi
      2) Event loop bloklanib qolishi -> bot "tirik" ko'rinadi, lekin
         aslida javob bermaydi (health check ham o'tadi!)
    Bu modul ikkalasini ham kuzatadi va log'ga yozadi.

Xotira chegarasi (MEMORY_LIMIT_MB > 0):
    Xotira belgilangan chegaradan oshsa, jarayon TOZA to'xtatiladi
    (`os._exit`). `start.sh` uni 5 sekundda qayta ishga tushiradi va baza
    Gist zaxirasidan tiklanadi. Bu OOM-kill'ning tasodifiy, nazoratsiz
    o'lishidan ancha yaxshi: restart nazorat ostida, log'da sabab ko'rinadi.

Nima qiladi:
    * RSS xotirani davriy o'qib, log'ga yozadi
    * Xotira chegarasini tekshiradi
    * Event loop kechikishini (lag) o'lchaydi — bloklanishni aniqlaydi
    * Davriy `gc.collect()` — uzoq ishlashda xotirani tartibga soladi
    * Holatni `/status` uchun ochiq beradi (`stats()`)
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import time
from typing import Any, Callable, Optional

log = logging.getLogger("watchdog")


def read_rss_mb() -> Optional[float]:
    """Joriy jarayonning RSS xotirasini MB da qaytaradi (Linux).

    Avval `/proc/self/status` (VmRSS — joriy xotira), u ishlamasa
    `resource` moduli (ru_maxrss — eng yuqori cho'qqi) ishlatiladi.
    """
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 2)
    except Exception:  # noqa: BLE001
        pass
    try:
        import resource  # noqa: PLC0415

        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024.0, 2)
    except Exception:  # noqa: BLE001
        return None


class Watchdog:
    """Xotira va event loop'ni kuzatuvchi fon vazifasi.

    Parametrlar:
        interval        — tekshirish oralig'i (sekund, min 30)
        memory_limit_mb — xotira chegarasi MB da (0 = o'chirilgan)
        gc_every        — har necha tekshiruvda `gc.collect()` (0 = hech qachon)
        on_limit        — chegara oshganda chaqiriladigan callback (ixtiyoriy);
                          berilmasa — `os._exit(1)` (start.sh qayta ishga tushiradi)
    """

    def __init__(
        self,
        interval: int = 300,
        memory_limit_mb: int = 0,
        gc_every: int = 6,
        on_limit: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.interval = max(30, int(interval))
        self.memory_limit_mb = max(0, int(memory_limit_mb))
        self.gc_every = max(0, int(gc_every))
        self.on_limit = on_limit

        self.checks: int = 0
        self.restarts: int = 0
        self.peak_mb: float = 0.0
        self.last_mb: Optional[float] = None
        self.last_lag: float = 0.0
        self.max_lag: float = 0.0
        self.started_at: float = time.time()

    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, Any]:
        """`/status` uchun qisqa holat."""
        return {
            "watchdog_checks": self.checks,
            "watchdog_restarts": self.restarts,
            "memory_mb": self.last_mb,
            "memory_peak_mb": round(self.peak_mb, 2) if self.peak_mb else None,
            "memory_limit_mb": self.memory_limit_mb or None,
            "loop_lag_ms": round(self.last_lag * 1000, 1),
            "loop_lag_max_ms": round(self.max_lag * 1000, 1),
        }

    # ------------------------------------------------------------------ #
    async def loop(self) -> None:
        """Asosiy kuzatuv sikli (asyncio task sifatida ishga tushiriladi)."""
        log.info(
            "Watchdog yoqildi: har %ds, xotira chegarasi=%s, gc har %s tekshiruv",
            self.interval,
            f"{self.memory_limit_mb} MB" if self.memory_limit_mb else "o'chirilgan",
            self.gc_every or "—",
        )
        # Bot to'liq ishga tushishini kutish
        await asyncio.sleep(20)

        while True:
            t0 = time.monotonic()
            await asyncio.sleep(self.interval)
            # Event loop kechikishi: sleep belgilangan vaqtdan qancha ko'p
            # cho'zilgan bo'lsa, loop shuncha bloklangan bo'ladi.
            lag = max(0.0, (time.monotonic() - t0) - self.interval)
            self.last_lag = lag
            self.max_lag = max(self.max_lag, lag)

            self.checks += 1
            mb = read_rss_mb()
            if mb is not None:
                self.last_mb = mb
                self.peak_mb = max(self.peak_mb, mb)

            if lag > 5.0:
                log.warning(
                    "Event loop %0.1fs bloklangan (kechikish) — og'ir so'rov "
                    "yoki sinxron I/O bo'lishi mumkin.",
                    lag,
                )

            if self.gc_every and self.checks % self.gc_every == 0:
                collected = gc.collect()
                log.debug("gc.collect(): %d obyekt yig'ildi", collected)

            log.info(
                "Watchdog #%d: xotira=%s MB, cho'qqi=%s MB, loop lag=%0.0f ms",
                self.checks,
                f"{mb:.1f}" if mb is not None else "?",
                f"{self.peak_mb:.1f}" if self.peak_mb else "?",
                lag * 1000,
            )

            if self.memory_limit_mb and mb is not None and mb > self.memory_limit_mb:
                self.restarts += 1
                log.critical(
                    "XOTIRA CHEGARASI OSHILDI: %.1f MB > %d MB. "
                    "Jarayon toza qayta ishga tushiriladi (start.sh uni tiklaydi).",
                    mb,
                    self.memory_limit_mb,
                )
                if self.on_limit is not None:
                    try:
                        self.on_limit(mb)
                    except Exception as exc:  # noqa: BLE001
                        log.error("on_limit callback xato: %s", exc)
                    return
                # Standart xatti-harakat: jarayonni to'xtatish.
                # `os._exit` — atexit/finally ishlamaydi, lekin bu yerda
                # aynan shu kerak: start.sh darhol qayta ishga tushiradi.
                os._exit(1)
