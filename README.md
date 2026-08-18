# FPL AI Assistant 🤖⚽

> نظام ذكاء اصطناعي (rules-based) يساعدك أسبوعياً في قرارات Fantasy Premier League — بدون تدخل تلقائي بحسابك.

**⚠️ تنويه مهم:** هذا المشروع للتوصية والتحليل فقط. القرار النهائي دائماً لك، والنظام لا يُعدّل حسابك بأي شكل.

---

## ما يفعله هذا المشروع

- يسحب بيانات تشكيلتك من FPL API الرسمي
- يقارن تشكيلتك بأفضل 10 مدراء عالمياً
- يجلب حالات الإصابات المحدّثة
- يقترح التحويلات والكابتن وتوقيت الـ Chips
- يرسل تقريراً مفصلاً عبر Telegram Bot

---

## الإعداد

### 1. متطلبات النظام
- Python 3.11+
- pip

### 2. تثبيت المتطلبات
```bash
pip install -r requirements.txt
# أو
make install
```

### 3. إعداد Telegram Bot (خطوة يدوية لمرة واحدة)

1. افتح تيليجرام وابحث عن `@BotFather`
2. أرسل `/newbot` واتبع التعليمات → ستحصل على `TELEGRAM_BOT_TOKEN`
3. أرسل أي رسالة للبوت الجديد
4. افتح هذا الرابط: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. استخرج `chat_id` من النتيجة

### 4. إعداد متغيرات البيئة
```bash
cp .env.example .env
# ثم عدّل .env بقيمك الحقيقية
```

محتوى ملف `.env`:
```
FPL_TEAM_ID=رقم_فريقك
TELEGRAM_BOT_TOKEN=توكن_البوت
TELEGRAM_CHAT_ID=معرف_المحادثة
INJURY_SOURCE_URL=https://example.com/injuries
TOP_N_MANAGERS=10
```

### 5. تشغيل محلي للاختبار
```bash
make run
# أو
python src/main.py
```

---

## GitHub Actions (التشغيل التلقائي الأسبوعي)

أضف هذه الأسرار إلى GitHub Secrets:
- `FPL_TEAM_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

الجدولة: كل جمعة الساعة 18:00 UTC (قابلة للتعديل في `.github/workflows/weekly_run.yml`).

يمكنك التشغيل اليدوي من: **Actions → weekly_run → Run workflow**

---

## هيكل المشروع

```
src/
├── config.py          # قراءة الإعدادات من البيئة
├── fpl_client.py      # اتصالات FPL API
├── squad_optimizer.py # بناء تشكيلة الجولة الأولى (PuLP)
├── injuries_source.py # بيانات الإصابات
├── top_managers.py    # أفضل 10 مدراء عالمياً
├── transfer_planner.py# طابور التحويلات متعدد الجولات
├── decision_engine.py # محرك القرار المركزي
├── report_builder.py  # بناء نص التقرير العربي
├── telegram_notifier.py# إرسال التقرير
└── main.py            # نقطة التشغيل الرئيسية
```

---

## Tech Stack

| المكوّن | الأداة |
|---|---|
| اللغة | Python 3.11+ |
| سحب FPL | requests + FPL API (مجاني، بدون مفتاح) |
| سحب الإصابات | requests + BeautifulSoup4 |
| تحسين التشكيلة | PuLP (Linear Programming) |
| الإشعارات | Telegram Bot API |
| الجدولة | GitHub Actions |
| الأسرار | GitHub Secrets |

---

## القيود والمبادئ

- ❌ لا تنفيذ تلقائي داخل حساب FPL
- ❌ لا مفاتيح API مدفوعة
- ❌ لا AI API خارجي (كل المنطق rules-based)
- ✅ كل الأسرار تُقرأ من متغيرات بيئة فقط
- ✅ التقرير يُعرض كـ"اقتراح للمراجعة" دائماً
