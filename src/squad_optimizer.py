"""
squad_optimizer.py — بناء أفضل تشكيلة ممكنة قبل بداية الموسم (الجولة الأولى).

يُستخدم مرة واحدة فقط: حين لا تتوفر بيانات أفضل 10 عالمياً بعد.
البديل: نسب الامتلاك قبل الموسم + أداء الموسم الماضي + سهولة المباريات + القيمة/السعر.

الأوزان قابلة للتعديل من الثوابت أدناه دون لمس منطق الحساب.
"""

import logging
from typing import Optional
import pulp

logger = logging.getLogger(__name__)

# ─── أوزان الدرجة المركّبة (قابلة للتعديل) ─────────────────────────────────
# مجموعها يجب أن يساوي 1.0
WEIGHT_OWNERSHIP = 0.35    # نسبة الامتلاك قبل الموسم (selected_by_percent)
WEIGHT_FORM = 0.30         # الأداء (points_per_game أو total_points مُطبَّع)
WEIGHT_FIXTURE = 0.20      # سهولة أول 5 مباريات (fixture difficulty — معكوسة)
WEIGHT_VALUE = 0.15        # القيمة مقابل السعر (points_per_game / now_cost)

# ─── قيود المسألة (من قواعد اللعبة 00_GAME_RULES.md) ───────────────────────
BUDGET_LIMIT = 100.0       # مليون جنيه
SQUAD_SIZE = 15
MAX_PER_CLUB = 3
POSITION_COUNTS = {1: 2, 2: 5, 3: 5, 4: 3}  # GK=1, DEF=2, MID=3, FWD=4

# التشكيلات الأساسية المسموحة: (n_DEF, n_MID, n_FWD) — دائماً 1 GK
VALID_FORMATIONS = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 4, 2),
    (4, 3, 3),
    (5, 3, 2),
    (5, 4, 1),
    (4, 5, 1),
]


def _normalize(values: list[float]) -> list[float]:
    """يُطبَّع قائمة أرقام بين 0 و1 (Min-Max Normalization)."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)  # كل القيم متساوية → منتصف السلم
    return [(v - mn) / (mx - mn) for v in values]


def _compute_scores(players: list[dict]) -> list[float]:
    """
    يحسب الدرجة المركّبة لكل لاعب بناءً على الأوزان المعرّفة بالثوابت.

    Args:
        players: قائمة قواميس اللاعبين من bootstrap-static

    Returns:
        قائمة درجات بنفس الترتيب
    """
    # ── استخراج القيم الخام ──────────────────────────────────────────────────
    ownerships = [float(p.get("selected_by_percent") or 0) for p in players]
    # points_per_game أو total_points مُبسَّط (÷ عدد المباريات — تقريبياً)
    forms = [float(p.get("points_per_game") or 0) for p in players]
    # fixture_difficulty يُوفَّر خارجياً كحقل إضافي إن وجد، وإلا 0.5 محايد
    fixtures = [float(p.get("fixture_difficulty_avg") or 5) for p in players]
    # القيمة = نقاط_للمباراة / سعر (السعر بالمليون = now_cost/10)
    prices = [p.get("now_cost", 60) / 10 for p in players]
    values = [
        f / max(c, 0.1)
        for f, c in zip(forms, prices)
    ]

    # ── تطبيع كل عنصر بين 0 و1 ──────────────────────────────────────────────
    norm_own = _normalize(ownerships)
    norm_form = _normalize(forms)
    # الصعوبة أسهل = رقم أصغر = درجة أعلى → نعكسها بعد التطبيع
    raw_fix = [6 - f for f in fixtures]   # عكس الصعوبة (1=صعب → 5، 5=سهل → 1... → نعكس)
    norm_fix = _normalize(raw_fix)
    norm_val = _normalize(values)

    # ── الدرجة المركّبة ───────────────────────────────────────────────────────
    scores = [
        WEIGHT_OWNERSHIP * own
        + WEIGHT_FORM * frm
        + WEIGHT_FIXTURE * fix
        + WEIGHT_VALUE * val
        for own, frm, fix, val in zip(norm_own, norm_form, norm_fix, norm_val)
    ]
    return scores


def _select_starting_xi(squad_15: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    يختار أفضل 11 لاعب أساسي من الـ15 ضمن التشكيلات المسموحة.

    Returns:
        (starting_xi, bench) — قوائم بنفس بنية اللاعبين
    """
    best_xi = None
    best_score = -1.0
    best_bench = None

    for def_n, mid_n, fwd_n in VALID_FORMATIONS:
        gk_pool = [p for p in squad_15 if p["element_type"] == 1]
        def_pool = [p for p in squad_15 if p["element_type"] == 2]
        mid_pool = [p for p in squad_15 if p["element_type"] == 3]
        fwd_pool = [p for p in squad_15 if p["element_type"] == 4]

        # تحقق من توفر عدد كافٍ لكل مركز
        if len(gk_pool) < 1 or len(def_pool) < def_n or \
           len(mid_pool) < mid_n or len(fwd_pool) < fwd_n:
            continue

        # اختر الأعلى درجة من كل مركز
        gk_starters = sorted(gk_pool, key=lambda x: x["_score"], reverse=True)[:1]
        def_starters = sorted(def_pool, key=lambda x: x["_score"], reverse=True)[:def_n]
        mid_starters = sorted(mid_pool, key=lambda x: x["_score"], reverse=True)[:mid_n]
        fwd_starters = sorted(fwd_pool, key=lambda x: x["_score"], reverse=True)[:fwd_n]

        xi = gk_starters + def_starters + mid_starters + fwd_starters
        total_score = sum(p["_score"] for p in xi)

        if total_score > best_score:
            best_score = total_score
            best_xi = xi
            best_bench = [p for p in squad_15 if p not in xi]

    if best_xi is None:
        # fallback: أفضل 11 بالدرجة مباشرة (بدون فلترة تشكيلة)
        sorted_squad = sorted(squad_15, key=lambda x: x["_score"], reverse=True)
        best_xi = sorted_squad[:11]
        best_bench = sorted_squad[11:]

    return best_xi, best_bench


