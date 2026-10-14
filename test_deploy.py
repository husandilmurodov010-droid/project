"""Deploy-side checks: YAML, gitignore coverage, health endpoints, backup roundtrip."""
import base64
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import time

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}{(' — ' + detail) if detail else ''}")


def main():
    # 1. YAML
    try:
        import yaml
        cfg = yaml.safe_load(open("render.yaml"))
        svc = cfg["services"][0]
        check("render.yaml parse", True)
        check("render.yaml healthCheckPath=/health", svc.get("healthCheckPath") == "/health")
        keys = {e["key"] for e in svc["envVars"]}
        for k in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEYS", "GEMINI_MODELS", "WEBHOOK_BASE_URL"):
            check(f"render.yaml has {k}", k in keys)
    except Exception as e:
        check("render.yaml parse", False, str(e))

    # 2. .gitignore
    gi = open(".gitignore").read()
    for pat in (".env", "*.db", "logs/", "__pycache__/"):
        check(f".gitignore covers {pat}", pat in gi)

    # 3. .env.example has no real secret
    ex = open(".env.example").read()
    check(".env.example has no real token", "8858092416:" not in ex)
    check(".env.example has no real key", "AQ.Ab8RN6" not in ex)

    # 4. JSON data files
    for f in ("instant_replies.json", "quiz_data.json", "ielts_speaking.json",
              "ielts_writing.json", "math_tests.json", "physics_tests.json"):
        try:
            data = json.load(open(f, encoding="utf-8"))
            check(f"{f} valid ({len(data)} items)", len(data) > 0)
        except Exception as e:
            check(f"{f} valid", False, str(e))

    # 5. backup roundtrip (VACUUM INTO -> gzip -> base64 -> restore)
    try:
        tmp = tempfile.mktemp(suffix=".db")
        con = sqlite3.connect(tmp)
        con.execute("CREATE TABLE t(a INTEGER)")
        con.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(100)])
        con.commit()
        con.close()

        snap = tempfile.mktemp(suffix=".db")
        src = sqlite3.connect(tmp)
        src.execute("VACUUM INTO ?", (snap,))
        src.close()
        blob = base64.b64encode(gzip.compress(open(snap, "rb").read(), 9)).decode()

        back = tempfile.mktemp(suffix=".db")
        open(back, "wb").write(gzip.decompress(base64.b64decode(blob)))
        con = sqlite3.connect(back)
        n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        con.close()
        check("backup roundtrip preserves rows", n == 100, f"rows={n}")
        check("backup is base64 text", blob.isascii() and len(blob) > 0)
        for p in (tmp, snap, back):
            os.path.exists(p) and os.unlink(p)
    except Exception as e:
        check("backup roundtrip", False, str(e))

    # 6. Dockerfile sanity
    df = open("Dockerfile").read()
    check("Dockerfile starts via start.sh", "start.sh" in df)
    check("Dockerfile has HEALTHCHECK", "HEALTHCHECK" in df)
    check("Dockerfile runs as non-root", "USER botuser" in df)

    # 7. start.sh syntax
    rc = os.system("bash -n start.sh")
    check("start.sh syntax", rc == 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
