# FPL AI Assistant 🤖⚽

> نظام ذكاء اصطناعي (rules-based) يساعدك **أسبوعياً** في قرارات Fantasy Premier League — بدون تدخل تلقائي بحسابك الشخصي.

> [!IMPORTANT]
> **⚠️ تنويه مهم:** هذا المشروع للتوصية والتحليل فقط. القرار النهائي دائماً لك، والنظام **لا يُعدّل حسابك** بأي شكل. لا يوجد تسجيل دخول تلقائي ولا تنفيذ تحويلات آلي.

---

## ما يفعله هذا المشروع

| الخطوة | التفاصيل |
|---|---|
| 📥 يسحب بياناتك | تشكيلتك الحالية + رصيدك + تحويلاتك المتبقية من FPL API الرسمي |
| 🏆 يقارن بأفضل 10 | يجلب تشكيلات أفضل 10 مدراء عالمياً ويقارنها بتشكيلتك |
| 🏥 يتحقق من الإصابات | يجلب أحدث حالات الإصابة من FPL API الرسمي |
| 🧠 يحلل ويوصي | يقترح تحويلات + كابتن + توقيت Chips (بدون AI API — منطق قواعد بحت) |
| 📱 يُرسل لتيليجرام | تقرير أسبوعي مفصّل عربي يصلك قبل الديدلاين |
| 🔄 يخطط على مدى الجولات | يحفظ مرشحي التحويل المؤجلين ويُعيد تقييمهم جولة تلو الأخرى |

---

## إعداد المشروع (خطوة بخطوة)

### 1. متطلبات النظام

```
Python 3.11+
pip
```

### 2. تثبيت المتطلبات

```bash
pip install -r requirements.txt
```

أو إن كان لديك `make`:
```bash
make install
```

---

### 3. إعداد Telegram Bot (خطوات يدوية لمرة واحدة)

> [!NOTE]
> هذه الخطوات ضرورية مرة واحدة فقط. لا تحتاج إلى أي اشتراك مدفوع.

**الخطوة 1:** افتح تيليجرام وابحث عن `@BotFather`

**الخطوة 2:** أرسل `/newbot` واتبع التعليمات:
- أدخل اسماً للبوت (مثال: "FPL Assistant")
- أدخل username ينتهي بـ `bot` (مثال: `my_fpl_assistant_bot`)

**الخطوة 3:** BotFather سيُعطيك `TELEGRAM_BOT_TOKEN` بهذا الشكل:
```
123456789:ABCDEFabcdef1234567890_XXXXXXXX
```

**الخطوة 4:** ابحث عن البوت الجديد في تيليجرام وأرسل له أي رسالة (مثال: `hi`)

**الخطوة 5:** افتح هذا الرابط في المتصفح (استبدل TOKEN):
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

ابحث عن `"chat"` → `"id"` في الرد — هذا هو `TELEGRAM_CHAT_ID`

> [!TIP]
> إذا كان `chat_id` رقماً سالباً (مثال: `-987654321`) فهذا يعني أنك تستخدم مجموعة (Group) — هذا صحيح وسيعمل.

---

### 4. معرفة رقم فريقك في FPL

