#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Auto-restart wrapper (VPS / lokal uchun).
# Render'da `start.sh` ishlatiladi — bu skript unga topshiradi, shunda
# bitta mantiq bo'ladi (ikki joyda saqlash shart emas).
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"
exec bash start.sh