def build_initial_squad(
    players_data: list[dict],
    budget: float = BUDGET_LIMIT,
) -> dict:
    """
    يبني أفضل تشكيلة ممكنة (15 لاعب) ضمن قيود FPL باستخدام Linear Programming (PuLP).

    يُستخدم مرة واحدة فقط قبل الجولة 1. بداية من الجولة 2،
    يستخدم decision_engine.py + top_managers.py بدلاً منه.

    Args:
        players_data: قائمة اللاعبين من get_bootstrap_static()['elements']
        budget: الميزانية الإجمالية (افتراضي 100.0 مليون)

    Returns:
        dict يحوي:
            - 'squad': قائمة الـ15 لاعب المختار
            - 'starting_xi': أفضل 11 أساسي
            - 'bench': الـ4 بدلاء بالترتيب
            - 'captain': اسم الكابتن
            - 'vice_captain': اسم نائب الكابتن
            - 'total_cost': التكلفة الإجمالية
            - 'budget_remaining': الرصيد المتبقي
            - 'solver_status': حالة الحل (Optimal/Infeasible/...)
    """
    logger.info("بدء بناء التشكيلة الأولى — عدد اللاعبين المتاحين: %d", len(players_data))

    # ── فلترة اللاعبين غير المؤهلين (سعر 0 أو بيانات ناقصة) ────────────────
    players = [
        p for p in players_data
        if p.get("now_cost", 0) > 0 and p.get("element_type") in (1, 2, 3, 4)
    ]
    logger.info("لاعبون مؤهلون بعد الفلترة: %d", len(players))

    # ── حساب الدرجات ─────────────────────────────────────────────────────────
    scores = _compute_scores(players)
    for p, s in zip(players, scores):
        p["_score"] = s

    # ── إعداد مسألة PuLP ─────────────────────────────────────────────────────
    prob = pulp.LpProblem("FPL_Squad_Selection", pulp.LpMaximize)

    # متغير ثنائي لكل لاعب: 1 = مختار، 0 = غير مختار
    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(len(players))]

    # ── دالة الهدف: تعظيم مجموع الدرجات ─────────────────────────────────────
    prob += pulp.lpSum(scores[i] * x[i] for i in range(len(players)))

    # ── القيود ───────────────────────────────────────────────────────────────
    # 1. الميزانية (now_cost ÷ 10 = القيمة بالمليون)
    prob += pulp.lpSum(
        (players[i]["now_cost"] / 10) * x[i] for i in range(len(players))
    ) <= budget, "budget"

    # 2. حجم التشكيلة: 15 لاعب بالضبط
    prob += pulp.lpSum(x) == SQUAD_SIZE, "squad_size"

    # 3. توزيع المراكز (element_type: 1=GK, 2=DEF, 3=MID, 4=FWD)
    for pos_type, count in POSITION_COUNTS.items():
        prob += pulp.lpSum(
            x[i] for i in range(len(players))
            if players[i]["element_type"] == pos_type
        ) == count, f"position_{pos_type}"

    # 4. حد أقصى 3 لاعبين من نفس النادي
    team_ids = set(p["team"] for p in players)
    for team_id in team_ids:
        prob += pulp.lpSum(
            x[i] for i in range(len(players))
            if players[i]["team"] == team_id
        ) <= MAX_PER_CLUB, f"club_limit_{team_id}"

    # ── حل المسألة ──────────────────────────────────────────────────────────
    logger.info("حل مسألة Linear Programming (PuLP)...")
    # PULP_CBC_CMD هو الحل الافتراضي (مفتوح المصدر، لا يحتاج ترخيص)
    solver = pulp.PULP_CBC_CMD(msg=0)  # msg=0 لإخفاء output المُحلّ
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    logger.info("حالة الحل: %s", status)

    if prob.status != pulp.LpStatusOptimal:
        logger.error("فشل الحل: %s — تحقق من القيود والبيانات", status)
        return {
            "squad": [],
            "starting_xi": [],
            "bench": [],
            "captain": None,
            "vice_captain": None,
            "total_cost": 0.0,
            "budget_remaining": budget,
            "solver_status": status,
        }

    # ── استخراج التشكيلة المختارة ────────────────────────────────────────────
    squad = [
        players[i] for i in range(len(players))
        if pulp.value(x[i]) == 1
    ]
    total_cost = sum(p["now_cost"] / 10 for p in squad)
    budget_remaining = budget - total_cost

    logger.info(
        "التشكيلة المختارة: %d لاعب | التكلفة: %.1fM | المتبقي: %.1fM",
        len(squad), total_cost, budget_remaining
    )

    # ── اختيار التشكيلة الأساسية والبدلاء ───────────────────────────────────
    starting_xi, bench = _select_starting_xi(squad)

    # ── اختيار الكابتن ونائبه (أعلى لاعبَين درجة بالتشكيلة الأساسية) ────────
    xi_sorted = sorted(starting_xi, key=lambda p: p["_score"], reverse=True)
    captain = xi_sorted[0]["web_name"] if len(xi_sorted) >= 1 else None
    vice_captain = xi_sorted[1]["web_name"] if len(xi_sorted) >= 2 else None

    logger.info("الكابتن: %s | النائب: %s", captain, vice_captain)

    return {
        "squad": squad,
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "total_cost": round(total_cost, 1),
        "budget_remaining": round(budget_remaining, 1),
        "solver_status": status,
    }
