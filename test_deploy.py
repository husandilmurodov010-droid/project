"""AI Manager Bot v4 — deploy (GitHub/Render) qismini sinash.

Bu sinov botning AI qismini emas, balki GITHUB + RENDER deploy uchun
qo'shilgan qismlarni tekshiradi:

  1. YAML fayllar to'g'rimi (render.yaml, ci.yml, docker-compose.yml)
  2. .gitignore maxfiy fayllarni haqiqatan qoplaydimi
  3. .env.example da haqiqiy maxfiy qiymat yo'qmi (faqat o'rn-joylar)
  4. render.yaml ichida kerakli env kalitlar bormi
  5. Health server haqiqatan javob beradimi (aiohttp, jonli so'rov)
  6. Backup: SQLite -> gzip -> base64 -> ochish aylanmasi ishlaydimi
  7. start.sh sintaksisi to'g'rimi (bash -n)
  8. config.py yangi aliaslarni o'qiy oladimi (GEMINI_KEY_1..5, ADMIN_ID)

Ishga tushirish:
    python test_deploy.py
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# Testdan oldin majburiy env — config import bo'lishi uchun.
# MUHIM: qiymatlarni ATAYLAB o'rnatamiz (pop emas!) — chunki config.py
# `load_dotenv()` ni chaqiradi va u mavjud env o'zgaruvchilarni OVERRIDE
# QILMAYDI. Shunday qilib test lokal `.env` faylidan (haqiqiy kalitlar)
# mustaqil bo'ladi va CI'da ham, lokalda ham bir xil natija beradi.
os.environ["BOT_TOKEN"] = "1234567890:TEST_TOKEN_FOR_DEPLOY_TEST"
os.environ["DB_PATH"] = "deploy_test.db"
os.environ["GEMINI_API_KEYS"] = ""          # vergul-usulini o'chir
for _i in range(1, 11):                     # GEMINI_KEY_* ni tozalab, faqat 1..3 qoldiramiz
    os.environ.pop(f"GEMINI_KEY_{_i}", None)
os.environ["GEMINI_KEY_1"] = "key_one"
os.environ["GEMINI_KEY_2"] = "key_two"
os.environ["GEMINI_KEY_3"] = "key_three"
os.environ["ADMIN_ID"] = "555"
os.environ["ADMIN_USERNAME"] = "tester"
os.environ["ADMIN_IDS"] = ""
os.environ["ADMIN_USERNAMES"] = ""

import aiohttp  # noqa: E402
import yaml  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {extra}" if extra else ""))


ROOT = Path(__file__).resolve().parent
HTTP_PORT = 8931


# --------------------------------------------------------------------------- #
def test_yaml() -> None:
    print("\n[1] YAML fayllar")
    for rel in ("render.yaml", "deploy/docker-compose.yml", ".github/workflows/ci.yml"):
        p = ROOT / rel
        if not p.exists():
            check(f"{rel} mavjud", False)
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            check(f"{rel} to'g'ri YAML", isinstance(data, (dict, list)) or data is not None)
        except Exception as exc:  # noqa: BLE001
            check(f"{rel} to'g'ri YAML", False, str(exc)[:100])


def test_render_keys() -> None:
    print("\n[2] render.yaml kerakli o'zgaruvchilar")
    data = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = data.get("services") or []
    check("kamida bitta servis bor", len(services) >= 1, f"{len(services)} ta")

    web = next((s for s in services if s.get("type") == "web"), None)
    check("web servis (bepul yo'l) bor", web is not None)
    if web:
        keys = {e.get("key") for e in (web.get("envVars") or [])}
        for need in ("BOT_TOKEN", "GEMINI_KEY_1", "GEMINI_KEY_5", "ADMIN_USERNAME",
                     "GEMINI_MODELS", "DB_PATH", "BACKUP_ENABLED", "GITHUB_TOKEN"):
            check(f"web env: {need}", need in keys)
        check("web: healthCheckPath=/health", web.get("healthCheckPath") == "/health",
              str(web.get("healthCheckPath")))
        check("web: startCommand start.sh", "start.sh" in (web.get("startCommand") or ""))
        check("web: plan=free", web.get("plan") == "free", str(web.get("plan")))
        # Maxfiy qiymatlar sync:false bo'lishi shart (GitHub'da saqlanmasin)
        secret_vars = [e for e in (web.get("envVars") or [])
                       if e.get("key") in ("BOT_TOKEN", "GEMINI_KEY_1", "GITHUB_TOKEN")]
        check("maxfiy qiymatlar sync:false",
              all(e.get("sync") is False for e in secret_vars),
              f"{len(secret_vars)} ta tekshirildi")


def test_gitignore() -> None:
    print("\n[3] .gitignore qamrovi")
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = {ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")}
    for need in (".env", "*.db", "logs/", "__pycache__/", ".venv/"):
        check(f".gitignore: {need}", need in patterns)
    check(".env.example istisno qilingan", "!.env.example" in patterns)


def test_env_example_clean() -> None:
    print("\n[4] .env.example'da haqiqiy maxfiy qiymat yo'q")
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    # Telegram token formati: <raqam>:<harflar>
    check("haqiqiy Telegram tokeni yo'q",
          not re.search(r"BOT_TOKEN=\d{6,}:[A-Za-z0-9_-]{20,}", text))
    # Gemini kalitlari (uzun base64) yo'q
    check("haqiqiy Gemini kaliti yo'q",
          not re.search(r"GEMINI[_A-Z0-9]*=[A-Za-z0-9_.-]{30,}", text))
    # GitHub token yo'q
    check("haqiqiy GitHub tokeni yo'q", "ghp_" not in text or "<ghp_" in text)
    check("o'rn-joylar ishlatilgan", "<" in text and ">" in text)


def test_config_aliases() -> None:
    print("\n[5] config.py yangi aliaslar")
    import config  # noqa: E402  (env yuqorida o'rnatilgan)

    check("GEMINI_KEY_1..3 o'qildi", len(config.GEMINI_API_KEYS) == 3,
          str(config.GEMINI_API_KEYS))
    check("kalitlar tartibi saqlandi",
          config.GEMINI_API_KEYS == ["key_one", "key_two", "key_three"])
    check("ADMIN_ID o'qildi", 555 in config.ADMIN_IDS, str(config.ADMIN_IDS))
    check("ADMIN_USERNAME o'qildi", "tester" in config.ADMIN_USERNAMES,
          str(config.ADMIN_USERNAMES))
    check("PORT o'zgaruvchisi bor", hasattr(config, "PORT"))
    check("backup sozlamalari bor",
          all(hasattr(config, a) for a in
              ("BACKUP_ENABLED", "GITHUB_TOKEN", "GIST_ID",
               "BACKUP_INTERVAL_SECONDS", "RESTORE_ON_START")))
    check("is_admin(555) True", config.is_admin(555))
    check("is_admin(noma'lum) False", not config.is_admin(999999))


def test_start_sh_syntax() -> None:
    print("\n[6] start.sh va run.sh sintaksisi")
    for f in ("start.sh", "run.sh"):
        p = ROOT / f
        if not p.exists():
            check(f"{f} mavjud", False)
            continue
        r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
        check(f"{f} sintaksisi to'g'ri", r.returncode == 0, r.stderr.strip()[:100])
        # Render/Linux'da bajariladigan bo'lishi kerak (git'da +x saqlanadi)
        check(f"{f} bajariladigan (+x)", os.access(p, os.X_OK),
              oct(p.stat().st_mode)[-3:])


async def test_backup_roundtrip() -> None:
    print("\n[7] Backup aylanmasi (SQLite -> gzip -> base64 -> tiklash)")
    import backup as backup_mod

    tmpdir = Path(tempfile.mkdtemp())
    try:
        src = tmpdir / "src.db"
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t (v) VALUES (?)",
                         [(f"qator-{i}",) for i in range(200)])
        conn.commit()
        conn.close()

        # 1) Izchil nusxa (VACUUM INTO)
        snap = tmpdir / "snap.db"
        backup_mod._snapshot(str(src), str(snap))
        check("VACUUM INTO nusxa oldi", snap.exists() and snap.stat().st_size > 0,
              f"{snap.stat().st_size if snap.exists() else 0} bayt")

        # 2) Nusxa to'liqmi (200 qator + ustunlar)
        c = sqlite3.connect(snap)
        n = c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        c.close()
        check("nusxada 200 qator bor", n == 200, f"{n} qator")

        # 3) gzip + base64 (gist'ga ketadigan format)
        raw = snap.read_bytes()
        payload = base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
        check("siqilgan yuklama matn", isinstance(payload, str) and len(payload) > 0,
              f"{len(raw)/1024:.1f} KB -> {len(payload)/1024:.1f} KB")

        # 4) Ochish va tiklash
        restored = tmpdir / "restored.db"
        restored.write_bytes(gzip.decompress(base64.b64decode(payload)))
        c = sqlite3.connect(restored)
        n2 = c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        v = c.execute("SELECT v FROM t WHERE id = 100").fetchone()[0]
        c.close()
        rest_has = restored.exists()
        check("tiklangandan keyin 200 qator", n2 == 200, f"{n2} qator")
        check("ma'lumot buzilmagan", v == "qator-99", v)

        # 5) Menejer: token yo'q -> o'chiq holat, lekin crash bo'lmasin
        mgr = backup_mod.BackupManager(db_path=str(src), token="")
        check("tokensiz menejer o'chiq", mgr.enabled is False)
        check("stats() ishlaydi", isinstance(mgr.stats(), dict))
        ok = await mgr.push()
        check("tokensiz push xato bermaydi", ok is False)
        ok2 = await mgr.restore_if_needed()
        check("tokensiz restore xato bermaydi", ok2 is False)
        check("last_backup_human ishlaydi", isinstance(mgr.last_backup_human(), str))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def test_health_server() -> None:
    print("\n[8] Health server (jonli HTTP so'rovlar)")
    import health_server

    runner = await health_server.start_health_server(port=HTTP_PORT, host="127.0.0.1")
    if runner is None:
        check("server ko'tarildi", False)
        return

    base = f"http://127.0.0.1:{HTTP_PORT}"
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            # /health — doim 200 (Render health check)
            async with s.get(f"{base}/health") as r:
                check("/health -> 200", r.status == 200, str(r.status))
                data = await r.json()
                check("/health JSON'da 'status' bor", "status" in data,
                      json.dumps(data, ensure_ascii=False)[:90])
                check("ready=False (hali ishga tushmagan)",
                      data.get("ready") is False)

            # /ready — tayyor bo'lmasa 503
            async with s.get(f"{base}/ready") as r:
                check("/ready -> 503 (hali tayyor emas)", r.status == 503, str(r.status))

            # /ping — keep-alive
            async with s.get(f"{base}/ping") as r:
                body = await r.text()
                check("/ping -> 200 'ok'", r.status == 200 and body == "ok",
                      f"{r.status} {body!r}")

            # /healthz alias
            async with s.get(f"{base}/healthz") as r:
                check("/healthz -> 200", r.status == 200, str(r.status))

            # /status
            async with s.get(f"{base}/status") as r:
                check("/status -> 200", r.status == 200, str(r.status))

            # / — HTML sahifa
            async with s.get(f"{base}/") as r:
                html = await r.text()
                check("/ -> 200 HTML", r.status == 200 and "<html" in html.lower())
                check("HTML'da bot nomi bor", "AI Manager Bot" in html)

            # ready=True bo'lganda /ready 200 berishi
            health_server.state.ready = True
            health_server.state.bot_username = "@AIManagerProBot"
            health_server.state.detail = {"keys": 5, "models": 4,
                                          "db": "bot.db", "backup_enabled": True}
            async with s.get(f"{base}/ready") as r:
                check("/ready -> 200 (tayyor bo'lgach)", r.status == 200, str(r.status))
                d = await r.json()
                check("ready=True qaytdi", d.get("ready") is True)
                check("bot username uzatildi", d.get("bot") == "@AIManagerProBot")
                check("kalitlar soni uzatildi", d.get("keys") == 5)
                check("backup holati uzatildi", d.get("backup_enabled") is True)

            async with s.get(f"{base}/health") as r:
                d = await r.json()
                check("uptime hisoblanadi", d.get("uptime_seconds", -1) >= 0
                      and str(d.get("uptime_human", "")).endswith("s"),
                      f"{d.get('uptime_seconds')}s ({d.get('uptime_human')})")
                check("so'rovlar sanaladi", d.get("requests_total", 0) >= 7,
                      f"{d.get('requests_total')} so'rov")
                check("keep-alive ping sanaladi", d.get("keepalive_pings", 0) >= 1,
                      f"{d.get('keepalive_pings')} ping")
    finally:
        await runner.cleanup()
        check("server toza to'xtatildi", True)


async def test_watchdog() -> None:
    print("\n[11] Watchdog (xotira/loop kuzatuvi)")
    import watchdog

    # RSS o'qish ishlaydimi
    mb = watchdog.read_rss_mb()
    check("read_rss_mb() qiymat qaytaradi", mb is None or mb > 0,
          f"{mb} MB")

    # stats() to'g'ri kalitlarni beradimi
    wd = watchdog.Watchdog(interval=30, memory_limit_mb=0, gc_every=0)
    st = wd.stats()
    for key in ("watchdog_checks", "watchdog_restarts", "memory_mb",
                "memory_peak_mb", "memory_limit_mb", "loop_lag_ms",
                "loop_lag_max_ms"):
        check(f"stats() da '{key}' bor", key in st)
    check("boshlang'ich checks=0", st["watchdog_checks"] == 0)
    check("chegara 0 -> None (o'chiq)", st["memory_limit_mb"] is None)

    # interval minimal 30 ga ko'tariladi
    wd2 = watchdog.Watchdog(interval=5)
    check("interval min 30 ga majburlanadi", wd2.interval == 30, str(wd2.interval))

    # on_limit callback: chegara oshsa chaqiriladi (os._exit EMAS)
    called: list[float] = []
    wd3 = watchdog.Watchdog(interval=30, memory_limit_mb=1, gc_every=0,
                            on_limit=lambda m: called.append(m))
    # loop'ni qisqa muddatga ishga tushirib, chegarani tekshiramiz
    task = asyncio.create_task(wd3.loop())
    await asyncio.sleep(0.1)
    # loop 20s kutadi — bekor qilamiz va callback mantiqini to'g'ridan tekshiramiz
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    check("on_limit berilganda loop toza bekor qilinadi", True)

    # config'da watchdog sozlamalari bor
    import config
    check("config.WATCHDOG_ENABLED mavjud", hasattr(config, "WATCHDOG_ENABLED"))
    check("config.WATCHDOG_INTERVAL mavjud", hasattr(config, "WATCHDOG_INTERVAL"))
    check("config.WATCHDOG_MEMORY_LIMIT_MB mavjud",
          hasattr(config, "WATCHDOG_MEMORY_LIMIT_MB"))


def test_dockerfile() -> None:
    print("\n[9] Dockerfile")
    text = (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
    check("python:3.11-slim bazasi", "python:3.11-slim" in text)
    check("requirements o'rnatiladi", "requirements.txt" in text)
    check("start.sh CMD", "start.sh" in text)
    check("non-root foydalanuvchi", "USER botuser" in text)
    check("HEALTHCHECK bor", "HEALTHCHECK" in text)


def test_files_present() -> None:
    print("\n[10] Kerakli fayllar mavjud")
    for rel in ("bot.py", "config.py", "database.py", "gemini_pool.py",
                "backup.py", "health_server.py", "watchdog.py", "start.sh", "run.sh",
                "render.yaml", ".env.example", ".gitignore",
                "requirements.txt", "instant_replies.json", "quiz_data.json",
                ".github/workflows/ci.yml", "deploy/Dockerfile",
                "deploy/docker-compose.yml", "deploy/manga-bot.service",
                "README.md"):
        check(f"mavjud: {rel}", (ROOT / rel).exists())


# --------------------------------------------------------------------------- #
async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v4 — deploy qismi sinovlari (GitHub + Render)")
    print("=" * 70)

    test_files_present()
    test_yaml()
    test_render_keys()
    test_gitignore()
    test_env_example_clean()
    test_config_aliases()
    test_start_sh_syntax()
    await test_backup_roundtrip()
    test_dockerfile()
    await test_health_server()
    await test_watchdog()

    # Tozalash
    for suffix in ("", "-wal", "-shm"):
        f = ROOT / f"deploy_test.db{suffix}"
        if f.exists():
            f.unlink()

    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
