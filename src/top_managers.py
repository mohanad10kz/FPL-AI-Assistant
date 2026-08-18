"""
top_managers.py — جلب تشكيلات أفضل N مدير عالمياً ومقارنتها بتشكيلة المستخدم.

⚠️ يبدأ العمل فقط بعد انتهاء الجولة الأولى فعلياً.
⚠️ هذا الملف لا يتخذ قرار تحويل — فقط يُنتج بيانات مقارنة خام لـ decision_engine.py.
"""

import time
import logging
from typing import Optional
from fpl_client import get_league_standings, get_my_team, FPLAPIError

logger = logging.getLogger(__name__)

# ── ثوابت ──────────────────────────────────────────────────────────────────
OVERALL_LEAGUE_ID = 314     # معرّف الدوري العام العالمي
REQUEST_DELAY = 0.5         # ثانية بين كل طلب HTTP لتفادي الحظر
HIGH_CONSENSUS_THRESHOLD = 0.7  # 70% من N لاعتبار اللاعب "إجماع قوي"


# ───────────────────────────────────────────────────────────────────────────

def get_top_n_manager_ids(n: int = 10, league_id: int = OVERALL_LEAGUE_ID) -> list[int]:
    """
    يجلب أول N معرّف لأفضل المدراء عالمياً من ترتيب الدوري.

    ⚠️ استدعِ هذه الدالة فقط بعد انتهاء الجولة (finished=True في bootstrap-static).

    Args:
        n: عدد المدراء المطلوب (افتراضي 10)
        league_id: معرّف الدوري (افتراضي 314 = Overall World)

    Returns:
        قائمة بـ entry IDs لأفضل N مدير (قد تكون أقل من N لو الدوري فارغ)
    """
    logger.info("جلب أفضل %d مدير من league_id=%d...", n, league_id)
    data = get_league_standings(league_id=league_id, page=1)
    results = data.get("standings", {}).get("results", [])

    manager_ids = [r["entry"] for r in results[:n] if r.get("entry")]

    logger.info("تم جلب %d معرّف من أصل %d مطلوب", len(manager_ids), n)
    return manager_ids


def get_top_n_squads(
    manager_ids: list[int],
    gameweek: int,
) -> list[dict]:
    """
    يجلب تشكيلات أفضل N مدير للجولة المحددة.
    يتعامل مع فشل جلب أي مدير دون إيقاف الباقين.

    Args:
        manager_ids: قائمة entry IDs من get_top_n_manager_ids()
        gameweek: رقم الجولة

    Returns:
        قائمة من dicts، كل dict يحوي:
            - 'manager_id': int
            - 'picks': قائمة الـ15 لاعب
    """
    squads = []
    failed = 0

    for idx, manager_id in enumerate(manager_ids):
        try:
            team_data = get_my_team(manager_id, gameweek)
            picks = team_data.get("picks", [])
            if picks:
                squads.append({
                    "manager_id": manager_id,
                    "picks": picks,
                })
                logger.debug("✅ تشكيلة manager_id=%d: %d لاعب", manager_id, len(picks))
        except FPLAPIError as e:
            failed += 1
            logger.warning(
                "⚠️ فشل جلب تشكيلة manager_id=%d (تم تخطيه): %s",
                manager_id, e
            )
        except Exception as e:
            failed += 1
            logger.warning(
                "⚠️ خطأ غير متوقع لـ manager_id=%d (تم تخطيه): %s",
                manager_id, e
            )

        # تأخير بين الطلبات لتفادي الحظر
        if idx < len(manager_ids) - 1:
            time.sleep(REQUEST_DELAY)

    logger.info(
        "تشكيلات جُلبت: %d نجاح، %d فشل من أصل %d",
        len(squads), failed, len(manager_ids)
    )
    return squads


