"""
differential_finder.py — مسح استباقي للاعبي الدوري لاكتشاف الـ Differentials.

يكتشف لاعبين بسعر معقول، فورم جيد، مباريات قادمة سهلة، ونسبة امتلاك منخفضة/متوسطة.
تُعرض النتائج كاقتراحات اختيارية للمتابعة بالتقرير النهائي.

⚠️ هذا القسم معلوماتي واختياري بالكامل:
- لا يفرض أي قرار تحويل إجباري.
- لا يمرر أي لاعب لـ transfer_planner.py.
- لا يستهلك أي رصيد من التحويلات المجانية.
"""

import logging
from typing import Optional

from squad_optimizer import _normalize

logger = logging.getLogger(__name__)

# ─── ثوابت الفلاتر والحدود (قابلة للتعديل) ──────────────────────────────────
MIN_OWNERSHIP = 2.0           # الحد الأدنى لنسبة الامتلاك (%)
MAX_OWNERSHIP = 15.0          # الحد الأقصى لنسبة الامتلاك (%)
PRICE_TOLERANCE_FACTOR = 1.10 # +10% فوق متوسط سعر لاعبي نفس المركز
HIGH_CONSENSUS_THRESHOLD = 0.70 # استبعاد من تكراره >= 70% بإجماع أفضل N
MAX_PER_POSITION = 5          # الحد الأقصى للاعبين لكل مركز قبل التصفية النهائية
MAX_TOTAL_RESULTS = 5         # الحد الأقصى للاعبين بالتقرير النهائي

# ─── أوزان الدرجة المركّبة (مجموعها = 1.0) ──────────────────────────────────
WEIGHT_FORM = 0.35            # الفورم
WEIGHT_FIXTURE = 0.35         # سهولة أول 3-5 مباريات قادمة (FDR معكوس)
WEIGHT_VALUE = 0.20           # القيمة مقابل السعر (الفورم / السعر)
WEIGHT_RARITY = 0.10          # ندرة الامتلاك (فرصة تفوق مبكرة)

# ─── تعيين أسماء المراكز ───────────────────────────────────────────────────
POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _calculate_team_fdr_avg(
    team_id: int,
    fixtures_data: Optional[list[dict]],
    current_gw: int,
    n_matches: int = 5,
) -> float:
    """
    يحسب متوسط صعوبة المباريات (FDR) لفريق معين على مدى أول 3-5 جولات قادمة.

    Args:
        team_id: معرّف الفريق (النادي)
        fixtures_data: قائمة كل مباريات الموسم من fpl_client.get_fixtures()
        current_gw: الجولة القادمة/الحالية
        n_matches: عدد المباريات القادمة المطلوب تقييمها (افتراضي 5)

    Returns:
        متوسط FDR (من 1 أسهل إلى 5 أصعب)، أو 3.0 (محايد) لو لم تتوفر بيانات.
    """
    if not fixtures_data:
        return 3.0

    upcoming = []
    for fix in fixtures_data:
        # فحص المباريات غير المنتهية من الجولة الحالية وما بعدها
        event = fix.get("event")
        if event is None or event < current_gw:
            continue
        if fix.get("finished", False):
            continue

        if fix.get("team_h") == team_id:
            upcoming.append((event, fix.get("team_h_difficulty", 3)))
        elif fix.get("team_a") == team_id:
            upcoming.append((event, fix.get("team_a_difficulty", 3)))

    if not upcoming:
        return 3.0

    # ترتيب زمني حسب الجولة واختيار أول n_matches
    upcoming.sort(key=lambda x: x[0])
    selected = upcoming[:n_matches]
    difficulties = [diff for _, diff in selected]
    return sum(difficulties) / len(difficulties)


