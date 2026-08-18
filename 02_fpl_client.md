# 02 - fpl_client.py

## الهدف من هذا الملف
الوسيط الوحيد بين المشروع وFPL API الرسمي. **أي ملف آخر يحتاج بيانات من FPL يستدعي دوال من هنا فقط — ممنوع أي ملف آخر يسوي HTTP request مباشر لـ FPL API.** هذا يعني لو تغيّر شكل الـ API مستقبلاً، الإصلاح بمكان واحد فقط.

## الارتباط بباقي الملفات
- `squad_optimizer.py` يستخدمه لجلب بيانات كل اللاعبين (`get_bootstrap_static`).
- `top_managers.py` يستخدمه لجلب تشكيلات المدراء الآخرين (`get_my_team` بمعرّف مختلف).
- `decision_engine.py` يستخدمه لجلب تشكيلتي الحالية وتاريخ الرقائق المستخدمة.
- `main.py` ينسّق استدعاءاته بالترتيب الصحيح.

## نقاط النهاية (Endpoints) المطلوبة بالتفصيل

### 1. `get_bootstrap_static()`
```
GET https://fantasy.premierleague.com/api/bootstrap-static/
```
يُرجع كائن ضخم يحوي:
- `elements`: قائمة كل اللاعبين (id, web_name, team, element_type, now_cost, form, selected_by_percent, chance_of_playing_next_round, total_points, ep_next...).
- `teams`: قائمة الأندية (id, name, strength...).
- `events`: قائمة الجولات (id, deadline_time, is_current, is_next, finished...).

**استخدام مهم:** هذه الدالة تُستدعى مرة واحدة أول كل تشغيل ويُعاد استخدام نتيجتها بباقي الدوال (لا تكرر الطلب لنفس البيانات — خزّنها بمتغير واحد ومرّرها).

### 2. `get_current_gameweek(bootstrap_data)`
منطق الاستخراج: ابحث بقائمة `events` عن العنصر اللي `is_next == true` (الجولة القادمة، اللي راح نخطط لها). لو كل الجولات منتهية (نهاية الموسم)، أرجع `None` وتعامل مع هذه الحالة بـ `main.py` (أرسل رسالة "الموسم انتهى" بدل تشغيل التحليل).

### 3. `get_my_team(team_id, gameweek)`
```
GET https://fantasy.premierleague.com/api/entry/{team_id}/event/{gameweek}/picks/
```
يُرجع:
- `picks`: قائمة الـ15 لاعب (element id + position بالتشكيلة + is_captain + is_vice_captain).
- `entry_history`: يحوي `bank` (الرصيد المتبقي)، `event_transfers` (تحويلات هذه الجولة)، `points`.

**ملاحظة حرجة:** هذا الـ endpoint **يعمل فقط بعد بدء الجولة الأولى فعلياً**. قبل الجولة 1 (فترة ما قبل الموسم)، لا توجد تشكيلة محفوظة بعد — هنا يُستخدم `squad_optimizer.py` بدلاً منه (راجع ملف 03).

### 4. `get_manager_history(team_id)`
```
GET https://fantasy.premierleague.com/api/entry/{team_id}/history/
```
يُرجع `chips`: قائمة بكل رقاقة استُخدمت مسبقاً هذا الموسم (الاسم + رقم الجولة). **ضروري لـ `decision_engine.py`** حتى لا يقترح رقاقة مستخدمة أصلاً (خطأ فادح لو حصل).

### 5. `get_league_standings(league_id=314, page=1)`
```
GET https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standings={page}
```
`314` هو معرّف الدوري العام العالمي (Overall). يُرجع قائمة مرتبة بأفضل المدراء عالمياً مع `entry` (وهو نفسه team_id نستخدمه لاحقاً بـ `get_my_team`). **يُستخدم فقط من `top_managers.py`.**

## معالجة الأخطاء (إلزامي بكل دالة)
- كل طلب HTTP يجب أن يكون داخل `try/except` مع `timeout` محدد (مثال: 10 ثواني) — FPL API أحياناً يبطئ أو يقع وقت الذروة (قبل الديدلاين مباشرة بالذات).
- عند الفشل: أعد المحاولة مرة واحدة تلقائياً (retry) قبل رفع الخطأ نهائياً، ولا تدع البرنامج يتوقف بصمت — سجّل الخطأ بوضوح ليصل لـ `main.py` ويُقرر هل يوقف التشغيل أو يكمل بجزء ناقص.

## معايير القبول
- [ ] `get_bootstrap_static()` يُرجع بيانات كل اللاعبين والفرق والجولات بنجاح.
- [ ] `get_current_gameweek()` يحدد الجولة الصحيحة (تحقق يدوياً بمقارنة الناتج بموقع FPL الرسمي).
- [ ] `get_my_team()` يعمل بشكل صحيح بعد بدء الجولة 1 (اختبره بـ team_id حقيقي).
- [ ] `get_manager_history()` يُظهر أي رقائق استُخدمت فعلياً (اختبر بحساب استخدم رقاقة سابقاً إن أمكن).
- [ ] كل الدوال تتعامل مع فشل الاتصال بدون كراش كامل للبرنامج.
