#!/usr/bin/env bash
# Render start command: keeps the bot alive, restarting it cleanly if it dies.
set -u

cd "$(dirname "$0")"

ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "[start.sh] ▶ Bot ishga tushirilmoqda (urinish #$ATTEMPT) $(date -u +%H:%M:%S)"
  python -u bot.py
  CODE=$?
  echo "[start.sh] ⚠️ Bot $CODE kodi bilan to'xtadi - 5 sekunddan keyin qayta ishga tushadi"
  sleep 5
done
