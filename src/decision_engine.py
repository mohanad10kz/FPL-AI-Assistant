"""
decision_engine.py — قلب المشروع.

يجمع مخرجات كل الملفات التحليلية ويحوّلها لتوصية نهائية واحدة متكاملة.
المنطق rules-based بالكامل — لا AI API خارجي.

تسلسل المنطق (من spec 07_decision_engine.md):
1. تصنيف لاعبي تشكيلتي بحالة الإصابة.
2. (GW≥2) دمج بيانات الإجماع.
3. بناء بدائل لكل مرشح تحويل إجباري.
4. تمرير لـ transfer_planner.
5. اختيار الكابتن ونائبه.
6. تقييم اقتراح الرقاقة.
"""

import logging
from pathlib import Path
from typing import Optional

from squad_optimizer import _compute_scores, _normalize
from injuries_source import get_injury_status
from transfer_planner import update_transfer_queue, calculate_priority_score

logger = logging.getLogger(__name__)

# ── ثوابت الكابتن (قابلة للتعديل) ────────────────────────────────────────────
CAPTAIN_WEIGHT_FORM = 0.40
CAPTAIN_WEIGHT_FIXTURE = 0.35
CAPTAIN_WEIGHT_CONSENSUS = 0.25

# ── ثوابت اقتراح الرقائق ──────────────────────────────────────────────────────
TRIPLE_CAPTAIN_MIN_FORM = 7.0          # حد أدنى لـ form الكابتن
TRIPLE_CAPTAIN_MAX_FDR = 2             # حد أقصى FDR (1=أسهل, 5=أصعب)
BENCH_BOOST_MIN_BENCH_SCORE = 20.0     # نقاط متوقعة من البدلاء الأربعة
WILDCARD_MIN_FORCED_EXCESS = 3         # فرق مرشحين مقابل تحويلات متاحة

# الرقائق المتاحة (من 00_GAME_RULES.md)
ALL_CHIPS = {"wildcard", "freehit", "3xc", "bboost"}

# الرقائق المقسّمة بين نصفَي الموسم (الجولة 19 حدّ فاصل)
FIRST_HALF_DEADLINE_GW = 19


def _get_player_name(player_id: int, players_map: dict) -> str:
    """يُرجع اسم اللاعب من players_map أو fallback."""
    p = players_map.get(player_id, {})
    return p.get("web_name", f"player_{player_id}")


def _find_best_replacement(
    player_out: dict,
    my_squad_ids: set,
    all_players: list[dict],
    available_budget: float,
) -> Optional[dict]:
    """
    يجد أفضل بديل لـ player_out بنفس المركز ضمن الميزانية المتاحة.
    يستخدم نفس دالة الدرجة من squad_optimizer (لتفادي ازدواجية المنطق).
    """
    pos_type = player_out.get("element_type")
    current_price = player_out.get("now_cost", 0) / 10

    # ميزانية الاستبدال = سعر اللاعب الخارج + الرصيد المتاح
    budget_for_replacement = current_price + available_budget

    candidates = [
        p for p in all_players
        if p.get("element_type") == pos_type
        and p["id"] not in my_squad_ids
        and p.get("now_cost", 0) / 10 <= budget_for_replacement
        and p.get("status", "a") in ("a", "d")  # متاح أو مشكوك فقط
    ]

    if not candidates:
        logger.warning(
            "لا يوجد بديل لـ %s (مركز=%d، ميزانية=%.1fM)",
            player_out.get("web_name"), pos_type, budget_for_replacement
        )
        return None

    # استخدام دالة _compute_scores من squad_optimizer مباشرة
    scores = _compute_scores(candidates)
    best_idx = scores.index(max(scores))
    best = candidates[best_idx]
    best["_score"] = scores[best_idx]

    logger.debug(
        "أفضل بديل لـ %s: %s (سعر=%.1fM، درجة=%.3f)",
        player_out.get("web_name"),
        best.get("web_name"),
        best.get("now_cost", 0) / 10,
        best["_score"]
    )
    return best


def _get_used_chips_this_half(chips_history: list[dict], current_gw: int) -> set:
    """
    يستخرج الرقائق المستخدمة في النصف الحالي من الموسم.
    النصف الأول: حتى الجولة 19. النصف الثاني: من الجولة 20.
    """
    in_second_half = current_gw > FIRST_HALF_DEADLINE_GW
    used = set()
    for chip in chips_history:
        chip_gw = chip.get("event", 0)
        chip_name = chip.get("name", "").lower()
        if in_second_half:
            if chip_gw > FIRST_HALF_DEADLINE_GW:
                used.add(chip_name)
        else:
            if chip_gw <= FIRST_HALF_DEADLINE_GW:
                used.add(chip_name)
    return used


