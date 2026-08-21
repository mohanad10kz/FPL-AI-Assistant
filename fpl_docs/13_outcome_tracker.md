# 13 - outcome_tracker.py (المرحلة 1: جمع بيانات للتعلّم المستقبلي)

## الهدف من هذا الملف
بعد انتهاء كل جولة فعلياً، يسجّل **النتيجة الحقيقية** لكل توصية سابقة (كم نقطة حقق اللاعب المقترَح مقابل اللاعب المستبعَد، هل الكابتن المقترح كان فعلاً الأفضل، هل لاعبين differential المقترحين كانوا مفيدين). هذا الملف **لا يغيّر أي قرار حالي** — فقط يبني أرشيف بيانات موثوق سيُستخدم لاحقاً بـ `learning_engine.py` (المرحلة 2، تُبنى بعد تجميع 8-10 جولات على الأقل).

## الارتباط بباقي الملفات
- يُستدعى من `main.py` كخطوة **إضافية بأول كل تشغيل** (قبل أي تحليل جديد)، لأنه يعالج بيانات **الجولة الماضية** لا الحالية.
- يقرأ الملفات المؤرشفة سابقاً من `data/history/{team_id}/gw_{n}.json` (نفس الملفات اللي ينتجها `main.py` أصلاً حالياً — لا حاجة لتغيير بنيتها، فقط قراءة إضافية).
- يستخدم `fpl_client.py` — يحتاج دالة جديدة (`get_player_gameweek_points`) تُضاف هناك.
- يكتب ملف نتائج جديد منفصل: `data/history/{team_id}/outcomes_gw_{n}.json`.
- **لا يُستدعى من `decision_engine.py` ولا يؤثر عليه إطلاقاً بهذه المرحلة** — الفصل الكامل هنا مقصود ومهم.

## دالة جديدة مطلوبة بـ `fpl_client.py`

### `get_player_gameweek_points(player_id, gameweek)`
```
GET https://fantasy.premierleague.com/api/element-summary/{player_id}/
```
يُرجع كائن فيه `history`: قائمة بأداء اللاعب بكل جولة لعبها فعلياً هذا الموسم (`total_points` لكل جولة). ابحث عن العنصر اللي `round == gameweek` واستخرج `total_points` منه. لو اللاعب لم يلعب تلك الجولة (0 دقيقة)، أرجع 0 صراحة (لا `None`).

## خطوات التنفيذ التفصيلية

### 1. `detect_pending_evaluation(team_id, bootstrap_data)`
- افحص كل الجولات بـ `bootstrap-static → events` اللي `finished == true`.
- لكل جولة منتهية، تحقق: هل يوجد ملف `data/history/{team_id}/gw_{n}.json` (توصية سُجّلت) **و** لا يوجد بعد `outcomes_gw_{n}.json` (لم تُقيَّم)؟
- أرجع قائمة أرقام الجولات المنتظرة تقييماً (عادة جولة واحدة فقط بكل تشغيل، لكن الدالة تدعم أكثر من جولة تحسباً لأي انقطاع بالتشغيل).

### 2. `fetch_actual_team(team_id, gameweek)`
استدعِ `fpl_client.get_my_team(team_id, gameweek)` لجلب التشكيلة **الفعلية** اللي لعب بها المستخدم تلك الجولة (بعد أي تعديل يدوي سواه هو بنفسه، بغض النظر هل اتبع التوصية أو لا).

### 3. `evaluate_transfer_recommendation(decision_record, actual_team, gameweek)`
لكل تحويل كان مقترحاً بـ `decision_record["forced_transfers"]`:
- هل اللاعب المقترَح دخوله (`in`) موجود فعلاً بـ `actual_team`؟ → `followed: true/false`.
- اجلب `get_player_gameweek_points()` لكل من اللاعب المقترَح واللاعب المستبعَد.
- احسب الفرق: `points_gained_if_followed = points(in) - points(out)`.

**ملاحظة مهمة:** هذا يحسب **الفائدة الافتراضية** بغض النظر هل المستخدم اتبع التوصية أو لا — وهذا بالضبط ما نحتاجه لاحقاً لتقييم "هل توصياتنا كانت جيدة بالأساس"، بمعزل عن قرار المستخدم الشخصي.

### 4. `evaluate_captain_recommendation(decision_record, actual_team, gameweek)`
- اجلب نقاط الكابتن المقترَح فعلياً تلك الجولة.
- قارنه بأعلى نقاط حققها أي لاعب آخر كان بالتشكيلة (كابتن "مثالي" بأثر رجعي) — احسب الفرق كمقياس "جودة اختيار الكابتن".

### 5. `evaluate_differential_suggestions(decision_record, gameweek)`
(يُفعَّل فقط بعد إتمام ملف 12) لكل لاعب اقتُرح بقسم "يستحق المتابعة"، اجلب نقاطه الفعلية تلك الجولة — يبني قاعدة بيانات لاحقاً لمعرفة هل فلاتر `differential_finder.py` فعلاً تلتقط لاعبين جيدين أو لا.

### 6. `build_outcome_record(...)` وحفظه
يجمع كل نتائج الخطوات 3-5 بكائن واحد ويحفظه بـ `data/history/{team_id}/outcomes_gw_{n}.json`:
```json
{
  "gameweek": 6,
  "transfer_evaluations": [
    {"out": "...", "in": "...", "followed_by_user": true, "points_gained_if_followed": 4}
  ],
  "captain_evaluation": {"suggested": "...", "actual_points": 8, "best_possible_points": 12, "gap": 4},
  "differential_evaluations": [
    {"name": "...", "actual_points": 9}
  ]
}
```

## معايير القبول
- [ ] لا يُعاد تقييم نفس الجولة مرتين (تحقق من وجود ملف `outcomes_gw_{n}.json` قبل أي معالجة).
- [ ] يعمل بشكل مستقل تماماً عن `decision_engine.py` — تعطيله بالكامل لا يكسر أي جزء آخر بالمشروع (اختبار فصل واضح).
- [ ] يتعامل بشكل صحيح مع لاعب لم يلعب أي دقيقة (0 نقطة، لا خطأ).
- [ ] بعد 3-4 جولات تشغيل فعلي، يوجد فعلياً عدة ملفات `outcomes_gw_*.json` متراكمة وقابلة للقراءة.

---

## ملاحظة للمرحلة القادمة (لا تُنفَّذ الآن)
بعد تجميع 8-10 جولات على الأقل من ملفات `outcomes_gw_*.json`، سيُبنى ملف مواصفات منفصل (`14_learning_engine.md`) يستخدم هذه البيانات المتراكمة فعلياً لتعديل أوزان `decision_engine.py` و`squad_optimizer.py` تلقائياً (عبر `scikit-learn`، بدون أي AI API خارجي مدفوع). لا داعي للبدء بهذا الملف قبل توفر بيانات كافية.
