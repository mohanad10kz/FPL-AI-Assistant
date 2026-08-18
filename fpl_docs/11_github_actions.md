# 11 - .github/workflows/weekly_run.yml

## الهدف من هذا الملف
تشغيل `main.py` تلقائياً كل أسبوع على سيرفرات GitHub (لا يعتمد على تشغيل جهاز المستخدم إطلاقاً)، مجاناً بالكامل ضمن الحصة المجانية.

## الارتباط بباقي الملفات
يستدعي `src/main.py` فقط، ويمرر له القيم من GitHub Secrets كمتغيرات بيئة (بنفس أسماء المتغيرات الموثقة بملف `01_config.md`).

## خطوات الإعداد

### 1. تسجيل الأسرار بـ GitHub (خطوات يدوية لمرة واحدة، تُشرح بـ README)
Repo Settings → Secrets and variables → Actions → إضافة:
- `FPL_TEAM_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 2. محتوى ملف الـ workflow (البنية المطلوبة)
```yaml
name: FPL Weekly Report

on:
  schedule:
    - cron: "0 18 * * 5"   # كل جمعة الساعة 18:00 UTC — يُعدَّل حسب توقيت الديدلاين الفعلي بكل جولة
  workflow_dispatch:        # يسمح بتشغيل يدوي من تبويب Actions لأغراض الاختبار

jobs:
  run-fpl-assistant:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run FPL assistant
        env:
          FPL_TEAM_ID: ${{ secrets.FPL_TEAM_ID }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python src/main.py

      - name: Commit updated state files
        run: |
          git config user.name "fpl-bot"
          git config user.email "actions@github.com"
          git add data/state/ data/history/
          git commit -m "Update state after GW run" || echo "No changes to commit"
          git push
```

## ⚠️ ملاحظة تقنية مهمة يجب أن ينتبه لها الـ AI agent
خطوة "Commit updated state files" **ضرورية** لأن `transfer_planner.py` يعتمد على ملف حالة دائم (`data/state/transfer_queue.json`) — بيئة GitHub Actions مؤقتة (تُمحى بعد كل تشغيل)، فلازم أي تعديل على ملفات الحالة يُحفظ (commit + push) للـ repo نفسه، وإلا سيُفقد "الطابور المؤجل" بين كل تشغيل وآخر ويتعطل كل منطق التخطيط متعدد الجولات.

## توقيت الجدولة (Cron)
ديدلاين FPL يتغيّر بالتوقيت أسبوعياً (عادة الجمعة أو السبت). **لا تعتمد على قيمة cron ثابتة بشكل أعمى** — الأصح جلب `deadline_time` من `bootstrap-static → events` والتأكد أن وقت التشغيل المجدول دائماً **قبل** الديدلاين بساعات كافية (4-6 ساعات على الأقل)، وضبط الـ cron يدوياً إذا لاحظ المستخدم انحرافاً بالتوقيت بأي أسبوع.

## معايير القبول
- [ ] تشغيل يدوي عبر `workflow_dispatch` ينجح ويصل تقرير فعلي لتيليجرام.
- [ ] ملفات الحالة (`data/state/`) تُحدَّث فعلياً بالـ repo بعد كل تشغيل (تحقق بفتح الملف بعد commit).
- [ ] التشغيل المجدول (cron) يحدث فعلاً قبل ديدلاين الجولة بوقت كافٍ.