def _select_captain(
    updated_squad: list[dict],
    injury_statuses: dict,
    consensus_data: dict,
    total_top_n: int,
    all_players_map: dict,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    يختار الكابتن ونائبه بناءً على form + fixture + consensus.
    لا يُقترح كابتن حالته غير fit.
    """
    eligible = [
        p for p in updated_squad
        if get_injury_status(p.get("element"), injury_statuses).get("status") == "fit"
    ]

    if not eligible:
        logger.warning("لا يوجد لاعب سليم كامل لاختيار الكابتن!")
        return None, None

    def captain_score(player: dict) -> float:
        pid = player.get("element")
        full_player = all_players_map.get(pid, player)

        # form (متوسط نقاط آخر المباريات)
        form = float(full_player.get("form") or 0)
        form_norm = min(form / 12.0, 1.0)  # طبّع: form=12 هو الحد النظري العملي

        # سهولة المباراة (FDR أقل = أسهل) — من ep_next كبديل عملي لو FDR غير متاح
        ep_next = float(full_player.get("ep_next") or 0)
        # طبّع ep_next بين 0 و1 (قيم عادية 0-15)
        fixture_norm = min(ep_next / 15.0, 1.0)

        # consensus
        count = consensus_data.get(pid, 0)
        consensus_norm = count / total_top_n if total_top_n > 0 else 0.0

        return (
            CAPTAIN_WEIGHT_FORM * form_norm
            + CAPTAIN_WEIGHT_FIXTURE * fixture_norm
            + CAPTAIN_WEIGHT_CONSENSUS * consensus_norm
        )

    sorted_eligible = sorted(eligible, key=captain_score, reverse=True)
    captain = sorted_eligible[0] if len(sorted_eligible) >= 1 else None
    vice = sorted_eligible[1] if len(sorted_eligible) >= 2 else None

    return captain, vice


def _evaluate_chip(
    available_chips: set,
    captain_player: dict,
    my_squad: list[dict],
    bench: list[dict],
    n_forced: int,
    available_free_transfers: int,
    all_players_map: dict,
) -> dict:
    """يُقيّم أيّ رقاقة (إن وجدت) مناسبة للجولة."""
    if not available_chips:
        return {"chip": None, "recommended": False, "reason": "كل الرقائق مستخدمة بهذا النصف من الموسم"}

    # ── Triple Captain ───────────────────────────────────────────────────────
    if "3xc" in available_chips and captain_player:
        cap_id = captain_player.get("element")
        cap_full = all_players_map.get(cap_id, captain_player)
        cap_form = float(cap_full.get("form") or 0)
        # ep_next كمعيار سهولة المباراة
        cap_ep = float(cap_full.get("ep_next") or 0)
        if cap_form >= TRIPLE_CAPTAIN_MIN_FORM and cap_ep >= 8.0:
            return {
                "chip": "Triple Captain",
                "recommended": True,
                "reason": (
                    f"الكابتن {cap_full.get('web_name')} بفورم {cap_form} "
                    f"ونقاط متوقعة {cap_ep:.1f} — ثلاثية الكابتن مجدية"
                ),
            }

    # ── Bench Boost ───────────────────────────────────────────────────────────
    if "bboost" in available_chips and bench:
        bench_scores = []
        for pick in bench:
            pid = pick.get("element")
            full_p = all_players_map.get(pid, {})
            ep = float(full_p.get("ep_next") or 0)
            bench_scores.append(ep)
        total_bench_ep = sum(bench_scores)
        if total_bench_ep >= BENCH_BOOST_MIN_BENCH_SCORE:
            return {
                "chip": "Bench Boost",
                "recommended": True,
                "reason": (
                    f"نقاط بدلاء متوقعة: {total_bench_ep:.1f} — Bench Boost مجدي"
                ),
            }

    # ── Wildcard ──────────────────────────────────────────────────────────────
    if "wildcard" in available_chips:
        excess = n_forced - available_free_transfers
        if excess >= WILDCARD_MIN_FORCED_EXCESS:
            return {
                "chip": "Wildcard",
                "recommended": True,
                "reason": (
                    f"{n_forced} مرشح للتحويل مقابل {available_free_transfers} تحويل مجاني فقط — "
                    f"Wildcard أجدى من تكبّد خصومات متعددة"
                ),
            }

    # ── Free Hit ──────────────────────────────────────────────────────────────
    # لا يُقترح تلقائياً بالنسخة الأولى (يحتاج بيانات جولات مضاعفة)
    if "freehit" in available_chips:
        return {
            "chip": "Free Hit",
            "recommended": False,
            "reason": (
                "Free Hit متاح لكن قراره يُترك لك — يُستخدم أمثلياً بالجولات المضاعفة/الملغاة"
            ),
        }

    return {"chip": None, "recommended": False, "reason": "لا توجد شروط مناسبة لاقتراح رقاقة بهذه الجولة"}


# ───────────────────────────────────────────────────────────────────────────
# الدالة الرئيسية
# ───────────────────────────────────────────────────────────────────────────

def run_decision_engine(
    gameweek: int,
    my_picks: list[dict],
    entry_history: dict,
    bootstrap_data: dict,
    injury_statuses: dict,
    manager_history: dict,
    queue_file: Path,
    consensus_data: Optional[dict] = None,
    total_top_n: int = 10,
) -> dict:
    """
    يُشغّل محرك القرار الكامل ويُرجع توصية نهائية لـ report_builder.py.

    Args:
        gameweek: رقم الجولة القادمة
        my_picks: قائمة picks من get_my_team()['picks']
        entry_history: من get_my_team()['entry_history']
        bootstrap_data: من get_bootstrap_static()
        injury_statuses: من injuries_source.get_all_injury_statuses()
        manager_history: من get_manager_history()
        queue_file: مسار ملف حالة transfer_planner الخاص بهذا الفريق
        consensus_data: من top_managers.calculate_consensus() (None في GW1)
        total_top_n: عدد المدراء بالإجماع

    Returns:
        dict الموثّق بـ 07_decision_engine.md
    """
    logger.info("=== محرك القرار — الجولة %d ===", gameweek)

    # ── إعداد الخرائط ────────────────────────────────────────────────────────
    all_players = bootstrap_data.get("elements", [])
    all_players_map: dict[int, dict] = {p["id"]: p for p in all_players}

    my_squad_ids = {pick.get("element") for pick in my_picks}

    # معلومات الرصيد والتحويلات
    bank = entry_history.get("bank", 0) / 10  # FPL يحفظ الرصيد × 10
    event_transfers = entry_history.get("event_transfers", 0)
    event_transfers_cost = entry_history.get("event_transfers_cost", 0)
    # التحويلات المجانية المتاحة: من entry_history أو 1 كحد أدنى
    available_free_transfers = max(
        entry_history.get("transfers_balance", 1), 1
    )

    logger.info(
        "رصيد: %.1fM | تحويلات مجانية: %d | تحويلات مستخدمة هذه الجولة: %d",
        bank, available_free_transfers, event_transfers
    )

    # ── الخطوة 1: تصنيف الإصابات ─────────────────────────────────────────────
    forced_candidates = []   # مصاب/موقوف → تحويل إجباري
    flagged_players = []     # غائب عن الإجماع بدون إصابة → للمراجعة اليدوية

    for pick in my_picks:
        player_id = pick.get("element")
        injury_info = get_injury_status(player_id, injury_statuses)
        status = injury_info.get("status", "fit")

        player_data = all_players_map.get(player_id, {})
        player_name = player_data.get("web_name", f"player_{player_id}")

        if status in ("injured", "suspended"):
            forced_candidates.append({
                "player_out_id": player_id,
                "player_out_name": player_name,
                "player_out_data": player_data,
                "injury_status": status,
                "consensus_count": consensus_data.get(player_id, 0) if consensus_data else 0,
                "total_top_n": total_top_n,
                "reason": f"{status} — {injury_info.get('note', '')}".strip(" —"),
            })
            logger.info("مرشح إجباري: %s (%s)", player_name, status)

    # ── الخطوة 2: (GW≥2) دمج بيانات الإجماع ─────────────────────────────────
    if gameweek >= 2 and consensus_data is not None:
        for pick in my_picks:
            player_id = pick.get("element")
            if player_id in {c["player_out_id"] for c in forced_candidates}:
                continue  # موجود بالفعل بالإجباريين

            count = consensus_data.get(player_id, 0)
            total_n = total_top_n or 1
            player_data = all_players_map.get(player_id, {})
            player_name = player_data.get("web_name", f"player_{player_id}")
            injury_info = get_injury_status(player_id, injury_statuses)
            status = injury_info.get("status", "fit")

            if count <= 2:  # غائب كلياً أو حضور ضعيف
                if status in ("doubtful", "injured", "suspended"):
                    # الإجماع + إصابة/شك = مرشح إجباري
                    forced_candidates.append({
                        "player_out_id": player_id,
                        "player_out_name": player_name,
                        "player_out_data": player_data,
                        "injury_status": status,
                        "consensus_count": count,
                        "total_top_n": total_top_n,
                        "reason": (
                            f"غائب عن إجماع أفضل {total_top_n} ({count} فقط) + حالة: {status}"
                        ),
                    })
                    logger.info("مرشح إجباري (إجماع+إصابة): %s", player_name)
                else:
                    # غائب عن الإجماع لكن سليم → للمراجعة اليدوية فقط
                    flagged_players.append({
                        "name": player_name,
                        "reason": (
                            f"غائب عن إجماع أفضل {total_top_n} ({count}/{total_top_n}) "
                            f"لكن لا توجد شكوك إصابة رسمية — للمراجعة اليدوية فقط"
                        ),
                    })
                    logger.debug("لاعب للمراجعة (إجماع فقط): %s", player_name)

    # ── الخطوة 3: بناء بدائل للمرشحين الإجباريين ────────────────────────────
    for candidate in forced_candidates:
        best_in = _find_best_replacement(
            player_out=candidate["player_out_data"],
            my_squad_ids=my_squad_ids,
            all_players=all_players,
            available_budget=bank,
        )
        candidate["player_in_data"] = best_in
        candidate["player_in_id"] = best_in["id"] if best_in else None
        candidate["player_in_name"] = best_in.get("web_name", "غير متاح") if best_in else "غير متاح"

    # ── الخطوة 4: تمرير لـ transfer_planner ──────────────────────────────────
    queue_result = update_transfer_queue(
        new_candidates=forced_candidates,
        available_free_transfers=available_free_transfers,
        current_gameweek=gameweek,
        queue_file=queue_file,
        injury_statuses=injury_statuses,
    )

    execute_now = queue_result.get("execute_now", [])
    still_pending = queue_result.get("still_pending", [])
    penalty_transfer = queue_result.get("penalty_transfer")

    # بناء قائمة التحويلات المنسّقة
    forced_transfers = []
    for t in execute_now:
        forced_transfers.append({
            "out": t.get("player_out_name", "?"),
            "in": t.get("player_in_name", "?"),
            "reason": t.get("reason", ""),
            "cost_in_points": 0,  # ضمن التحويلات المجانية
        })
    if penalty_transfer:
        forced_transfers.append({
            "out": penalty_transfer.get("player_out_name", "?"),
            "in": penalty_transfer.get("player_in_name", "?"),
            "reason": penalty_transfer.get("justification", ""),
            "cost_in_points": -4,
        })

    # ── الخطوة 5: اختيار الكابتن ─────────────────────────────────────────────
    # التشكيلة "بعد" التحويلات المتوقعة (تقريبية — الأساسيون فقط)
    updated_squad = [
        pick for pick in my_picks
        if pick.get("element") not in {t.get("player_out_id") for t in execute_now}
    ]

    captain_pick, vice_pick = _select_captain(
        updated_squad=updated_squad,
        injury_statuses=injury_statuses,
        consensus_data=consensus_data or {},
        total_top_n=total_top_n,
        all_players_map=all_players_map,
    )

    captain_name = _get_player_name(captain_pick.get("element"), all_players_map) if captain_pick else None
    vice_name = _get_player_name(vice_pick.get("element"), all_players_map) if vice_pick else None

    logger.info("الكابتن: %s | النائب: %s", captain_name, vice_name)

    # ── الخطوة 6: تقييم الرقائق ──────────────────────────────────────────────
    chips_history = manager_history.get("chips", [])
    used_chips_this_half = _get_used_chips_this_half(chips_history, gameweek)
    available_chips = ALL_CHIPS - used_chips_this_half

    logger.info(
        "الرقائق المستخدمة بهذا النصف: %s | المتاحة: %s",
        used_chips_this_half, available_chips
    )

    # البدلاء (الـ4 الأخيرين حسب position)
    bench_picks = sorted(my_picks, key=lambda p: p.get("position", 0))[-4:]

    chip_suggestion = _evaluate_chip(
        available_chips=available_chips,
        captain_player=captain_pick,
        my_squad=my_picks,
        bench=bench_picks,
        n_forced=len(forced_candidates),
        available_free_transfers=available_free_transfers,
        all_players_map=all_players_map,
    )

    # ── حساب التكلفة وما تبقّى ──────────────────────────────────────────────
    transfers_cost = sum(t.get("cost_in_points", 0) for t in forced_transfers)
    bank_after = bank  # تُحسب تقريبياً (بدون تنفيذ فعلي)

    result = {
        "gameweek": gameweek,
        "forced_transfers": forced_transfers,
        "still_pending": [
            {"out": t.get("player_out_name", "?"), "reason": t.get("reason", "")}
            for t in still_pending
        ],
        "flagged_players": flagged_players,
        "captain": captain_name,
        "vice_captain": vice_name,
        "chip_suggestion": chip_suggestion,
        "transfers_cost": transfers_cost,
        "bank_after": round(bank_after, 1),
        "free_transfers_remaining": max(0, available_free_transfers - len(execute_now)),
    }

    logger.info(
        "محرك القرار اكتمل: %d تحويل، كابتن=%s، رقاقة=%s",
        len(forced_transfers),
        captain_name,
        chip_suggestion.get("chip") or "لا"
    )
    return result
