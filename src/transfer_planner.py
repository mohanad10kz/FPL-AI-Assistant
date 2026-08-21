"""
transfer_planner.py — إدارة طابور التحويلات المتعدد الجولات.

الملف الوحيد بالمشروع ذو حالة دائمة (stateful) — يقرأ/يكتب:
    data/state/transfer_queue_{team_id}.json
    (المسار يُمرَّر كوسيط من main.py لدعم فرق متعددة)

المبدأ الأساسي: لا تقترح تحويلات أكثر من رصيدك المجاني إلا بمبرر قوي موثّق.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── ثوابت أولويات التحويل (قابلة للتعديل) ───────────────────────────────────
# إصابة/إيقاف مؤكد → أولوية قصوى
PRIORITY_INJURED = 10.0
PRIORITY_SUSPENDED = 10.0

# غياب كامل عن إجماع أفضل N + Doubtful → أولوية عالية
PRIORITY_ABSENT_DOUBTFUL_BASE = 7.0

# غياب كامل عن إجماع أفضل N (سليم) → متوسط
PRIORITY_ABSENT_FIT = 4.0

# حضور ضعيف بالإجماع (1-2 من 10) → منخفض
PRIORITY_LOW_PRESENCE = 2.0

# فروقات نقاط بسيطة فقط → ضعيف جداً
PRIORITY_PERFORMANCE_ONLY = 1.0

# عتبة تبرير خصم -4 (يجب أن يتجاوز هذه الدرجة)
PENALTY_WORTHY_THRESHOLD = 9.0


# ───────────────────────────────────────────────────────────────────────────
# 1. قراءة/كتابة ملف الحالة
# ───────────────────────────────────────────────────────────────────────────

def load_queue(queue_file: Path) -> dict:
    """
    يقرأ قائمة المرشحين المعلّقين من ملف الحالة الخاص بالفريق.
    لو الملف غير موجود (أول تشغيل)، يُنشئ هيكل فارغ بدل رمي خطأ.

    Args:
        queue_file: مسار ملف الحالة الخاص بهذا الفريق

    Returns:
        {"last_updated_gw": int|None, "pending_candidates": []}
    """
    try:
        if queue_file.exists():
            with open(queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(
                    "تم تحميل %d مرشح معلّق من الجولة %s (ملف: %s)",
                    len(data.get("pending_candidates", [])),
                    data.get("last_updated_gw", "غير معروفة"),
                    queue_file
                )
                return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("⚠️ خطأ في قراءة ملف الطابور (%s) — سيُبدأ بطابور فارغ: %s", queue_file, e)

    return {"last_updated_gw": None, "pending_candidates": []}


def save_queue(queue_data: dict, gameweek: int, queue_file: Path) -> bool:
    """
    يحفظ حالة الطابور بملف JSON خاص بالفريق.

    Args:
        queue_data: dict يحوي pending_candidates
        gameweek: رقم الجولة الحالية
        queue_file: مسار ملف الحالة الخاص بهذا الفريق

    Returns:
        True عند النجاح، False عند الفشل
    """
    try:
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        save_data = {
            "last_updated_gw": gameweek,
            "pending_candidates": queue_data.get("pending_candidates", []),
        }
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        logger.info(
            "تم حفظ %d مرشح معلّق للجولة %d (ملف: %s)",
            len(save_data["pending_candidates"]), gameweek, queue_file
        )
        return True
    except OSError as e:
        logger.error("❌ فشل حفظ ملف الطابور (%s): %s", queue_file, e)
        return False


# ───────────────────────────────────────────────────────────────────────────
# 2. حساب الأولوية
# ───────────────────────────────────────────────────────────────────────────

def calculate_priority_score(candidate: dict) -> float:
    """
    يحسب درجة الأولوية لمرشح تحويل.

    حقول الـ candidate المتوقعة:
        - "injury_status": "fit"|"doubtful"|"injured"|"suspended"
        - "consensus_count": int (كم من أفضل N يملكونه)
        - "total_top_n": int (إجمالي N)
        - "reason_type": "injury"|"consensus"|"performance" (اختياري)

    Returns:
        درجة float بين 0 و 10
    """
    status = candidate.get("injury_status", "fit")
    consensus_count = candidate.get("consensus_count", 0)
    total_n = candidate.get("total_top_n", 10)

    # إصابة/إيقاف مؤكد → الأولوية القصوى
    if status == "injured":
        return PRIORITY_INJURED
    if status == "suspended":
        return PRIORITY_SUSPENDED

    # حساب نسبة الغياب عن الإجماع
    absence_ratio = 1.0 - (consensus_count / total_n) if total_n > 0 else 1.0

    if status == "doubtful":
        # غياب + Doubtful → أولوية عالية متدرّجة
        score = PRIORITY_ABSENT_DOUBTFUL_BASE + (absence_ratio * 2.0)
        return min(score, 9.5)  # لا تتجاوز الإصابة المؤكدة

    if consensus_count == 0:
        # غائب تماماً عن الإجماع (سليم) → متوسط
        return PRIORITY_ABSENT_FIT

    if consensus_count <= 2:
        # حضور ضعيف
        return PRIORITY_LOW_PRESENCE

    # فروقات بسيطة فقط
    return PRIORITY_PERFORMANCE_ONLY


# المسار الافتراضي لملف الحالة
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
QUEUE_FILE = STATE_DIR / "transfer_queue.json"


# ───────────────────────────────────────────────────────────────────────────
# 3. الدالة الأساسية
# ───────────────────────────────────────────────────────────────────────────

def update_transfer_queue(
    new_candidates: list[dict],
    available_free_transfers: int,
    current_gameweek: int,
    queue_file: Optional[Path] = None,
    injury_statuses: Optional[dict] = None,
) -> dict:
    """
    يدمج المرشحين الجدد مع المعلّقين القدامى، ويقرر من يُنفَّذ الآن.


    الخوارزمية (من spec 06_transfer_planner.md):
    1. اقرأ pending_candidates من الجولة الماضية.
    2. أعد تقييم كل مرشح قديم ببيانات الجولة الجديدة.
    3. احذف من تعافى أو لم يعد يستحق التحويل.
    4. ادمج القديم المحدَّث مع الجديد (بدون تكرار).
    5. رتّب بالأولوية.
    6. execute_now = أعلى `available_free_transfers` مرشحاً.
    7. still_pending = الباقي.
    8. احفظ still_pending للجولة القادمة.

    Args:
        new_candidates: مرشحو هذه الجولة (من decision_engine)
        available_free_transfers: رصيد التحويلات المجانية (≤ 5 حسب القواعد)
        current_gameweek: رقم الجولة الحالية
        queue_file: مسار ملف الحالة الخاص بهذا الفريق
        injury_statuses: أحدث بيانات إصابات {player_id: {"status": ...}}

    Returns:
        {
            "execute_now": [...],    # نفّذ هذه الجولة
            "still_pending": [...],  # مرشحون للجولة القادمة
            "penalty_transfer": None | dict  # تحويل -4 مقترح (استثنائي)
        }
    """
    if queue_file is None:
        queue_file = QUEUE_FILE

    # ── 1. قراءة الطابور الحالي ─────────────────────────────────────────────
    queue_data = load_queue(queue_file)
    old_pending = queue_data.get("pending_candidates", [])

    # ── 2. إعادة تقييم القدامى ببيانات الجولة الجديدة ────────────────────────
    re_evaluated_old = []
    for old in old_pending:
        player_out_id = old.get("player_out_id")

        # تحديث حالة الإصابة لو توفرت بيانات جديدة
        if injury_statuses and player_out_id:
            new_status_info = injury_statuses.get(player_out_id, {})
            new_status = new_status_info.get("status", "fit")
            old["injury_status"] = new_status

            # لو تعافى تماماً ولم يعد بالمرشحين الجدد → احذفه
            if new_status == "fit" and not any(
                nc.get("player_out_id") == player_out_id for nc in new_candidates
            ):
                # تحقق لو لا يزال في الإجماع
                new_consensus = old.get("consensus_count", 0)
                if new_consensus > 2:
                    logger.info(
                        "تم حذف player_id=%d من الطابور: تعافى وعاد للإجماع",
                        player_out_id
                    )
                    continue

        # إعادة حساب priority_score من جديد (لا تستخدم القديمة كما هي)
        old["priority_score"] = calculate_priority_score(old)
        old["reviewed_count"] = old.get("reviewed_count", 0) + 1
        re_evaluated_old.append(old)

    # ── 3. دمج القديم مع الجديد (بدون تكرار — الجديد يطغى عند التعارض) ───────
    combined_map: dict[int, dict] = {}

    for old in re_evaluated_old:
        pid = old.get("player_out_id")
        if pid:
            combined_map[pid] = old

    for new in new_candidates:
        pid = new.get("player_out_id")
        if pid:
            new["priority_score"] = calculate_priority_score(new)
            new.setdefault("flagged_at_gw", current_gameweek)
            new.setdefault("reviewed_count", 0)
            combined_map[pid] = new  # الجديد يطغى عند التكرار

    # ── 4. ترتيب بالأولوية (تنازلياً) ──────────────────────────────────────
    all_candidates = sorted(
        combined_map.values(),
        key=lambda c: c.get("priority_score", 0),
        reverse=True
    )

    # ── 5. تقسيم execute_now / still_pending ────────────────────────────────
    execute_now = all_candidates[:available_free_transfers]
    still_pending_raw = all_candidates[available_free_transfers:]

    # ── 6. الحالة الاستثنائية: تحويل واحد -4 مبرَّر ────────────────────────
    penalty_transfer = None
    if still_pending_raw and available_free_transfers == 0:
        top_pending = still_pending_raw[0]
        if top_pending.get("priority_score", 0) >= PENALTY_WORTHY_THRESHOLD:
            penalty_transfer = {
                **top_pending,
                "cost_in_points": -4,
                "justification": (
                    "تحويل إضافي مقترح بخصم -4 بسبب: " + top_pending.get("reason", "إصابة/إيقاف مؤكد")
                ),
            }
            still_pending_raw = still_pending_raw[1:]  # حذفه من الانتظار لو اقترحنا تنفيذه
            logger.info(
                "تحويل -4 مقترح: player_id=%s (أولوية=%.1f)",
                top_pending.get("player_out_id"),
                top_pending.get("priority_score", 0)
            )
    elif still_pending_raw and available_free_transfers > 0:
        top_next = still_pending_raw[0]
        if top_next.get("priority_score", 0) >= PENALTY_WORTHY_THRESHOLD:
            penalty_transfer = {
                **top_next,
                "cost_in_points": -4,
                "justification": (
                    "تحويل إضافي مقترح بخصم -4 بسبب: " + top_next.get("reason", "إصابة/إيقاف مؤكد")
                ),
            }

    # ── 7. حفظ still_pending للجولة القادمة ─────────────────────────────────
    still_pending = list(still_pending_raw)
    save_queue({"pending_candidates": still_pending}, current_gameweek, queue_file)

    logger.info(
        "طابور التحويلات: %d للتنفيذ الآن، %d معلّق، تحويل -4: %s",
        len(execute_now),
        len(still_pending),
        "نعم" if penalty_transfer else "لا"
    )

    return {
        "execute_now": execute_now,
        "still_pending": still_pending,
        "penalty_transfer": penalty_transfer,
    }