def filter_candidates(
    all_players: list[dict],
    my_squad_ids: set[int],
    consensus_data: Optional[dict[int, int]] = None,
    top_n_total: int = 0,
    injury_statuses: Optional[dict[int, dict]] = None,
) -> list[dict]:
    """
    يطبّق الفلاتر الستة المتسلسلة لاستبعاد غير المؤهلين وفق وثيقة 12_differential_finder.md.

    Args:
        all_players: قائمة عناصر bootstrap-static['elements']
        my_squad_ids: مجموعة معرفات لاعبي تشكيلتي الحالية
        consensus_data: قاموس إجماع أفضل N {player_id: count}
        top_n_total: إجمالي عدد مدراء الإجماع المحللين
        injury_statuses: قاموس حالات الإصابة من injuries_source

    Returns:
        قائمة اللاعبين المجتازين لجميع الفلاتر
    """
    if not all_players:
        return []

    # حساب متوسط السعر والفورم لكل مركز عبر كل لاعبي الدوري
    pos_prices: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    pos_forms: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}

    for p in all_players:
        pos = p.get("element_type", 0)
        if pos in pos_prices:
            price = p.get("now_cost", 0) / 10.0
            pos_prices[pos].append(price)
            try:
                form = float(p.get("form") or 0.0)
            except (ValueError, TypeError):
                form = 0.0
            pos_forms[pos].append(form)

    avg_prices = {
        pos: (sum(vals) / len(vals)) if vals else 5.0
        for pos, vals in pos_prices.items()
    }
    avg_forms = {
        pos: (sum(vals) / len(vals)) if vals else 0.0
        for pos, vals in pos_forms.items()
    }

    high_consensus_count = round(top_n_total * HIGH_CONSENSUS_THRESHOLD) if top_n_total > 0 else 999

    filtered = []
    for p in all_players:
        pid = p.get("id")
        if pid is None:
            continue

        # 1. استبعاد لاعبي تشكيلتي الحالية
        if pid in my_squad_ids:
            continue

        # 2. استبعاد تكرار الإجماع العالي (>= 70%)
        if consensus_data and top_n_total > 0:
            count = consensus_data.get(pid, 0)
            if count >= high_consensus_count:
                continue

        # 3. فلتر نسبة الامتلاك (2% - 15%)
        try:
            ownership = float(p.get("selected_by_percent") or 0.0)
        except (ValueError, TypeError):
            ownership = 0.0
        if not (MIN_OWNERSHIP <= ownership <= MAX_OWNERSHIP):
            continue

        # 4. فلتر السعر (<= متوسط سعر المركز + 10%)
        pos = p.get("element_type", 0)
        price = p.get("now_cost", 0) / 10.0
        max_allowed_price = avg_prices.get(pos, 5.0) * PRICE_TOLERANCE_FACTOR
        if price > max_allowed_price:
            continue

        # 5. فلتر الفورم (> متوسط فورم المركز)
        try:
            form = float(p.get("form") or 0.0)
        except (ValueError, TypeError):
            form = 0.0
        if form <= avg_forms.get(pos, 0.0):
            continue

        # 6. فلتر الإصابة (سليم "fit" فقط)
        if injury_statuses and pid in injury_statuses:
            if injury_statuses[pid].get("status") != "fit":
                continue
        else:
            raw_status = p.get("status", "a")
            chance = p.get("chance_of_playing_next_round")
            if raw_status != "a" or (chance is not None and chance < 100):
                continue

        filtered.append(p)

    logger.info(
        "فلترة Differentials: %d لاعب مؤهل من أصل %d لاعب",
        len(filtered), len(all_players)
    )
    return filtered


def score_and_rank(
    filtered_players: list[dict],
    fixtures_data: Optional[list[dict]] = None,
    current_gw: int = 1,
) -> list[dict]:
    """
    يحسب الدرجة المركّبة ويرتب اللاعبين لاختيار أفضل 5 إجمالاً.

    Args:
        filtered_players: اللاعبون المجتازون للفلاتر
        fixtures_data: جدول مباريات الموسم
        current_gw: رقم الجولة القادمة

    Returns:
        قائمة بأفضل المرشحين (بحد أقصى 5) مرتبة تنازلياً مع درجاتهم.
    """
    if not filtered_players:
        return []

    # استخراج المقاييس الخام
    forms: list[float] = []
    fdrs: list[float] = []
    values: list[float] = []
    ownerships: list[float] = []

    for p in filtered_players:
        try:
            frm = float(p.get("form") or 0.0)
        except (ValueError, TypeError):
            frm = 0.0
        forms.append(frm)

        team_id = p.get("team", 0)
        fdr = _calculate_team_fdr_avg(team_id, fixtures_data, current_gw, n_matches=5)
        fdrs.append(fdr)

        price = max(p.get("now_cost", 50) / 10.0, 0.1)
        values.append(frm / price)

        try:
            own = float(p.get("selected_by_percent") or 0.0)
        except (ValueError, TypeError):
            own = 0.0
        ownerships.append(own)

    # تطبيع القيم (0 - 1)
    norm_form = _normalize(forms)
    # سهولة المباريات: FDR أصغر = أسهل → نعكسه
    raw_fix_ease = [6.0 - f for f in fdrs]
    norm_fix = _normalize(raw_fix_ease)
    norm_val = _normalize(values)
    # ندرة الامتلاك: امتلاك أقل = ميزة تفوق أكبر → نعكسه
    raw_rarity = [MAX_OWNERSHIP - o for o in ownerships]
    norm_rarity = _normalize(raw_rarity)

    scored_players = []
    for i, p in enumerate(filtered_players):
        composite_score = (
            WEIGHT_FORM * norm_form[i]
            + WEIGHT_FIXTURE * norm_fix[i]
            + WEIGHT_VALUE * norm_val[i]
            + WEIGHT_RARITY * norm_rarity[i]
        )
        scored_p = dict(p)
        scored_p["_score"] = composite_score
        scored_p["_fdr_avg"] = fdrs[i]
        scored_players.append(scored_p)

    # تجميع حسب المركز واختيار أفضل 5 لكل مركز
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for sp in scored_players:
        pos = sp.get("element_type", 0)
        if pos in by_pos:
            by_pos[pos].append(sp)

    survivors: list[dict] = []
    for pos, players_in_pos in by_pos.items():
        players_in_pos.sort(key=lambda x: x["_score"], reverse=True)
        survivors.extend(players_in_pos[:MAX_PER_POSITION])

    # الترتيب النهائي لجميع الناجين واقتطاع أفضل 5 إجمالاً
    survivors.sort(key=lambda x: x["_score"], reverse=True)
    top_results = survivors[:MAX_TOTAL_RESULTS]

    logger.info(
        "تم ترتيب الـ Differentials: اختيار أفضل %d مرشح إجمالاً",
        len(top_results)
    )
    return top_results


