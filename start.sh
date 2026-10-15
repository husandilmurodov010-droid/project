#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Render uchun ishga tushirish skripti (start command).
#
# Nima qiladi:
#   1) Render'da paketlar global o'rnatiladi — venv shart emas.
#   2) Bot yiqilsa (xato, tarmoq uzilishi, 409 conflict) — avtomatik qayta
#      ishga tushiradi. Shu bilan "24/7 uzluksiz" ta'minlanadi: oraliq
#      uzilishlar tashqi restart'ga muhtoj bo'lmaydi.
#   3) `python -u` — buferlash o'chirilgan, loglar Render'da darhol ko'rinadi.
#
# Muhim: bu skript ATAYLAB hech qachon chiqmaydi. Render servisni faqat
# jarayon o'lganda qayta ishga tushiradi; uzluksiz loop ichkarida ishlagani
# uchun qayta ishga tushish tez va DB fayli saqlanib qoladi (toza restart
# esa yangi bo'sh konteyner beradi).
# ---------------------------------------------------------------------------
set -u

cd "$(dirname "$0")"

# Agar .venv bo'lsa (lokal ishlatishda) — faollashtiramiz.
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

RESTART_DELAY="${RESTART_DELAY:-5}"

echo "[start.sh] ============================================"
echo "[start.sh] AI Manager Bot ishga tushirilmoqda"
echo "[start.sh] Sana      : $(date -Is)"
echo "[start.sh] Python    : $(python --version 2>&1)"
echo "[start.sh] PORT      : ${PORT:-<berilmagan>}"
echo "[start.sh] HEALTH    : ${ENABLE_HEALTH_SERVER:-true}"
echo "[start.sh] BACKUP    : ${BACKUP_ENABLED:-false}"
echo "[start.sh] ============================================"

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "[start.sh] ▶ Bot ishga tushirilmoqda (urinish #${attempt}) — $(date -Is)"

  python -u bot.py
  code=$?

  # 0 = toza to'xtash, 130/143 = SIGINT/SIGTERM (Render to'xtatgan) — qayta
  # ishga tushirmaymiz, servis to'xtatilgan bo'lishi mumkin.
  if [ "$code" -eq 0 ] || [ "$code" -eq 130 ] || [ "$code" -eq 143 ]; then
    echo "[start.sh] ⏹ Bot toza to'xtadi (kod=${code}). Chiqamiz."
    exit "$code"
  fi

  echo "[start.sh] ⚠ Bot xato bilan to'xtadi (kod=${code}). ${RESTART_DELAY}s dan so'ng qayta urinamiz..."
  sleep "$RESTART_DELAY"
done
