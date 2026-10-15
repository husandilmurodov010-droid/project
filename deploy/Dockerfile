# ===========================================================================
#  AI Manager Bot — Docker image
#  Ishlatish: docker build -f deploy/Dockerfile -t ai-manager-bot .
#  Yoki:      docker compose -f deploy/docker-compose.yml up -d --build
# ===========================================================================
FROM python:3.11-slim

# Python: buferlash va .pyc yozishni o'chirish (loglar darhol ko'rinadi)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Avval faqat kutubxonalar — Docker qatlam keshi uchun (kod o'zgarsa ham
#    pip qayta o'rnatilmaydi, build tez bo'ladi).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) Keyin kod
COPY . .

# 3) Ishchi papkalar (Render'da disk vaqtinchalik bo'lsa ham kerak)
RUN mkdir -p logs data

# 4) Root bo'lmagan foydalanuvchi (xavfsizlik)
RUN useradd --create-home --shell /bin/bash botuser \
    && chown -R botuser:botuser /app
USER botuser

# 5) Health check — Docker ham bot tirikligini tekshira oladi.
#    PORT berilgan bo'lsa /health javob beradi; aks holda tekshiruv
#    o'tkazib yuboriladi (background worker holati).
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','0'); \
sys.exit(0) if p in ('','0') else urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=5).read() and sys.exit(0)"

# 6) start.sh — ichida avtomatik qayta ishga tushirish sikli bor
CMD ["bash", "start.sh"]