def _generate_reason(player: dict, fdr_avg: float) -> str:
    """يولد نصاً توضيحياً لسبب التوصية بهذا اللاعب."""
    try:
        form = float(player.get("form") or 0.0)
    except (ValueError, TypeError):
        form = 0.0
    try:
        own = float(player.get("selected_by_percent") or 0.0)
    except (ValueError, TypeError):
        own = 0.0

    reasons = []
    if form >= 5.0:
        reasons.append(f"فورم ممتاز ({form:.1f})")
    elif form > 0:
        reasons.append(f"فورم تصاعدي ({form:.1f})")

    if fdr_avg <= 2.6:
        reasons.append("مباريات قادمة سهلة جداً")
    elif fdr_avg <= 3.2:
        reasons.append("جدول مباريات واعد")

    if own <= 6.0:
        reasons.append(f"امتلاك منخفض جداً ({own:.1f}%)")
    else:
        reasons.append(f"امتلاك تفاضلي ({own:.1f}%)")

    if not reasons:
        return "فورم جيد + مباريات سهلة + امتلاك منخفض نسبياً"
    return " + ".join(reasons)


def build_differential_section(top_candidates: list[dict]) -> dict:
    """
    يبني كائن الاقتراحات المنسّق وفق وثيقة 12_differential_finder.md.

    Args:
        top_candidates: قائمة أفضل المرشحين من score_and_rank()

    Returns:
        dict: {"differential_suggestions": [...]}
    """
    suggestions = []
    for p in top_candidates:
        pos_id = p.get("element_type", 0)
        pos_str = POSITION_NAMES.get(pos_id, "MID")
        price = round(p.get("now_cost", 0) / 10.0, 1)

        try:
            own = float(p.get("selected_by_percent") or 0.0)
        except (ValueError, TypeError):
            own = 0.0

        try:
            form = float(p.get("form") or 0.0)
        except (ValueError, TypeError):
            form = 0.0

        fdr_avg = p.get("_fdr_avg", 3.0)
        if fdr_avg <= 2.6:
            fdr_label = "سهلة"
        elif fdr_avg <= 3.4:
            fdr_label = "متوسطة"
        else:
            fdr_label = "صعبة"

        reason = _generate_reason(p, fdr_avg)

        suggestions.append({
            "id": p.get("id"),
            "name": p.get("web_name", "?"),
            "position": pos_str,
            "price": price,
            "ownership": own,
            "form": form,
            "next_fixtures_difficulty": fdr_label,
            "reason": reason,
        })

    return {"differential_suggestions": suggestions}


def find_differentials(
    all_players: list[dict],
    my_squad_ids: set[int],
    consensus_data: Optional[dict[int, int]] = None,
    top_n_total: int = 0,
    injury_statuses: Optional[dict[int, dict]] = None,
    fixtures_data: Optional[list[dict]] = None,
    current_gw: int = 1,
) -> list[dict]:
    """
    نقطة الدخول الرئيسية للبحث عن الـ Differentials.

    Args:
        all_players: قائمة عناصر bootstrap-static['elements']
        my_squad_ids: مجموعة معرفات لاعبي تشكيلتي
        consensus_data: بيانات إجماع أفضل N
        top_n_total: عدد مدراء الإجماع
        injury_statuses: بيانات الإصابات
        fixtures_data: جدول المباريات
        current_gw: رقم الجولة

    Returns:
        قائمة الاقتراحات المنسقة (differential_suggestions)
    """
    logger.info("🔍 بدء المسح الاستباقي لاكتشاف الـ Differentials...")
    filtered = filter_candidates(
        all_players=all_players,
        my_squad_ids=my_squad_ids,
        consensus_data=consensus_data,
        top_n_total=top_n_total,
        injury_statuses=injury_statuses,
    )

    ranked = score_and_rank(
        filtered_players=filtered,
        fixtures_data=fixtures_data,
        current_gw=current_gw,
    )

    section = build_differential_section(ranked)
    suggestions = section.get("differential_suggestions", [])
    logger.info("✅ اكتمل مسح Differentials: تم ترشيح %d لاعب", len(suggestions))
    return suggestions