def calculate_consensus(top_n_squads: list[dict]) -> dict[int, int]:
    """
    يحسب عدد المرات التي يظهر فيها كل لاعب عبر تشكيلات أفضل N.

    Args:
        top_n_squads: مخرجات get_top_n_squads()

    Returns:
        dict {player_element_id: count} — count لا يتجاوز len(top_n_squads)
    """
    consensus: dict[int, int] = {}
    total = len(top_n_squads)

    for squad in top_n_squads:
        for pick in squad.get("picks", []):
            player_id = pick.get("element")
            if player_id:
                consensus[player_id] = consensus.get(player_id, 0) + 1

    # تحقق سلامة: لا يتجاوز أي تكرار عدد المدراء
    over = sum(1 for c in consensus.values() if c > total)
    if over:
        logger.error("!خطأ منطقي: %d لاعب لديه تكرار يتجاوز عدد المدراء (%d)", over, total)

    logger.info(
        "إجماع محسوب: %d لاعب فريد عبر %d تشكيلة",
        len(consensus), total
    )
    return consensus


def compare_my_team_with_consensus(
    my_squad: list[dict],
    consensus_data: dict[int, int],
    total_top_n: int,
    all_players_map: Optional[dict[int, str]] = None,
) -> dict:
    """
    يقارن تشكيلة المستخدم بإجماع أفضل N ويُصنّف اللاعبين.

    ⚠️ لا قرار تحويل هنا — فقط بيانات مقارنة خام لـ decision_engine.py.
    القاعدة: غياب لاعب من تشكيلات أفضل N لا يعني أنه سيء — راجع 05_top_managers.md.

    Args:
        my_squad: قائمة picks من get_my_team()['picks']
        consensus_data: مخرجات calculate_consensus()
        total_top_n: عدد المدراء في الإجماع (لحساب النسب)
        all_players_map: dict {player_id: web_name} للحصول على الأسماء (اختياري)

    Returns:
        dict يحوي:
            - 'players_not_in_top_n': [{"id": ..., "name": ..., "count": 0}]
            - 'players_low_presence': [{"id": ..., "name": ..., "count": 1|2, "pct": ...}]
            - 'players_high_consensus_missing': [{"id": ..., "name": ..., "count": ..., "pct": ...}]
    """
    def _name(pid: int) -> str:
        if all_players_map:
            return all_players_map.get(pid, f"player_{pid}")
        return f"player_{pid}"

    my_player_ids = {pick.get("element") for pick in my_squad if pick.get("element")}
    high_threshold = round(total_top_n * HIGH_CONSENSUS_THRESHOLD)

    players_not_in_top_n = []
    players_low_presence = []

    for player_id in my_player_ids:
        count = consensus_data.get(player_id, 0)
        pct = round(count / total_top_n * 100) if total_top_n else 0

        if count == 0:
            players_not_in_top_n.append({
                "id": player_id,
                "name": _name(player_id),
                "count": 0,
                "pct": 0,
            })
        elif count <= 2:
            players_low_presence.append({
                "id": player_id,
                "name": _name(player_id),
                "count": count,
                "pct": pct,
            })

    # لاعبون لا أملكهم لكن تكرارهم ≥ 70% من N
    players_high_consensus_missing = []
    for player_id, count in consensus_data.items():
        if player_id not in my_player_ids and count >= high_threshold:
            pct = round(count / total_top_n * 100) if total_top_n else 0
            players_high_consensus_missing.append({
                "id": player_id,
                "name": _name(player_id),
                "count": count,
                "pct": pct,
            })

    # ترتيب بالأهمية (أقل وجود أولاً)
    players_not_in_top_n.sort(key=lambda x: x["id"])
    players_low_presence.sort(key=lambda x: x["count"])
    players_high_consensus_missing.sort(key=lambda x: x["count"], reverse=True)

    result = {
        "players_not_in_top_n": players_not_in_top_n,
        "players_low_presence": players_low_presence,
        "players_high_consensus_missing": players_high_consensus_missing,
        "total_top_n_analyzed": total_top_n,
    }

    logger.info(
        "مقارنة التشكيلة: %d غائب عن الإجماع، %d حضور منخفض، %d إجماع قوي غائب",
        len(players_not_in_top_n),
        len(players_low_presence),
        len(players_high_consensus_missing),
    )
    return result
