# 🤖 AI Manager Bot — GitHub + Render bilan 24/7

Telegram bot: **[@AIManagerProBot](https://t.me/AIManagerProBot)**

Gemini AI asosida ishlaydigan, **hamma soha** bo'yicha javob beradigan, SQLite
ma'lumotlar bazasi, tezkor javob tizimi va test (quiz) funksiyasiga ega bot.
Bu versiya (v4) **GitHub'da saqlanadigan** va **Render'da 24/7 uzluksiz
ishlaydigan** qilib sozlangan.

---

## 📑 Mundarija

1. [Funksiyalar](#-funksiyalar)
2. [Buyruqlar](#-buyruqlar)
3. [Fayllar tuzilmasi](#-fayllar-tuzilmasi)
4. [Lokal ishga tushirish](#-lokal-ishga-tushirish)
5. [GitHub'ga joylash](#-githubga-joylash) ← **yangi**
6. [Render'ga deploy](#-renderga-deploy) ← **yangi**
7. [Ma'lumotlar bazasi muammosi (Render)](#-malumotlar-bazasi-muammosi) ← **muhim**
8. [24/7 uzluksizlik](#-247-uzluksizlik)
9. [Boshqa deployment variantlari](#-boshqa-deployment-variantlari)
10. [Sozlamalar](#-sozlamalar-env)
11. [Muammolarni bartaraf etish](#-muammolarni-bartaraf-etish)
12. [Xavfsizlik](#-xavfsizlik)

---

## ✨ Funksiyalar

### ⚡ Tezkor javob tizimi (instant reply)
`salom`, `assalomu alaykum`, `rahmat`, `qalaysan`, `sen kimsan` kabi so'z va
iboralarga **AI'ga murojaat qilmasdan**, bazadan darhol javob beriladi
(o'lchangan tezlik: **~0.4 ms/javob** — 0.1 sekunddan ancha tez).

### 🗄 Ma'lumotlar bazasi (SQLite)
| Jadval | Saqlanadi |
|---|---|
| `users` | user_id, username, ism, til, ro'yxatdan o'tgan vaqt, oxirgi faollik, xabar soni |
| `chat_history` | har bir savol-javob, aniqlangan soha, manba (instant/ai/quiz) |
| `instant_replies` | kalit so'z → javob, kategoriya, ustuvorlik, ishlatilish soni |
| `quiz_questions` | savol, variantlar, to'g'ri javob, soha, izoh |
| `quiz_sessions` | foydalanuvchining joriy test sessiyasi |
| `quiz_results` | test natijalari tarixi |
| `stats` | so'rovlar, sohalar bo'yicha hisob |
| `ielts_*`, `math_tests`, `physics_tests`, `test_codes`, `reminders`, `question_bank`, `user_states`, `admins` | v3'da qo'shilgan qo'shimcha jadvallar |
| `channels` | ulangan kanallar (owner_id, channel_id, nomi, username, ulangan vaqt) |
| `scheduled_posts` | kanalga rejalashtirilgan postlar (matn, media, vaqt, takrorlash) |

### 🎯 Testlar (quiz)
`/quiz` → soha tanlanadi → tasodifiy savollar → inline tugmalar → javob
tekshiriladi → **natija va xatolar tahlili**. **60 ta savol, 10 soha**:
matematika, tarix, ingliz tili, dasturlash, tibbiyot, biznes, fan, geografiya,
adabiyot, umumiy bilim.

### 🌍 Hamma soha bo'yicha AI javob
Bot sohani **avtomatik aniqlaydi** (kalit so'z + arifmetik ifoda tahlili) va
Gemini orqali mos tarzda javob beradi.

### 🔑 5 ta Gemini kalit — round-robin + failover
- **Round-robin:** har bir so'rov navbatdagi kalitdan boshlanadi
- **Failover:** kalit 429/5xx bersa → avtomatik keyingisiga o'tadi
- **Cooldown:** limitga yetgan kalit vaqtincha "sovutiladi"
- **Model fallback:** model 404/429 bersa → keyingi modelga o'tadi

### 🧰 Vositalar (Tools) — v5'da qayta qurildi
Asosiy menyu ostidagi **«🧰 Vositalar»** bo'limida endi faqat **2 ta tugma**:

1. **➕ Savol qo'shish** — savol/test qo'shish.
2. **📢 Kanalga ulash** — kanalni botga ulash va boshqarish.

#### ➕ Savol qo'shish
- **Admin** (@Husan_Dilmurodov) bosganda — to'g'ridan-to'g'ri savol qo'shadi.
- **Boshqa foydalanuvchi** bosganda — bot **adminga ruxsat so'rovini** yuboradi
  (inline tugmalar: ✅ Tasdiqlash / ❌ Rad etish). So'rovda foydalanuvchining
  ismi/username'i va ID'si ko'rsatiladi. Admin tasdiqlagach foydalanuvchi savol
  qo'shish huquqini oladi.
- Savol turi tanlanadi: **IELTS Speaking** (Part 1/2/3), **IELTS Writing**
  (Task 1/2), **Matematika**, **Fizika** (test kod tizimi bilan).

#### 📢 Kanal boshqaruvi (admin)
- **➕ Kanal ulash** — kanalning `@username` yoki ID sini yuborib ulash. Bot
  kanalda **admin** ekanligi avtomatik tekshiriladi.
- **📋 Kanallarim** — ulangan kanallar ro'yxati (o'chirish mumkin).
- **✍️ Kanalga post** — matn yoki rasmni tanlangan kanalga darhol joylash.
- **🗓 Post rejalashtirish** — `matn | vaqt` formatida postni rejalashtirish;
  takrorlash uchun `matn | +1d | 1440` (har 1440 daqiqada). Fon vazifasi
  (`post_loop`) muddati kelgan postlarni avtomatik yuboradi.
- Kanal ma'lumotlari bazada saqlanadi (`channels`, `scheduled_posts`).

### 📄 PDF dan test qo'shish (v5'da qo'shildi)
Admin (yoki ruxsat olgan foydalanuvchi) **PDF fayl yuborib** undan test qo'sha oladi.

**Oqim:** «🧰 Vositalar → ➕ Savol qo'shish → 📄 PDF dan test» → PDF yuborish →
kod → sarlavha → to'g'ri javoblar.

1. **PDF yuborish** — bot PDF matnini `pypdf` bilan o'qib, savollarni avtomatik
   ajratadi. Savollar `1) ...` ko'rinishida bo'lishi kerak.
2. **Kod kiritish** — har bir test **ixtiyoriy kod** bilan kodlanadi (masalan
   `12345`). Kod unikal bo'lishi shart; band bo'lsa bot ogohlantiradi.
3. **Sarlavha** — test nomi (masalan *Matematika 1-chorak testi*).
4. **To'g'ri javoblar** — quyidagi formatlarda kiritiladi.

#### Test kodlari
- Kod — admin o'zi kiritadigan ixtiyoriy belgi (masalan `12345`, `math-1`).
- Kod orqali foydalanuvchilar testni topadi va javob tekshiradi.
- Kodlar `pdf_tests` jadvalida saqlanadi (`code` — unikal).

#### Ochiq savol formati (`36a)2.3`)
- **Test (MC) savollar** — variant harflari ketma-ketligi: `abcdba`
  (har bir savol uchun bitta harf).
- **Ochiq (yozma) savollar** — `savol_raqami + variant_harfi + ")" + javob`:
  - `36a)2.3` — 36-savolning **a)** sharti, javobi `2.3`
  - `36b)4.5` — 36-savolning **b)** sharti, javobi `4.5`
  - `36)2.3` — faqat raqam bilan ham mumkin
- Ikkalasini birga yuborish mumkin: `abcdba 36a)2.3 36b)4.5`

### 📄 PDF testlarni tekshirish (asosiy menyu)
Asosiy menyuda **«📄 PDF testlarni tekshirish»** tugmasi bor:

1. Tugma bosiladi → bot **test kodini so'raydi** («Test kodini kiriting:»).
2. Kod kiritiladi → bot **javob kiritish oynasini** chiqaradi (savollar +
   variantlar + format ko'rsatmasi).
3. Foydalanuvchi javoblarni yuboradi (`abcdba` yoki `36a)2.3`).

#### Javobni tekshirish va natija
- Bot javoblarni to'g'ri kalit bilan solishtiradi.
- **Xato savollar aniq ko'rsatiladi** — savol raqami, foydalanuvchi javobi va
  to'g'ri javob.
- Umumiy natija: **nechta to'g'ri / nechta xato, foiz va baho** (🏆/👍/📚).
- Natija `test_submissions` jadvalida saqlanadi.

> ℹ️ PDF dan test qo'shish **faqat admin** uchun. Boshqa foydalanuvchilar
> «➕ Savol qo'shish» bosganda adminga ruxsat so'rovi yuboriladi.

### 🆕 v4'da qo'shildi (deploy uchun)
- **`health_server.py`** — Render Web Service uchun health-check + keep-alive
  (`/health`, `/ready`, `/ping`, `/status`, `/`)
- **`backup.py`** — SQLite bazani **GitHub Gist**'ga davriy zaxiralash va
  qayta tiklash (Render'ning vaqtinchalik diski muammosini hal qiladi)
- **`start.sh`** — Render start command: ichida avtomatik qayta ishga tushirish
- **`render.yaml`** — Render Blueprint (bir bosishda deploy)
- **`.github/workflows/ci.yml`** — har push'da sintaksis/YAML/xavfsizlik tekshiruvi
- **409 Conflict himoyasi** — auto-deploy paytida ikki instance to'qnashsa,
  bot o'lmaydi, kutib qayta urinadi
- **Yangi env aliaslar** — `GEMINI_KEY_1..5`, `ADMIN_ID`, `ADMIN_USERNAME`

---

### 🆕 v13 da qo'shildi

#### 1) Pastdagi doimiy panel (reply keyboard)
Inline tugmalardan tashqari, ekranning **pastida doimiy** turuvchi panel (talab
bo'yicha **inline emas — reply keyboard**):

```
🚀 Start          🏠 Asosiy menyu
⏰ Eslatma        🔄 Suhbatni tozalash
📢 Kanalga ulanish
```

`/start` bosilganda panel avtomatik chiqadi (`resize_keyboard=True`,
`is_persistent=True`). Har bir tugma matn sifatida keladi va `on_text`
handlerida ushlanadi.

#### 2) Majburiy kanal (subscription gate)
`/start` da IELTS Speaking bo'limlari chiqadi. Foydalanuvchi biror bo'limni
tanlaganda bot **getChatMember** orqali kanalga ulanganini tekshiradi:

- **Ulangan bo'lsa** → bo'lim ochiladi.
- **Ulanmagan bo'lsa** → bot: *«🔒 Davom etishdan oldin kanalga ulanishingiz kerak»*
  deb yozadi, `📢 Kanalga ulanish` havolasi va `✅ Tekshirish` tugmasini beradi.
  «✅ Tekshirish» bosilganda `getChatMember` qayta ishlaydi va obuna
  tasdiqlansa bo'lim ochiladi.

Sozlamalar: `REQUIRED_CHANNEL_URL=https://t.me/matmilliysertifikat`,
`REQUIRED_CHANNEL_ID=@matmilliysertifikat`, `ENABLE_SUB_GATE=true`.
Adminlar gate'siz o'tadi. Tekshirib bo'lmaydigan holatda (kanal yopiq/noto'g'ri)
foydalanuvchi bloklanmaydi.

#### 3) Tabiiy tildagi muloqot (eslatmalar)
Bot oddiy odam kabi, tabiiy tilda yozilgan eslatmani tushunadi:

```
Ertaga soat 12 da matematika darsini takrorlash
30 daqiqadan keyin suv ichish
2 soatdan so'ng dori ichish
Bugun kechqurun soat 20 da uchrashuv
```

`parse_reminder_natural()` vaqtni va kun qismini ajratib oladi
(`ertaga`/`bugun`/`indinga`, `soat 12 da`, `kechqurun` → 20:00,
`30 daqiqadan keyin`), matnni tozalaydi va eslatma o'rnatadi. Ikki qatorli
format (`matn` + `+2h`) ham hamon ishlaydi.

#### 4) Suhbat xotirasi (kontekst)
AI javoblari oldingi gaplarni **eslab qoladi** — har bir so'rovda oxirgi
`HISTORY_CONTEXT_SIZE` (default 6) qatlam Gemini'ning `contents` maydoniga
qo'shiladi. "davom et", "tahlil qil", "shuni ishlab ber" kabi so'rovlar oldingi
mavzuga tayanadi. Yangidan boshlash: **`/reset`** yoki 🖄 Suhbatni tozalash.

#### 5) Asosiy menyu — quizlar va AI
Asosiy menyuda: **🤖 AI bilan ishlash**, **🎯 Testlar (umumiy)**,
IELTS Speaking, IELTS Writing, Matematika, Fizika, Vositalar,
📄 PDF testlarni tekshirish, 🔄 Suhbatni tozalash.

---

### 🆕 v14 da qo'shildi

#### 1) 🔄 Suhbatni tozalash — faqat shu foydalanuvchi uchun
«🔄 Suhbatni tozalash» tugmasi (asosiy menyu, pastdagi doimiy panel va
`/reset`, `/clearhistory` buyruqlari) bosilganda **faqat o'sha foydalanuvchining**
suhbat tarixi o'chiriladi — boshqa foydalanuvchilarning suhbatiga **hech qanday
ta'sir qilmaydi**.

Yangi metod: `Database.clear_conversation(user_id)` — `chat_history` (AI xotirasi)
va `user_states` (joriy holat) ni shu `user_id` bo'yicha tozalaydi
(barcha `DELETE` lar `WHERE user_id = ?` bilan cheklangan) va o'chirilgan
qatlamlar sonini qaytaradi. Bot tomonida `_reset_my_conversation(user_id)`
yordamchisi buni chaqiradi va shu foydalanuvchining navigatsiya tarixini
(`_nav_stack`) ham tozalaydi. Natijada foydalanuvchi **toza holatdan** boshlaydi —
bot oldingi gaplarni eslab qolmaydi, ammo boshqalar ishlamaydi.

#### 2) «Bosh menyu» dublikati olib tashlandi
Ilgari ikkita bir xil ma'noli tugma bor edi: **«⬅️ Bosh menyu»** va
**«🏠 Asosiy menyu»**. Endi **bittasi** qoldi va **hamma joyda bir xil**:

```
[ ⬅️ Orqaga ]  [ 🏠 Asosiy menyu ]
```

- `back_kb()` va `_with_back()` faqat **«🏠 Asosiy menyu»** tugmasini qo'shadi.
- Bo'limlar ichidagi barcha qattiq yozilgan «⬅️ Bosh menyu» tugmalari olib
  tashlandi (`speaking_kb`, `writing_kb`, `subject_kb`, `tools_kb`,
  `qadd_*`, `channel_kb`, `reminders_kb`, `stats_admin_kb`,
  `testadd_subject_kb`) — ularning vazifasini pastdagi yagona
  **«⬅️ Orqaga» + «🏠 Asosiy menyu»** juftligi bajaradi.
- Pastdagi doimiy panel tugmasi ham `BTN_MAIN = "🏠 Asosiy menyu"` — endi
  hamma joyda bir xil nomlanish.

---

## 📋 Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/start` | Boshlash va tanishtirish (pastdagi doimiy panel ham chiqadi) |
| `/menu` | Asosiy menyu (inline tugmalar) |
| `/help` | Batafsil yordam |
| `/quiz` | Soha bo'yicha test o'tash |
| `/reset` | Suhbatni tozalash — bot kontekstni unutadi (yangi suhbat) |
| `/stats` | Statistika — **faqat admin** (boshqalarga ko'rinmaydi) |
| `/history` | Oxirgi suhbatlar tarixi |
| `/clearhistory` | Suhbat tarixini tozalash |
| `/lang` | Til tanlash (uz / en / ru) |
| `/bank [so'z]` | Savollar banki |
| `/manga <nom>` | Manga haqida ma'lumot |
| `/recommend <janr>` | Janr bo'yicha tavsiya |
| `/image <tavsif>` | Rasm generatsiyasi (Imagen) |

Erkin matn yozsangiz — hamma soha bo'yicha javob beradi.

---

## 📁 Fayllar tuzilmasi

```
manga-bot_v5/
├── bot.py                      # Asosiy bot (aiogram 3)
├── database.py                 # SQLite qatlami (aiosqlite)
├── gemini_pool.py              # 5 kalitli round-robin + failover
├── config.py                   # .env / Render env dan sozlamalar
├── health_server.py            # ★ Render health-check + keep-alive
├── watchdog.py                 # ★ Xotira/loop kuzatuvi (24/7 barqarorlik)
├── backup.py                   # ★ GitHub Gist zaxirasi (DB uchun)
├── start.sh                    # ★ Render start command (auto-restart)
├── run.sh                      # VPS uchun wrapper → start.sh
├── render.yaml                 # ★ Render Blueprint
├── .github/workflows/ci.yml    # ★ CI: sintaksis + YAML + xavfsizlik
├── .env.example                # Sozlamalar namunasi (maxfiy qiymatsiz!)
├── .gitignore                  # .env, *.db, logs/ himoyasi
├── requirements.txt            # aiogram, aiohttp, aiosqlite, python-dotenv
├── instant_replies.json        # Tezkor javoblar (50 ta)
├── quiz_data.json              # Test savollari (60 ta, 10 soha)
├── ielts_speaking.json         # IELTS Speaking savollari
├── ielts_writing.json          # IELTS Writing topshiriqlari
├── math_tests.json             # Matematika testlari (kod tizimi)
├── physics_tests.json          # Fizika testlari (kod tizimi)
├── test_bot.py                 # Integratsiya sinovi (bot/DB/AI)
├── test_deploy.py              # ★ Deploy sinovi (YAML/health/backup)
├── handler_test.py             # Handler sinovi
├── README.md                   # Shu fayl
└── deploy/
    ├── manga-bot.service       # systemd unit (VPS)
    ├── Dockerfile              # Docker image
    └── docker-compose.yml      # Docker Compose (VPS)
```

★ = v4'da qo'shilgan yoki o'zgartirilgan fayllar.

---

## 🚀 Lokal ishga tushirish

```bash
cd manga-bot_v4

python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# .env ni tahrirlab: BOT_TOKEN va GEMINI_KEY_1..5 ni yozing

python bot.py
```

Sinovlar:
```bash
python test_deploy.py               # deploy qismi (YAML, health, backup)
python test_bot.py                  # bot qismi (DB, tezkor javob, AI, getMe)
```

> **Nega `.env.example` da haqiqiy kalitlar yo'q?** Chunki bu fayl GitHub'ga
> tushadi. Haqiqiy qiymatlar faqat `.env` da (git'ga tushmaydi) yoki Render
> Environment'da saqlanadi.

---

## 🐙 GitHub'ga joylash

### 1-qadam — GitHub'da repo yaratish

1. [github.com/new](https://github.com/new) ga o'ting
2. **Repository name:** `ai-manager-bot` (yoki o'zingizga mos)
3. **Private** ni tanlang (tavsiya: kod maxfiy bo'lib qoladi)
4. ⚠️ **"Add a README" / ".gitignore" / "license" ni BELGILAMANG** — repo bo'sh bo'lsin
5. **Create repository**

### 2-qadam — Autentifikatsiya tokeni (parol o'rniga)

GitHub 2021-yildan parol bilan push'ni qabul qilmaydi. **Personal Access Token** kerak:

1. [github.com/settings/tokens](https://github.com/settings/tokens) → **Generate new token (classic)**
2. **Note:** `ai-manager-bot deploy`
3. **Expiration:** 90 kun (yoki "No expiration")
4. **Scopes:** ✅ **`repo`** (private repo uchun majburiy)
5. **Generate token** → tokenni **nusxalab saqlang** (bir marta ko'rsatiladi)

### 3-qadam — Git buyruqlari (nusxalab ishlating)

```bash
cd manga-bot_v4

# Git reponi boshlash
git init
git branch -M main

# Muallif ma'lumotlari (bir marta)
git config user.name "Husan Dilmurodov"
git config user.email "sizning@email.com"

# ⚠️ MUHIM: avval maxfiy fayllar himoyalanganini tekshiring!
git status --short                # .env va *.db KO'RINMASLIGI kerak

# Fayllarni qo'shish
git add .
git status --short                # yana bir bor tekshiring!

# Commit
git commit -m "AI Manager Bot v4 — GitHub + Render deploy tayyor"

# Masofaviy repo (USERNAME va REPO nomini almashtiring)
git remote add origin https://github.com/USERNAME/ai-manager-bot.git

# Push (parol o'rniga TOKEN ni kiriting)
git push -u origin main
```

**Push paytida:** `Username: USERNAME` → `Password: <TOKEN>` (GitHub paroli EMAS!)

Keyingi o'zgarishlar uchun:
```bash
git add .
git commit -m "o'zgarish tavsifi"
git push
```

### 4-qadam — Tekshirish

GitHub sahifangizda fayllar ko'rinsin, lekin:
- ❌ `.env` **ko'rinmasin**
- ❌ `*.db` **ko'rinmasin**
- ❌ `logs/` **ko'rinmasin**
- ✅ `.env.example` ko'rinsin (namuna — maxfiy qiymatsiz)

Agar `.env` tasodifan push qilingan bo'lsa — **darhol tokenni va kalitlarni
almashtiring** (git tarixidan o'chirish yetarli emas, chunki ular o'qilgan
bo'lishi mumkin).

---

## ☁️ Render'ga deploy

### Qaysi servis turi? (muhim qaror)

| | **Web Service** (bepul) | **Background Worker** (pullik) |
|---|---|---|
| Narx | **$0** | **$7/oy** |
| Uxlaydimi? | ⚠️ 15 daq harakatsizlikdan keyin | ✅ **hech qachon** |
| Health check | kerak | kerak emas |
| Persistent disk | ❌ (faqat pullik) | ✅ ($0.25/GB/oy) |
| Oylik limit | 750 instance-soat | — |
| Trafik | 5 GB/oy (2026 apreldan) | — |

> **Tavsiya:** bepul boshlash uchun **Web Service + Gist zaxirasi + keep-alive**
> ishlatiladi (bu README'ning asosiy yo'li). Agar $7/oy to'lash imkoni bo'lsa,
> **Background Worker + persistent disk** eng barqaror variant — u hech qachon
> uxlamaydi va baza o'chib ketmaydi.

---

### Yo'l A — Blueprint (bir bosishda, tavsiya etiladi)

`render.yaml` tayyor — Render uni o'qib servisni o'zi yaratadi.

1. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Blueprint**
2. GitHub hisobingizni ulang (bir marta ruxsat berasiz)
3. **`ai-manager-bot`** reponi tanlang → **Connect**
4. Render `render.yaml` ni o'qib, `sync: false` belgilangan qiymatlarni so'raydi:

   | O'zgaruvchi | Qiymat |
   |---|---|
   | `BOT_TOKEN` | Telegram bot tokeni |
   | `GEMINI_KEY_1` … `GEMINI_KEY_5` | 5 ta Gemini kaliti |
   | `GITHUB_TOKEN` | GitHub token (`gist` scope bilan) |
   | `GIST_ID` | *(bo'sh qoldiring — birinchi zaxiralashdan keyin to'ldiriladi)* |

5. **Apply** bosing → Render `pip install` qiladi va servisni ishga tushiradi
6. ~2-3 daqiqadan keyin **Logs** bo'limida:
   ```
   [start.sh] ▶ Bot ishga tushirilmoqda (urinish #1)
   Health server tayyor: http://0.0.0.0:10000/health
   ✅ Baza zaxiradan tiklandi ...   (yoki: Baza mavjud — tiklash shart emas)
   Bot tayyor: @AIManagerProBot
   ```
7. Servis URL'ini ochib tekshiring: `https://ai-manager-bot-xxxx.onrender.com/health`
   → `{"status":"ok","ready":true,"bot":"@AIManagerProBot", ...}`

---

### Yo'l B — Qo'lda (Dashboard orqali)

1. **New +** → **Web Service**
2. Reponi tanlang
3. Sozlamalar:
   - **Name:** `ai-manager-bot`
   - **Region:** eng yaqin (masalan Frankfurt)
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command:** `bash start.sh`
   - **Instance Type:** `Free`
   - **Health Check Path:** `/health`
   - **Auto-Deploy:** `Yes` ✅ (GitHub'ga push qilganda avtomatik qayta deploy)
4. **Environment** bo'limida o'zgaruvchilarni qo'lda qo'shing:

   ```
   BOT_TOKEN          = <BotFather bergan token>
   GEMINI_KEY_1       = <1-kalit>
   GEMINI_KEY_2       = <2-kalit>
   GEMINI_KEY_3       = <3-kalit>
   GEMINI_KEY_4       = <4-kalit>
   GEMINI_KEY_5       = <5-kalit>
   GEMINI_MODELS      = gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash,gemini-3.5-flash
   ADMIN_USERNAME     = Husan_Dilmurodov
   ADMIN_PHONE        = +998 883800311
   DB_PATH            = bot.db
   BACKUP_ENABLED     = true
   GITHUB_TOKEN       = ghp_...
   RESTORE_ON_START   = true
   BACKUP_INTERVAL_SECONDS = 3600
   ENV PYTHON_VERSION = 3.11.9
   ```
   > ⚠️ `PYTHON_VERSION` ni qo'shmang deb o'ylamang — `python:3.11` muhim,
   > chunki `VACUUM INTO` va aiogram 3.13 uchun kerak.

5. **Create Web Service**

---

### Ma'lumotlar bazasi muammosi

**Muammo:** Render'ning **bepul** tarifida disk **vaqtinchalik (ephemeral)**.
Har deploy, qayta ishga tushish yoki uxlashdan keyin `bot.db` **o'chib ketadi** —
foydalanuvchilar, suhbat tarixi, test natijalari yo'qoladi.

**3 ta yechim:**

| # | Yechim | Narx | Afzallik | Kamchilik |
|---|---|---|---|---|
| **1** | **GitHub Gist zaxirasi** ⭐ | **$0** | Bepul, o'rnatish oson, kod o'zgarmaydi | Oxirgi zaxiraga qadar ma'lumot yo'qolishi mumkin (interval) |
| **2** | **Persistent Disk** | $0.25/GB/oy | Eng oson, real-time | Bepul tarifda **yo'q** — Worker/paid instance kerak |
| **3** | **PostgreSQL (Neon/Supabase)** | $0 | Eng mustahkam, real-time | Kodni o'zgartirish kerak (aiosqlite → asyncpg) |

#### ⭐ Yechim 1 — GitHub Gist zaxirasi (tavsiya, bepul)

Kod **tayyor** — `backup.py` shu ishni qiladi:

1. **Token yarating:** [github.com/settings/tokens](https://github.com/settings/tokens)
   → Generate new token (classic) → scope: ✅ **`gist`** (boshqasi shart emas)
2. Render Environment'ga qo'shing:
   ```
   BACKUP_ENABLED = true
   GITHUB_TOKEN   = ghp_...
   RESTORE_ON_START = true
   BACKUP_INTERVAL_SECONDS = 3600
   ```
3. Servis qayta ishga tushgach, **Logs**'da:
   ```
   YANGI GIST YARATILDI: 4f8a...b2c1 — bu id'ni env (GIST_ID) sifatida saqlang!
   ```
4. Shu **GIST_ID** ni Render Environment'ga qo'shing → keyingi deploy'larda
   o'sha gist yangilanadi (yangi yaratilmaydi)
5. Tekshirish: gist'da `bot.db.b64.gz` fayli ko'rinadi va har soatda yangilanadi

**Qanday ishlaydi:**
- `VACUUM INTO` — WAL rejimida ham **izchil** nusxa (faylni oddiy `cp`
  qilishdan farqli, bot yozib turganda ham buzilmaydi)
- `gzip` + `base64` — gist faqat matn qabul qiladi, baza esa siqilib kichrayadi
- Bot ishga tushganda: baza **yo'q bo'lsa** — gist'dan tiklanadi

#### Yechim 3 — PostgreSQL'ga o'tish (kelajak uchun)

Agar loyiha kattalashsa, `database.py` ni `asyncpg`'ga o'tkazish kerak:

```bash
pip install asyncpg
# DATABASE_URL = postgresql://user:pass@host/db
```

Neon (neon.tech) yoki Supabase (supabase.com) bepul PostgreSQL beradi.
**Bu o'zgarish kodni qayta yozishni talab qiladi** — hozircha Gist yechimi
yetarli.

---

## ⏰ 24/7 uzluksizlik

Bepul Web Service **15 daqiqa** harakatsizlikdan keyin "uxlaydi" (spin down) va
keyingi so'rovda ~1 daqiqada uyg'onadi. Bot uchun bu yomon: xabar kelganda
javob 1 daqiqa kechikadi.

**Yechim — UCH qatlamli himoya** (bepul tarifda ham bot uxlamaydi):

| Qatlam | Nima qiladi | Yoqish |
|---|---|---|
| **1. Tashqi keep-alive** ⭐ | Har 5 daqiqada `/ping` ga so'rov — servis uyg'oq qoladi | UptimeRobot (bepul) |
| **2. Self-ping** | Bot o'zini har 10 daqiqada ping qiladi | Avtomatik (`RENDER_EXTERNAL_URL`) |
| **3. Watchdog** | Xotira oqishi va loop bloklanishini kuzatadi, kerak bo'lsa toza restart | Avtomatik (`WATCHDOG_ENABLED=true`) |

> **Nega uchtasi?** Render ba'zi holatlarda o'z-o'zini ping'ni "tashqi so'rov"
> deb hisoblamasligi mumkin — shuning uchun **tashqi pinger (1-qatlam) asosiy**.
> 2 va 3-qatlamlar qo'shimcha ishonchlilik beradi.

### 1-qatlam — Tashqi keep-alive (asosiy, ishonchli)

#### UptimeRobot bilan sozlash (qadam-baqadam, bepul)

1. **[uptimerobot.com](https://uptimerobot.com)** → **Sign Up** (bepul, karta shart emas)
2. Email'ni tasdiqlang va tizimga kiring
3. **+ Add New Monitor** tugmasini bosing
4. Quyidagilarni to'ldiring:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `AI Manager Bot`
   - **URL (or IP):** `https://SIZNING-SERVIS.onrender.com/ping`
     > ⚠️ `SIZNING-SERVIS` o'rniga Render'dagi haqiqiy servis nomingizni yozing.
     > Render URL formati: `https://<app-name>.onrender.com/ping`
   - **Monitoring Interval:** `5 minutes` (bepul tarifda eng kichigi)
5. **Create Monitor** bosing — tayyor! Endi har 5 daqiqada servis uyg'oq qoladi.

> `/ping` eng yengil endpoint (`"ok"` qaytaradi, bir necha bayt) — trafikni
> behuda sarflamaydi. Oyiga ~5 GB bepul trafik yetib ortadi.

#### Muqobil: cron-job.org

1. **[cron-job.org](https://cron-job.org)** → ro'yxatdan o'ting (bepul)
2. **Create cronjob** → **Title:** `AI Manager Bot ping`
3. **URL:** `https://SIZNING-SERVIS.onrender.com/ping`
4. **Schedule:** har 5 daqiqa (`*/5 * * * *`)
5. **Save** — tayyor.

### 2-qatlam — Self-ping (qo'shimcha, avtomatik)

`config.py` Render'ning `RENDER_EXTERNAL_URL` o'zgaruvchisini avtomatik topadi
va bot o'zini har 10 daqiqada ping qiladi:

```
SELF_PING_INTERVAL = 600   # sekund
```

Bu **qo'shimcha** himoya — Render ba'zi holatlarda o'z-o'zini ping'ni
hisobga olmasligi mumkin, shuning uchun **tashqi pinger (UptimeRobot) asosiy**
hisoblanadi. Ikkalasi birga ishlatilsa eng yaxshi natija beradi.

### 3-qatlam — Watchdog (uzoq muddatli barqarorlik)

Bot kunlab ishlaganda xotira oqib ketishi (memory leak) yoki event loop
bloklanishi mumkin. `watchdog.py` buni kuzatadi:

```
WATCHDOG_ENABLED=true
WATCHDOG_INTERVAL=300            # har 5 daqiqada tekshiradi
WATCHDOG_MEMORY_LIMIT_MB=400     # Render bepul (~512 MB) uchun xavfsiz chegara
WATCHDOG_GC_EVERY=6              # har 6 tekshiruvda gc.collect()
```

- Xotira chegaradan oshsa — jarayon **toza** to'xtatiladi, `start.sh` uni
  5 sekundda qayta ishga tushiradi (OOM-kill'ning nazoratsiz o'lishidan yaxshi).
- Event loop 5 sekunddan ko'p bloklansa — log'ga ogohlantirish yoziladi.
- Holat `/status` da ko'rinadi: `memory_mb`, `memory_peak_mb`, `loop_lag_ms`.

### ⚠️ Muhim cheklovlar (2026)

- Render **bepul tarifda Background Worker bermaydi** — eng arzoni $7/oy
- Bepul Web Service oyiga **750 instance-soat** oladi (bir servis uchun yetarli)
- 2026 apreldan bepul **trafik 5 GB/oy** (keep-alive ko'p trafik yemaydi)
- Render bepul servisni **istalgan vaqtda qayta ishga tushirishi mumkin**

### 🏆 Platformalarni taqqoslash — qaysi biri 24/7 uchun yaxshi?

| Platforma | Uxlaydimi? | Narx | Baza saqlanadimi? | Baho |
|---|---|---|---|---|
| **Render Web Service (bepul)** | ⚠️ Ha, 15 daq (keep-alive bilan yechiladi) | Bepul | ❌ (Gist zaxirasi kerak) | ⭐⭐⭐ Oson boshlash |
| **Render Background Worker** | ✅ Yo'q, hech qachon | $7/oy | ✅ (persistent disk) | ⭐⭐⭐⭐⭐ Eng oson 24/7 |
| **Oracle Cloud Always Free** | ✅ Yo'q, hech qachon | Bepul | ✅ (doimiy disk) | ⭐⭐⭐⭐⭐ Eng yaxshi bepul |
| **Fly.io** | ⚠️ Bepul tarifda uxlaydi (auto-stop) | Bepul/$2+ | ✅ (volume) | ⭐⭐⭐ |
| **Koyeb** | ⚠️ Bepul tarifda uxlaydi | Bepul | ❌ | ⭐⭐ |
| **VPS (Hetzner/DigitalOcean)** | ✅ Yo'q | ~$4-5/oy | ✅ | ⭐⭐⭐⭐ To'liq nazorat |

**Tavsiya:**
- **Bepul, oson** → Render Web Service + UptimeRobot + Gist zaxirasi (shu loyiha)
- **Bepul, 100% kafolat** → **Oracle Cloud Always Free** (pastda)
- **Eng oson, kafolat** → Render Background Worker ($7/oy)

### Variant — Oracle Cloud Always Free (bepul, doimiy, 100% 24/7)

Oracle Cloud **Always Free** ARM VM (4 CPU, 24 GB RAM) — haqiqiy doimiy bepul
server, **hech qachon uxlamaydi**. Eng ishonchli bepul variant.

**Qadam-baqadam:**

1. **[cloud.oracle.com](https://cloud.oracle.com)** → **Sign Up** (karta tekshiriladi, lekin Always Free resurslar uchun pul olinmaydi)
2. **Region** tanlang (o'zingizga yaqin: `Germany Central (Frankfurt)` yoki `UAE`)
3. **Create a VM Instance:**
   - **Image:** `Ubuntu 22.04` (yoki 24.04)
   - **Shape:** `VM.Standard.A1.Flex` (ARM, Always Free) → **4 OCPU, 24 GB RAM**
   - **Add SSH keys:** yangi kalit yarating yoki mavjudini yuklang
   - **Create** bosing (~1 daqiqa)
4. VM tayyor bo'lgach, **Public IP** ni nusxalab oling
5. SSH bilan kiring:
   ```bash
   ssh -i /path/to/ssh-key ubuntu@<VM_PUBLIC_IP>
   ```
6. Botni o'rnating (VPS + systemd yo'li — pastdagi bo'limga qarang):
   ```bash
   sudo apt update && sudo apt install -y python3-venv python3-pip git
   git clone https://github.com/USERNAME/ai-manager-bot.git
   cd ai-manager-bot
   cp .env.example .env && nano .env      # token va kalitlarni yozing
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   sudo cp deploy/manga-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now manga-bot
   ```
7. **Oracle Security List**'da (VPC → Security Lists) kerak bo'lsa port oching —
   bot polling ishlatgani uchun **kiruvchi port kerak emas**, faqat chiquvchi
   trafik yetarli.

> 💡 Oracle'da `PORT` berilmaydi → health server avtomatik o'chadi (kerak ham
> emas, chunki VM uxlamaydi). `WATCHDOG_MEMORY_LIMIT_MB=0` qoldiring (24 GB RAM).

---

## 🌐 Boshqa deployment variantlari

### Variant — VPS + systemd (eng barqaror, arzon)

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
sudo useradd -m -s /bin/bash mangabot

sudo mkdir -p /opt/manga-bot
sudo cp -r ./* /opt/manga-bot/
sudo cp .env /opt/manga-bot/.env
cd /opt/manga-bot

sudo -u mangabot python3 -m venv .venv
sudo -u mangabot .venv/bin/pip install -r requirements.txt

sudo cp deploy/manga-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now manga-bot

sudo systemctl status manga-bot
sudo journalctl -u manga-bot -f
```

### Variant — Docker + docker-compose

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f
```

### Variant — Oracle Cloud Always Free (bepul, doimiy)

To'liq qadam-baqadam qo'llanma yuqoridagi **"24/7 uzluksizlik"** bo'limida
berilgan (VM yaratish → SSH → systemd bilan o'rnatish).

---

## ⚙️ Sozlamalar (.env)

| O'zgaruvchi | Tavsif | Standart |
|---|---|---|
| `BOT_TOKEN` | Telegram bot tokeni | — |
| `GEMINI_API_KEYS` | 5 ta kalit (vergul bilan) | — |
| `GEMINI_KEY_1..5` | 5 ta kalit (alohida — Render uchun) | — |
| `GEMINI_MODELS` | Model zaxira zanjiri | `gemini-3.5-flash-lite,...` |
| `DB_PATH` | SQLite fayl yo'li | `bot.db` |
| `PORT` | Health server porti (Render beradi) | `0` (o'chiq) |
| `ENABLE_HEALTH_SERVER` | Health server yoqilishi | `true` |
| `SELF_PING_INTERVAL` | Self-ping oralig'i (sekund) | `600` |
| `WATCHDOG_ENABLED` | Watchdog (xotira/loop kuzatuvi) | `true` |
| `WATCHDOG_INTERVAL` | Watchdog tekshirish oralig'i (sekund) | `300` |
| `WATCHDOG_MEMORY_LIMIT_MB` | Xotira chegarasi (0 = o'chiq) | `0` |
| `WATCHDOG_GC_EVERY` | Har necha tekshiruvda `gc.collect()` | `6` |
| `BACKUP_ENABLED` | Gist zaxirasi yoqilishi | `false` |
| `GITHUB_TOKEN` | GitHub token (`gist` scope) | — |
| `GIST_ID` | Zaxira gist id'si | — |
| `BACKUP_INTERVAL_SECONDS` | Zaxiralash oralig'i | `3600` |
| `RESTORE_ON_START` | Ishga tushganda tiklash | `true` |
| `ADMIN_ID` / `ADMIN_IDS` | Admin telegram id(lar) | — |
| `ADMIN_USERNAME` | Admin username (`@` siz) | — |
| `ENABLE_INSTANT_REPLIES` | Tezkor javoblar | `true` |
| `INSTANT_MAX_LEN` | Tezkor javob uchun maks. uzunlik | `60` |
| `QUIZ_QUESTIONS_PER_SESSION` | Testdagi savollar soni | `5` |
| `ENABLE_IMAGE_GEN` | Rasm generatsiyasi | `true` |
| `COOLDOWN_SECONDS` | Kalit cooldown vaqti | `60` |
| `LOG_LEVEL` | Log darajasi | `INFO` |

---

## 🛠 Muammolarni bartaraf etish

### GitHub

| Muammo | Yechim |
|---|---|
| `remote: Support for password authentication was removed` | Parol o'rniga **Personal Access Token** ishlating |
| `Permission denied (publickey)` | HTTPS emas, SSH ishlatilmoqda — `git remote set-url origin https://...` |
| `.env` tasodifan push qilindi | Tokenlarni **darhol almashtiring**; `git rm --cached .env` + commit + push |
| `failed to push: non-fast-forward` | `git pull --rebase origin main` keyin `git push` |
| `ghp_...` GitHub'da ko'rinib qoldi | GitHub tokenni avtomatik bloklaydi — yangisini yarating |

### Render

| Muammo | Yechim |
|---|---|
| Deploy muvaffaqiyatsiz: `No such file: start.sh` | `start.sh` commit qilingan va bajariladigan: `git update-index --chmod=+x start.sh` |
| `BOT_TOKEN bo'sh — .env faylini to'ldiring` | Render **Environment** bo'limida o'zgaruvchilarni qo'shing (`.env` fayli git'da yo'q!) |
| `AllKeysFailedError` | Kalitlar kvotasi tugagan — yangi kalit qo'shing yoki `COOLDOWN_SECONDS` oshiring |
| Servis "Healthy" bo'lmayapti | **Health Check Path** = `/health` ekanini tekshiring |
| Bot javob bermayapti, uxlaydi | UptimeRobot bilan `.../ping` ga har 5 daqiqada ping qo'ying |
| Bot uxlab qoladi (UptimeRobot ham bor) | Monitor **Active** ekanini va URL `/ping` bilan tugashini tekshiring; `SELF_PING_INTERVAL=300` qilib kamaytiring |
| Xotira oshib bot o'ldi (OOM) | `WATCHDOG_MEMORY_LIMIT_MB=400` qo'ying — toza restart bo'ladi; log'da `XOTIRA CHEGARASI OSHILDI` ko'rinadi |
| Log'da `Event loop ... bloklangan` | Og'ir so'rov yoki sinxron I/O — odatda o'zi o'tib ketadi; tez-tez bo'lsa `WATCHDOG_INTERVAL` oshiring |
| **409 Conflict** log'da | Ikki instance ishlayapti — eski deploy'ni **Suspend** qiling. Bot endi o'zi kutib qayta urinadi |
| Baza har deploy'da o'chib ketadi | `BACKUP_ENABLED=true` + `GITHUB_TOKEN` qo'shing (Gist zaxirasi) |
| `YANGI GIST YARATILDI: ...` har restartda | `GIST_ID` ni Render Environment'ga qo'shishingiz kerak |
| Deploy ~15 daqiqada "o'ldi" | Free tarif uxlaydi — UptimeRobot yoki paid instance |
| Free instance-soat tugadi (750) | Boshqa servis o'chirilganini tekshiring yoki paid'ga o'ting |

### Bot

| Muammo | Yechim |
|---|---|
| `BOT_TOKEN bo'sh` | `.env` / Render Environment'ni tekshiring |
| `qr` / test savollari chiqmayapti | `quiz_data.json` mavjudligini tekshiring |
| Rasm yaratilmayapti | Imagen hisobingizda yoqilmagan bo'lishi mumkin |
| Bot javob bermayapti (lokal) | `logs/bot.log`; boshqa nusxa ishlab turgan bo'lsa to'xtating |

### Loglarni kuzatish (Render)

**Dashboard → servisingiz → Logs** bo'limida real-time log ko'rinadi.

Foydali qidiruvlar (Logs'da filtrga yozing):

| Qidiruv | Nimani ko'rsatadi |
|---|---|
| `ERROR` | Barcha xatolar |
| `[start.sh]` | Qayta ishga tushishlar (auto-restart) |
| `Zaxiralash` / `zaxiralandi` | Gist backup holati |
| `Kalitlar:` | Nechta kalit yuklanganini |
| `409 Conflict` | Ikki instance to'qnashuvi |
| `AllKeysFailed` | Barcha kalitlar tugagan |

Log'ni saqlash (Render'dan tashqarida): Dashboard → **Logs** → **Download**.

`/status` endpoint ham jonli holatni ko'rsatadi:
```json
{
  "status": "ok", "ready": true, "bot": "@AIManagerProBot",
  "uptime_human": "2h 15m 3s", "keys": 5, "models": 4,
  "backup_enabled": true, "backup_count": 3,
  "last_backup": "2026-10-15T09:00:12Z", "requests_total": 42
}
```

---

## 🔄 CI/CD

`.github/workflows/ci.yml` har push va pull request'da ishlaydi:

1. ✅ **`py_compile`** — barcha `.py` fayllar sintaksisi
2. ✅ **flake8** — jiddiy xatolar (E9xx, F63, F7, F82)
3. ✅ **Import testi** — modullar yuklanadimi
4. ✅ **JSON validatsiyasi** — `*.json` bazalar
5. ✅ **YAML validatsiyasi** — `render.yaml`, `ci.yml`, `docker-compose.yml`
6. ✅ **Xavfsizlik** — `.env` yoki `*.db` commit qilinmaganini tekshirish

Natijani GitHub'da **Actions** bo'limida ko'rasiz. Agar push qilganda CI
yiqilsa — Render'ga buzuq kod ketmaydi (Auto-Deploy'ni "After CI passes"
qilib sozlash mumkin: Settings → Auto-Deploy → **After CI Checks Pass**).

**Avtomatik deploy:** Render'da `autoDeploy: true` — GitHub'ga push qilganingizda
Render o'zi qayta deploy qiladi.

---

## 🔬 Sinov natijalari

`python test_deploy.py` (v4 — deploy qismi):
- ✅ YAML fayllar to'g'ri (`render.yaml`, `ci.yml`, `docker-compose.yml`)
- ✅ `render.yaml` da kerakli env kalitlar va `healthCheckPath=/health`
- ✅ `.gitignore` qamrovi (`.env`, `*.db`, `logs/`, `.venv/`)
- ✅ `.env.example` da haqiqiy maxfiy qiymat yo'q
- ✅ `config.py` yangi aliaslar (`GEMINI_KEY_1..5`, `ADMIN_ID`)
- ✅ `start.sh` / `run.sh` sintaksisi
- ✅ Backup aylanmasi: `VACUUM INTO` → gzip → base64 → tiklash (ma'lumot buzilmagan)
- ✅ Health server: `/health`, `/ready`, `/ping`, `/status`, `/` — jonli so'rovlar
- ✅ Dockerfile (non-root, HEALTHCHECK, start.sh)

`python test_bot.py` (bot qismi):
- ✅ Ma'lumotlar bazasi, tezkor javoblar, quiz, soha aniqlash
- ✅ Gemini pool (haqiqiy API), Telegram `getMe`

`python test_tools.py` (v5 — Tools va kanal boshqaruvi):
- ✅ Tools menyusida aynan **2 ta** amal tugmasi (Savol qo'shish, Kanalga ulash)
- ✅ Eski tugmalar (ovoz, rasm, savollar banki) olib tashlangan
- ✅ Kanal CRUD (ulash, ro'yxat, upsert, o'chirish)
- ✅ Rejalashtirilgan postlar (qo'shish, muddat, takrorlash, o'chirish)
- ✅ Savol qo'shish (Speaking Part 1/2, Writing Task 2)
- ✅ Admin ruxsat oqimi (`addq` so'rovi → tasdiqlash → admin huquqi)
- ✅ Test kod tizimi va `abcdfdddd` javob tekshirish
- ✅ Vaqt tahlili (`+2h`, `09:30`, aniq sana)

**Jami: 59/59 test o'tdi.**

`python test_pdf.py` (v5 — PDF test tizimi):
- ✅ PDF matnidan savollarni ajratish (test + ochiq savollar)
- ✅ Javob kiritmasini tahlil qilish (`abcdba`, `36a)2.3`, `36)2.3`)
- ✅ Javoblarni tekshirish va xatolarni aniqlash
- ✅ Baza: `pdf_tests` jadvali (qo'shish, olish, kod bandligi, o'chirish)
- ✅ Haqiqiy PDF yaratib, matn ajratish (pypdf)

**Jami: 32/32 test o'tdi.**

`python test_v13.py` (v13 — panel, kanal gate, xotira): **38/38 ✅**
`python test_memory.py` (v13 — suhbat xotirasi): **34/34 ✅**

`python test_channel_stats.py` (v6 — kanal tasdiqlash + admin statistikasi):
- ✅ Asosiy menyuda **📊 Statistika** faqat **adminga** ko'rinadi
- ✅ `/stats` buyrug'i va `menu:stats` callback faqat admin uchun
- ✅ Stats bo'limida **➕ Kanal qo'shish** va **📈 Kanallar statistikasi**
- ✅ Bot kanalga **admin qilinganda** (`my_chat_member`) adminga xabar boradi:
  "@foydalanuvchi shu kanalni botga qo'shdi" + ✅ Ruxsat berish / ❌ Rad etish
- ✅ Ruxsat berilgach kanal botga ulanadi; rad etilsa ulanmaydi
- ✅ Begona foydalanuvchi kanal qarorini qabul qila olmaydi
- ✅ Kanallar statistikasi: a'zolar soni (+ postlar soni, yuborilganlar) ko'rsatiladi

**Jami: 30/30 test o'tdi.**

---

## 📢 Kanal admini va statistika (v6'da qo'shildi)

### Bot kanalga admin qilinganda
1. Foydalanuvchi botni kanalga **admin** qilib qo'shadi.
2. Bot `my_chat_member` hodisasini oladi va **adminga** xabar yuboradi:
   ```
   📢 Bot kanalga admin qilindi
   👤 Qo'shgan: @foydalanuvchi
   🆔 Foydalanuvchi ID: 123456789
   📣 Kanal: Kanal nomi (@kanal)
   🆔 Kanal ID: -1001234567890
   ```
3. Admin **✅ Ruxsat berish** / **❌ Rad etish** tugmalari bilan javob beradi.
4. Ruxsat berilgach kanal botga **ulanadi** (post joylash va boshqarish uchun).
   Rad etilsa — kanal ulanmaydi. Bot allaqachon admin bo'lgan yoki kanal
   avval ulangan bo'lsa, takroriy so'rov yuborilmaydi.

### Statistika (faqat admin)
- **📊 Statistika** tugmasi **faqat adminning asosiy menyusida** ko'rinadi.
  Oddiy foydalanuvchi menyusida bu tugma **yo'q**; `/stats` ham taqiqlangan.
- Statistika bo'limida:
  - Umumiy ko'rsatkichlar (foydalanuvchilar, xabarlar, testlar, AI so'rovlar)
  - **➕ Kanal qo'shish** — @username yoki ID orqali kanal ulash
  - **📈 Kanallar statistikasi** — har bir kanal uchun:
    - 👥 **a'zolar soni** (Telegram'dan jonli olinadi)
    - 📨 **postlar soni** (jami / yuborilgan)
    - 🆔 kanal ID va @username

### Yangi jadval: `pending_channels`
Bot kanalga admin qilinganda yaratiladigan tasdiqlash so'rovlari:
`channel_id`, `title`, `username`, `requested_by`, `status`, `created_at`,
`decided_by`, `decided_at`.

**Yangi callback'lar:** `admin:chan:ok:<id>`, `admin:chan:no:<id>`,
`menu:stats`, `stats:chanadd`, `stats:chanstats`.

---

## 🔒 Xavfsizlik

- `.env` faylini **hech qachon** git'ga qo'shmang (`.gitignore` da bor)
- Render'da maxfiy qiymatlarni **faqat Environment** orqali bering (`.env` emas)
- `render.yaml` da maxfiy qiymatlar `sync: false` — Render ularni so'raydi,
  GitHub'da saqlanmaydi
- Token va API kalitlar ochiq yuborilgan bo'lsa, ularni **almashtiring**
- `bot.db` va Gist zaxirasida foydalanuvchi ma'lumotlari bor — xavfsiz saqlang
- `GITHUB_TOKEN` ga faqat **`gist`** scope bering (to'liq `repo` shart emas —
  zaxira uchun)

---

## ⚠️ Muhim eslatma: model nomi

Siz so'ragan **`gemini-1.5-flash` modeli Google tomonidan butunlay olib
tashlangan** — API unga `404` qaytaradi. Shuning uchun kod **model zaxira
zanjiri** bilan qurilgan:

```
gemini-3.5-flash-lite → gemini-3.1-flash-lite → gemini-3.8-flash → gemini-3.5-flash
```

Birinchi model kvota/xato bersa, avtomatik keyingisiga o'tadi. Sinovda
`gemini-3.5-flash-lite` va `gemini-3.1-flash-lite` ishlayotgani tasdiqlandi.

---

## 📄 Litsenziya

Shaxsiy foydalanish uchun. Muallif: Husan Dilmurodov.