افتح [fantasy.premierleague.com](https://fantasy.premierleague.com) → تسجيل الدخول → انظر رابط صفحتك:
```
https://fantasy.premierleague.com/entry/1234567/event/1
                                          ↑
                               هذا هو FPL_TEAM_ID
```

---

### 5. إعداد متغيرات البيئة (محلياً)

```bash
# نسخ ملف المثال
cp .env.example .env

# تعديل القيم الحقيقية
notepad .env      # Windows
nano .env         # Linux/Mac
```

محتوى ملف `.env`:
```
FPL_TEAM_ID=رقم_فريقك
TELEGRAM_BOT_TOKEN=توكن_البوت
TELEGRAM_CHAT_ID=معرف_المحادثة
INJURY_SOURCE_URL=https://www.premierinjuries.com/injury-table.php
TOP_N_MANAGERS=10
```

> [!CAUTION]
> **لا ترفع ملف `.env` للـ GitHub أبداً!** وهو مُضاف بالفعل لـ `.gitignore` حمايةً لبياناتك.

---

### 6. اختبار الإعداد محلياً

**اختبار رسالة تيليجرام:**
```bash
python -c "
import sys; sys.path.insert(0, 'src')
from dotenv import load_dotenv; load_dotenv()
from config import config
from telegram_notifier import send_test_message
send_test_message(config.telegram_bot_token, config.telegram_chat_id)
print('تحقق من تيليجرام!')
"
```

**تشغيل كامل:**
```bash
python src/main.py
# أو
make run
```

---

## GitHub Actions (التشغيل التلقائي الأسبوعي)

### إضافة الأسرار لـ GitHub

اذهب إلى: **Repo → Settings → Secrets and variables → Actions → New repository secret**

أضف هذه الأسرار الثلاثة:

| الاسم | القيمة |
|---|---|
| `FPL_TEAM_ID` | رقم فريقك |
| `TELEGRAM_BOT_TOKEN` | توكن البوت من @BotFather |
| `TELEGRAM_CHAT_ID` | معرّف محادثتك مع البوت |

### الجدولة التلقائية

يعمل تلقائياً **كل جمعة الساعة 16:00 UTC** (قابل للتعديل في `.github/workflows/weekly_run.yml`).

> [!WARNING]
> **ديدلاين FPL يتغيّر أسبوعياً.** تحقق من الديدلاين الفعلي كل أسبوع وعدّل الـ cron إذا لزم (راجع `weekly_run.yml`). الأصل أن يعمل قبل الديدلاين بـ4-6 ساعات على الأقل.

### تشغيل يدوي للاختبار

**Actions → FPL Weekly Report → Run workflow → Run workflow**

---

## هيكل المشروع

```
fpl-ai-assistant/
├── .github/
│   └── workflows/
│       └── weekly_run.yml      # جدولة GitHub Actions
├── src/
│   ├── config.py               # قراءة الإعدادات (مركزي)
│   ├── fpl_client.py           # اتصالات FPL API الرسمي
│   ├── squad_optimizer.py      # بناء تشكيلة الجولة الأولى (PuLP)
│   ├── injuries_source.py      # بيانات الإصابات
│   ├── top_managers.py         # أفضل 10 مدراء عالمياً
│   ├── transfer_planner.py     # طابور التحويلات متعدد الجولات
│   ├── decision_engine.py      # محرك القرار المركزي ⭐
│   ├── report_builder.py       # بناء نص التقرير العربي
│   ├── telegram_notifier.py    # إرسال التقرير
│   └── main.py                 # نقطة التشغيل الرئيسية
├── data/
│   ├── cache/                  # تخزين مؤقت
│   ├── history/                # أرشيف التقارير (gw_N.json)
│   └── state/                  # الحالة الدائمة (transfer_queue.json)
├── tests/
│   └── test_decision_engine.py # Unit tests لمحرك القرار
├── .env.example                # نموذج المتغيرات المطلوبة
├── requirements.txt
├── Makefile
└── README.md
```

---

## Tech Stack

| المكوّن | الأداة | لماذا؟ |
|---|---|---|
| اللغة | Python 3.11+ | دعم واسع لمكتبات FPL |
| FPL Data | `requests` + API رسمي | مجاني بالكامل، بدون مفتاح |
| الإصابات | FPL API + BeautifulSoup4 | مصدران متكاملان |
| تحسين التشكيلة | `PuLP` (Linear Programming) | حل رياضي دقيق |
| الإشعارات | Telegram Bot API | مجاني ومباشر |
| الجدولة | GitHub Actions | مجاني، بدون سيرفر خاص |
| الأسرار | GitHub Secrets | حماية كاملة للتوكنات |

---

## أوامر مفيدة

```bash
make run          # تشغيل محلي
make test         # تشغيل unit tests
make lint         # فحص جودة الكود
make install      # تثبيت المتطلبات
make env-check    # عرض المتغيرات المطلوبة
```

---

## القيود والمبادئ الأساسية

- ❌ **لا تنفيذ تلقائي داخل حساب FPL** — القراءة والتوصية فقط
- ❌ **لا مفاتيح API مدفوعة** — كل شيء مجاني
- ❌ **لا AI API خارجي** — منطق قواعد (rules-based) بالكامل
- ✅ **كل الأسرار من متغيرات بيئة فقط** — لا توجد بيانات حساسة بالكود
- ✅ **كل التوصيات كـ"اقتراح للمراجعة"** — ليست أوامر نهائية
- ✅ **معالجة الأخطاء الصريحة** — أي فشل يُرسل إشعاراً لتيليجرام

---

## استكشاف الأخطاء

**مشكلة: رسالة خطأ `FPL_TEAM_ID مفقود`**
→ تحقق من ملف `.env` وتأكد من وجود القيمة بدون مسافات

**مشكلة: رسالة خطأ `Unauthorized` من تيليجرام**
→ `TELEGRAM_BOT_TOKEN` خاطئ — تحقق من القيمة الكاملة بما فيها النقطتين `:` والرقم قبلها

**مشكلة: لا توجد نتائج في الجولة 1**
→ طبيعي — قبل بدء الموسم الفعلي، بعض endpoints لا تُرجع بيانات (get_my_team، الترتيب)

**مشكلة: GitHub Actions ينجح لكن لا تصل رسالة**
→ تحقق من `TELEGRAM_CHAT_ID` — تأكد أنك أرسلت رسالة للبوت أولاً قبل استخراج الـ ID

---

*آخر تحديث: 2026-08-18 | الإصدار: 1.0.0*
