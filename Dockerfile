# ===========================================================================
#  AI Manager Bot (@AIManagerProBot) — Render / Docker image
#  Render bu faylni `dockerfilePath: ./Dockerfile` orqali ishlatadi.
#  Lokal: docker build -t ai-manager-bot . && docker run --env-file .env -p 10000:10000 ai-manager-bot
# ===========================================================================
FROM python:3.11-slim

# Loglar darhol ko'rinadi, .pyc yozilmaydi, pip keshi o'chirilgan.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl — HEALTHCHECK uchun kerak.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 1) Avval kutubxonalar (Docker qatlam keshi uchun).
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) Keyin kod.
COPY . .

# 3) Ishchi papkalar + start.sh ruxsati + root bo'lmagan foydalanuvchi.
RUN mkdir -p logs data \
    && chmod +x start.sh run.sh \
    && useradd --create-home --shell /bin/bash botuser \
    && chown -R botuser:botuser /app
USER botuser

# Render Web Service PORT'ni o'zi beradi (odatda 10000).
EXPOSE 10000

# Health check — Render "healthy" deb belgilashi uchun /health javob berishi kerak.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-10000}/health" || exit 1

# start.sh — ichida avtomatik qayta ishga tushirish sikli bor (24/7).
CMD ["bash", "start.sh"]
