# 10 - main.py

## الهدف من هذا الملف
نقطة التشغيل الوحيدة للمشروع بالكامل — ينسّق استدعاء كل الوحدات بالترتيب الصحيح، ويتعامل مع أي حالة استثنائية بمستوى عالٍ (بداية موسم، نهاية موسم، فشل جزئي بمصدر بيانات).

## الارتباط بباقي الملفات
يستورد **كل** الملفات الأخرى بالمشروع وينسّق تسلسل استدعائها. هو الملف الوحيد الذي "يعرف" الصورة الكاملة — كل ملف آخر يعرف مسؤوليته فقط ولا يعرف عن الباقي.

## خطوات التنفيذ التفصيلية (تسلسل التشغيل الكامل بالضبط)

```
1. تحميل الإعدادات: من config.py — إن فشل (متغير ناقص)، توقف فوراً برسالة خطأ واضحة.

2. جلب بيانات FPL الأساسية:
   bootstrap_data = fpl_client.get_bootstrap_static()
   current_gw = fpl_client.get_current_gameweek(bootstrap_data)

3. تحديد الحالة:
   إذا current_gw is None → الموسم انتهى، أرسل رسالة تيليجرام بسيطة تفيد بذلك وأنهِ التشغيل (لا داعي لتشغيل أي تحليل).
   إذا current_gw == 1 والتشكيلة الأولية لم تُبنَ بعد (تحقق من عدم وجود ملف data/state/initial_squad_built.flag):
       شغّل squad_optimizer.build_initial_squad() فقط.
       أرسل النتيجة كتقرير توصية (وليس تقرير تحويلات عادي — نص مختلف بالكامل، تنسيقه بـ report_builder بقسم منفصل).
       أنشئ الملف initial_squad_built.flag لمنع إعادة التشغيل هذا المسار بالخطأ الجولات القادمة.
       أنهِ التشغيل هنا لهذه الجولة.
   خلاف ذلك (current_gw >= 2، التشكيلة الأولية موجودة):
       تابع للخطوة 4.

4. جلب تشكيلتي الحالية وتاريخ الرقائق:
   my_team = fpl_client.get_my_team(config.FPL_TEAM_ID, current_gw)
   manager_history = fpl_client.get_manager_history(config.FPL_TEAM_ID)

5. جلب حالة الإصابات:
   injury_data = injuries_source.get_injury_status_from_fpl(bootstrap_data)
   (+ المصدر الخارجي إن نجح، بمعالجة فشل صامتة كما هو موثّق بملف 04)

6. جلب بيانات إجماع أفضل N (فقط إذا الجولة الحالية > 1 والجولة السابقة انتهت فعلياً):
   top_manager_ids = top_managers.get_top_n_manager_ids(config.TOP_N_MANAGERS)
   top_squads = top_managers.get_top_n_squads(top_manager_ids, current_gw - 1)
   consensus_data = top_managers.calculate_consensus(top_squads)

7. تشغيل محرك القرار:
   decision = decision_engine.run(my_team, bootstrap_data, injury_data, consensus_data, manager_history)
   (هذه الدالة بداخلها تستدعي transfer_planner.update_transfer_queue تلقائياً كخطوة داخلية — راجع ملف 07)

8. بناء التقرير وإرساله:
   report_text = report_builder.build_report_text(decision)
   telegram_notifier.send_report(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, report_text)

9. أرشفة النتيجة:
   احفظ decision (الكائن الكامل) بملف data/history/gw_{current_gw}.json
```

## معالجة الأخطاء على مستوى `main.py`
- لف كامل التسلسل (الخطوات 4-9) بـ `try/except` عام واحد على مستوى عالٍ. أي خطأ غير متوقع بأي خطوة → أرسل رسالة تيليجرام مختصرة توضح "فشل تشغيل تقرير هذا الأسبوع، السبب: {نوع الخطأ}" بدل فشل صامت كامل بدون أي إشعار للمستخدم. هذا يضمن أن المستخدم **يعرف دائماً** أن هناك مشكلة حتى لو لم يصله التقرير الكامل.

## معايير القبول
- [ ] تشغيل كامل بالجولة 1 يبني تشكيلة أولية فقط ولا يحاول الوصول لـ `get_my_team` (غير متاح بعد).
- [ ] تشغيل كامل بالجولة 2+ يمر بكل الخطوات بالترتيب الصحيح.
- [ ] أي فشل بأي خطوة يُنتج على الأقل رسالة تيليجرام توضح وجود مشكلة (لا فشل صامت كامل أبداً).
- [ ] كل جولة تُنتج ملف أرشيف واحد بـ `data/history/`.
