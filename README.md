# 🤖 AI Manager Bot — Gemini + 24/7 Render

Telegram bot: [@AIManagerProBot](https://t.me/AIManagerProBot)

Gemini AI asosida ishlaydigan, hamma soha bo'yicha javob beradigan, SQLite
ma'lumotlar bazasi, tezkor javob tizimi, test (quiz) funksiyasi va kanal
boshqaruviga ega bot. GitHub'da saqlanadi va Render'da 24/7 ishlaydi.

---

## 📑 Mundarija

1. [Funksiyalar](#-funksiyalar)
2. [Buyruqlar](#-buyruqlar)
3. [Fayllar tuzilmasi](#-fayllar-tuzilmasi)
4. [Lokal ishga tushirish](#-lokal-ishga-tushirish)
5. [Render'ga deploy](#-renderga-deploy)
6. [Ma'lumotlar bazasi (Render)](#-malumotlar-bazasi-render)
7. [24/7 uzluksizlik](#-247-uzluksizlik)
8. [Sozlamalar (.env)](#-sozlamalar-env)
9. [Muammolarni bartaraf etish](#-muammolarni-bartaraf-etish)
10. [Xavfsizlik](#-xavfsizlik)

---

## ✨ Funksiyalar

### ⚡ Tezkor javob tizimi (instant reply)
`salom`, `assalomu alaykum`, `rahmat`, `qalaysan`, `sen kimsan` kabi so'z va
iboralarga AI'ga murojaat qilmasdan, bazadan darhol javob beriladi
(o'lchangan: ~0.4 ms/javob). 50 ta tayyor javob, 8 kategoriya.

### 🗄 Ma'lumotlar bazasi (SQLite)

| Jadval | Saqlanadi |
| --- | --- |
| `users` | user_id, username, ism, til, ro'yxatdan o'tgan vaqt, oxirgi faollik, xabar soni |
| `chat_history` | har bir savol-javob, aniqlangan soha, manba (instant/ai) |
| `instant_replies` | kalit so'z → javob, kategoriya, ustuvorlik, ishlatilish soni |
| `quiz_questions` | savol, variantlar, to'g'ri javob, soha, izoh |
| `quiz_sessions` / `quiz_results` | joriy sessiya va natijalar tarixi |
| `question_bank` | qo'shilgan savollar (IELTS/matematika/fizika) |
| `test_codes` / `math_tests` / `physics_tests` | test kod tizimi |
| `channels` | ulangan kanallar (owner, channel_id, nom) |
| `scheduled_posts` | kanalga rejalashtirilgan postlar (matn, media, vaqt, takrorlash) |
| `user_states` / `admins` / `addq_requests` / `stats` / `reminders` | holat, adminlar, so'rovlar, statistika |

### 🎯 Testlar (quiz)
`/quiz` → soha tanlanadi → tasodifiy savollar → inline tugmalar → javob
tekshiriladi → izoh → natija. **55 savol, 10 soha:** matematika, tarix,
ingliz tili, dasturlash, tibbiyot, biznes, fan, geografiya, adabiyot,
umumiy bilim.

### 🌍 Hamma soha bo'yicha AI javob
Bot sohani avtomatik aniqlaydi (kalit so'z tahlili) va Gemini orqali mos
tarzda javob beradi. Suhbat tarixi kontekst sifatida ishlatiladi.

### 🔑 5 ta Gemini kalit — round-robin + failover
- **Round-robin:** har bir so'rov navbatdagi kalitdan boshlanadi
- **Failover:** kalit 429/5xx bersa → avtomatik keyingisiga o'tadi
- **Cooldown:** limitga yetgan kalit vaqtincha "sovutiladi" (429 → 60s, 401/403 → 30min)
- **Model fallback:** model 404/429 bersa → keyingi modelga o'tadi

### 🧰 Vositalar (Tools)
Asosiy menyu ostidagi «🧰 Vositalar» bo'limida 2 ta tugma:

1. **➕ Savol qo'shish** — admin to'g'ridan-to'g'ri qo'shadi; boshqa
   foydalanuvchi bosganda bot adminga ruxsat so'rovini yuboradi
   (inline: ✅ Tasdiqlash / ❌ Rad etish). Admin tasdiqlagach huquq beriladi.
   Savol turi: IELTS Speaking (Part 1/2/3), IELTS Writing (Task 1/2),
   Matematika, Fizika.
2. **📢 Kanalga ulash** — kanal ulash, ro'yxat, darhol post, postni
   rejalashtirish (`matn | +2h`, `matn | 09:30`, `matn | 2026-10-16 09:30`,
   takrorlash uchun `matn | +1d | 1440`). Fon vazifasi muddati kelgan
   postlarni avtomatik yuboradi.

### 🛡 24/7 barqarorlik
- `health_server.py` — `/health`, `/ready`, `/ping`, `/status`
- `watchdog.py` — xotira oqishi va loop bloklanishini kuzatadi, toza restart
- `backup.py` — SQLite bazani GitHub Gist'ga davriy zaxiralash/tiklash
- `start.sh` — avtomatik qayta ishga tushirish
- Self-ping + tashqi keep-alive (UptimeRobot)

---

## 📋 Buyruqlar

| Buyruq | Vazifasi |
| --- | --- |
| `/start` | Boshlash va tanishtirish |
| `/menu` | Asosiy menyu (inline tugmalar) |
| `/help` | Batafsil yordam |
| `/quiz` | Soha bo'yicha test o'tash |
| `/stats` | Statistika (foydalanuvchilar, xabarlar, sohalar) |
| `/history` | Oxirgi suhbatlar tarixi |
| `/clearhistory` | Suhbat tarixini tozalash |
| `/lang` | Til tanlash (uz / en / ru) |
| `/bank [so'z]` | Savollar banki |
| `/manga <nom>` | Manga haqida ma'lumot |
| `/recommend <janr>` | Janr bo'yicha tavsiya |
| `/image <tavsif>` | Rasm generatsiyasi |
| `/admin` | Admin bilan bog'lanish |

Erkin matn yozsangiz — har qanday sohada javob beradi.

---

## 📁 Fayllar tuzilmasi

```
ai-manager-bot/
├── bot.py                    # Asosiy bot (aiogram 3) — handlerlar
├── database.py               # SQLite qatlami (aiosqlite)
├── gemini_pool.py            # Ko'p kalitli round-robin + failover
├── config.py                 # .env / Render env dan sozlamalar
├── health_server.py          # ★ Render health-check + keep-alive
├── watchdog.py               # ★ Xotira/loop kuzatuvi (24/7)
├── backup.py                 # ★ GitHub Gist zaxirasi
├── start.sh                  # ★ Render start command (auto-restart)
├── render.yaml               # ★ Render Blueprint
├── Dockerfile                # Docker image (non-root + HEALTHCHECK)
├── .github/workflows/ci.yml  # ★ CI: sintaksis + JSON + YAML + xavfsizlik
├── .env.example              # Sozlamalar namunasi (maxfiy qiymatsiz!)
├── .gitignore                # .env, *.db, logs/ himoyasi
├── requirements.txt          # aiogram, aiohttp, aiosqlite, python-dotenv
├── instant_replies.json      # Tezkor javoblar (50 ta)
├── quiz_data.json            # Test savollari (55 ta, 10 soha)
├── ielts_speaking.json       # IELTS Speaking savollari (13 ta)
├── ielts_writing.json        # IELTS Writing topshiriqlari (6 ta)
├── math_tests.json           # Matematika testlari (kod tizimi)
├── physics_tests.json        # Fizika testlari (kod tizimi)
├── test_bot.py               # Integratsiya sinovi (bot/DB/AI)
├── test_deploy.py            # ★ Deploy sinovi (YAML/health/backup)
├── test_tools.py             # ★ Tools va kanal boshqaruvi sinovi
└── README.md                 # Shu fayl

★ = deploy uchun muhim fayllar
```

---

## 🚀 Lokal ishga tushirish

```bash
cd ai-manager-bot
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env ni tahrirlab: BOT_TOKEN va GEMINI_API_KEYS ni yozing
# Lokal rejim uchun: WEBHOOK_MODE=polling

python bot.py
```

Sinovlar:

```bash
python test_deploy.py                # deploy qismi (YAML, backup, Dockerfile)
python test_bot.py                   # bot qismi (DB, tezkor javob, AI, getMe)
python test_tools.py                 # Tools + kanal boshqaruvi
```

> Nega `.env.example` da haqiqiy kalitlar yo'q? Chunki bu fayl GitHub'ga
> tushadi. Haqiqiy qiymatlar faqat `.env` da (git'ga tushmaydi) yoki Render
> Environment'da saqlanadi.

---

## ☁️ Render'ga deploy

### Yo'l A — Blueprint (tavsiya)

`render.yaml` tayyor — Render uni o'qib servisni o'zi yaratadi.

1. [dashboard.render.com](https://dashboard.render.com/) → **New +** → **Blueprint**
2. GitHub hisobingizni ulang → `project` reponi tanlang → **Connect**
3. Render `render.yaml` ni o'qiydi. `sync: false` belgilangan qiymatlarni so'raydi:

| O'zgaruvchi | Qiymat |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot tokeni |
| `GEMINI_API_KEYS` | 5 ta kalit (vergul bilan) |
| `GITHUB_TOKEN` | GitHub token (`gist` scope bilan) — zaxira uchun |
| `GIST_ID` | _(bo'sh — birinchi zaxiralashdan keyin to'ldiriladi)_ |

4. **Apply** → Render image'ni build qilib servisni ishga tushiradi
5. ~2-3 daqiqadan keyin Logs'da:

```
[start.sh] ▶ Bot ishga tushirilmoqda (urinish #1)
health server listening on 0.0.0.0:10000
Bot tayyor: @AIManagerProBot
Webhook registered: https://project-1hw0.onrender.com/webhook/***
```

6. Tekshirish: `https://project-1hw0.onrender.com/health`
   → `{"status":"ok","ready":true,"bot":"@AIManagerProBot", ...}`

### Yo'l B — Qo'lda (Dashboard)

1. **New +** → **Web Service** → reponi tanlang
2. Sozlamalar:
   - **Name:** `project`
   - **Region:** Oregon (yoki eng yaqin)
   - **Runtime:** Docker
   - **Dockerfile Path:** `./Dockerfile`
   - **Instance Type:** Free
   - **Health Check Path:** `/health`
   - **Auto-Deploy:** Yes ✅
3. **Environment** bo'limida o'zgaruvchilarni qo'shing (pastdagi jadvalga qarang)
4. **Create Web Service**

---

## 💾 Ma'lumotlar bazasi (Render)

**Muammo:** Render bepul tarifida disk vaqtinchalik (ephemeral). Har deploy
yoki restartdan keyin `bot.db` o'chib ketadi.

**⭐ Yechim — GitHub Gist zaxirasi (bepul):**

1. Token yarating: [github.com/settings/tokens](https://github.com/settings/tokens)
   → Generate new token (classic) → scope: ✅ `gist`
2. Render Environment'ga qo'shing:
   ```
   BACKUP_ENABLED = true
   GITHUB_TOKEN   = ghp_...
   RESTORE_ON_START = true
   BACKUP_INTERVAL_SECONDS = 3600
   ```
3. Servis ishga tushgach Logs'da:
   ```
   YANGI GIST YARATILDI: 4f8a...b2c1 — bu id'ni env (GIST_ID) sifatida saqlang!
   ```
4. Shu `GIST_ID` ni Render Environment'ga qo'shing → keyingi deploy'larda
   o'sha gist yangilanadi.

**Qanday ishlaydi:** `VACUUM INTO` → `gzip` → `base64` → gist. Bot ishga
tushganda baza yo'q bo'lsa — gist'dan tiklanadi.

---

## ⏰ 24/7 uzluksizlik

Bepul Web Service 15 daqiqa harakatsizlikdan keyin "uxlaydi". Yechim — **uch
qatlamli himoya**:

| Qatlam | Nima qiladi | Yoqish |
| --- | --- | --- |
| 1. Tashqi keep-alive ⭐ | Har 5 daqiqada `/ping` — servis uyg'oq qoladi | UptimeRobot (bepul) |
| 2. Self-ping | Bot o'zini har 10 daqiqada ping qiladi | Avtomatik (`RENDER_EXTERNAL_URL`) |
| 3. Watchdog | Xotira oqishi/loop bloklanishini kuzatadi, toza restart | Avtomatik |

### UptimeRobot sozlash (qadam-baqadam)

1. [uptimerobot.com](https://uptimerobot.com/) → Sign Up (bepul)
2. **+ Add New Monitor**
3. To'ldiring:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `AI Manager Bot`
   - **URL:** `https://project-1hw0.onrender.com/ping`
   - **Monitoring Interval:** `5 minutes`
4. **Create Monitor** — tayyor!

> `/ping` eng yengil endpoint (`"ok"` qaytaradi) — trafikni behuda sarflamaydi.

---

## ⚙️ Sozlamalar (.env)

| O'zgaruvchi | Tavsif | Standart |
| --- | --- | --- |
| `BOT_TOKEN` / `TELEGRAM_BOT_TOKEN` | Telegram bot tokeni | — |
| `GEMINI_API_KEYS` | Kalitlar (vergul bilan) | — |
| `GEMINI_KEY_1..5` | Kalitlar (alohida) | — |
| `GEMINI_MODELS` | Model zaxira zanjiri | `gemini-3.5-flash-lite,...` |
| `GEMINI_IMAGE_MODELS` | Rasm modellari | `gemini-3.1-flash-image,...` |
| `WEBHOOK_BASE_URL` | Webhook manzili (Render avtomatik beradi) | — |
| `WEBHOOK_SECRET` | Webhook xavfsizlik kaliti | — |
| `PORT` | Health server porti (Render beradi) | `10000` |
| `SELF_PING_INTERVAL` | Self-ping oralig'i (sekund) | `600` |
| `WATCHDOG_ENABLED` | Watchdog yoqilishi | `true` |
| `WATCHDOG_MEMORY_LIMIT_MB` | Xotira chegarasi | `400` |
| `BACKUP_ENABLED` | Gist zaxirasi | `false` |
| `ADMIN_ID` / `ADMIN_USERNAME` | Admin telegram id / username | — |
| `ENABLE_INSTANT_REPLIES` | Tezkor javoblar | `true` |
| `QUIZ_QUESTIONS_PER_SESSION` | Testdagi savollar soni | `5` |
| `ENABLE_IMAGE_GEN` | Rasm generatsiyasi | `true` |
| `LOG_LEVEL` | Log darajasi | `INFO` |

---

## 🔧 Muammolarni bartaraf etish

### Gemini
| Muammo | Yechim |
| --- | --- |
| `HTTP 429 — quota exceeded` | Bepul kvota tugagan. [Google AI Studio](https://aistudio.google.com/apikey) da billing yoqing yoki yangi kalit qo'shing. Bot kalitlarni avtomatik almashtiradi. |
| `HTTP 404 — model no longer available` | Model Google tomonidan yopilgan. `GEMINI_MODELS` ni yangilang (bot o'zi keyingi modelga o'tadi). |
| `AllKeysFailedError` | Barcha kalitlar kvotasi tugagan. Yangi kalit qo'shing. |
| Rasm yaratilmayapti | Imagen hisobingizda yoqilmagan bo'lishi mumkin. |

> **Diqqat:** model nomlari tez-tez o'zgaradi. Ishlayotganini tekshirish:
> `curl "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY"`

### Render
| Muammo | Yechim |
| --- | --- |
| `No such file: start.sh` | `git update-index --chmod=+x start.sh` |
| `BOT_TOKEN bo'sh` | Render Environment'da o'zgaruvchilarni qo'shing (`.env` git'da yo'q!) |
| Servis "Healthy" bo'lmayapti | Health Check Path = `/health` ekanini tekshiring |
| Bot uxlab qoladi | UptimeRobot bilan `.../ping` ga 5 daqiqalik ping qo'ying |
| 409 Conflict | Ikki instance ishlayapti — eski deploy'ni Suspend qiling |
| Baza har deploy'da o'chadi | `BACKUP_ENABLED=true` + `GITHUB_TOKEN` |
| Xotira oshib bot o'ldi (OOM) | `WATCHDOG_MEMORY_LIMIT_MB=400` — toza restart bo'ladi |

### Loglarni kuzatish (Render)
Dashboard → servisingiz → **Logs**. Foydali qidiruvlar: `ERROR`,
`[start.sh]` (restartlar), `zaxiralandi` (backup), `409 Conflict`.

`/status` endpoint jonli holatni ko'rsatadi:

```json
{"status":"ok","ready":true,"bot":"@AIManagerProBot","uptime_human":"2h 15m 3s",
 "keys":5,"models":5,"backup_enabled":true,"requests_total":42}
```

---

## 🔄 CI/CD

`.github/workflows/ci.yml` har push'da ishlaydi:

1. ✅ `py_compile` — barcha `.py` fayllar sintaksisi
2. ✅ Import testi — modullar yuklanadimi
3. ✅ JSON validatsiyasi — `*.json` bazalar
4. ✅ YAML validatsiyasi — `render.yaml`, `ci.yml`
5. ✅ Xavfsizlik — `.env` yoki `*.db` commit qilinmaganini tekshirish

Render'da `autoDeploy: true` — GitHub'ga push qilganingizda Render o'zi
qayta deploy qiladi.

---

## 🔒 Xavfsizlik

- `.env` faylini hech qachon git'ga qo'shmang (`.gitignore` da bor)
- Render'da maxfiy qiymatlarni faqat **Environment** orqali bering
- `render.yaml` da maxfiy qiymatlar `sync: false` — GitHub'da saqlanmaydi
- Token va API kalitlar ochiq yuborilgan bo'lsa — almashtiring
- `bot.db` va Gist zaxirasida foydalanuvchi ma'lumotlari bor — xavfsiz saqlang
- `GITHUB_TOKEN` ga faqat `gist` scope bering

---

## ⚠️ Model nomi haqida eslatma

Model nomlari Google tomonidan tez-tez o'zgartiriladi. Kod model zaxira
zanjiri bilan qurilgan, shuning uchun birinchi model ishlamasa avtomatik
keyingisiga o'tadi:

```
gemini-3.5-flash-lite → gemini-3.1-flash-lite → gemini-flash-lite-latest
  → gemini-3.8-flash → gemini-flash-latest
```

Birinchi model kvota/xato bersa, avtomatik keyingisiga o'tadi va bu
log'da ko'rinadi.

---

## 📄 Litsenziya

Shaxsiy foydalanish uchun. Muallif: **Husan Dilmurodov**
