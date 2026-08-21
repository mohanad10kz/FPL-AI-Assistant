"""
outcome_tracker.py — (المرحلة 1: جمع بيانات للتعلّم المستقبلي)

يسجّل النتيجة الفعلية لكل توصية سابقة (تحويلات، كابتن، لاعبي differential)
بعد انتهاء كل جولة فعلياً، لبناء أرشيف بيانات تدريبية لـ learning_engine.py مستقبلاً.

⚠️ قيود التصميم الحرج:
- هذا الملف مستقل تماماً — لا يُستدعى من decision_engine.py ولا يؤثر عليه بأي شكل بهذه المرحلة.
- الفصل الكامل مقصود ومهم: التقييم يُبنى بأثر رجعي على الجولات المنتهية فقط،
  ولا يغيّر أي قواعد أو أوزان لاتخاذ القرارات الحالية.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime, timezone

from fpl_client import get_my_team, get_player_gameweek_points

logger = logging.getLogger(__name__)

# ─── مسارات الملفات ──────────────────────────────────────────────────────────
src_dir = Path(__file__).parent
DATA_DIR = src_dir.parent / "data"
HISTORY_DIR = DATA_DIR / "history"


def _build_players_map(bootstrap_data: Optional[dict]) -> tuple[dict[int, dict], dict[str, dict]]:
    """
    يبني خريطتين للبحث عن اللاعبين: بالمعرف (ID) وبالاسم (web_name).
    """
    id_map: dict[int, dict] = {}
    name_map: dict[str, dict] = {}

    if not bootstrap_data:
        return id_map, name_map

    for p in bootstrap_data.get("elements", []):
        pid = p.get("id")
        if pid is not None:
            id_map[pid] = p
        web_name = p.get("web_name", "")
        if web_name:
            name_map[web_name.strip().lower()] = p
            # وأيضاً بالاسم الكامل للبحث الإضافي
            full_name = f"{p.get('first_name', '')} {p.get('second_name', '')}".strip().lower()
            if full_name:
                name_map[full_name] = p

    return id_map, name_map


def _resolve_player(
    identifier,
    id_map: dict[int, dict],
    name_map: dict[str, dict],
) -> tuple[Optional[int], str]:
    """
    يستخرج معرف اللاعب واسمه سواء كان المعطى ID أو قاموساً أو اسماً نصياً.
    """
    if identifier is None:
        return None, "غير محدد"

    # لو كان قاموساً
    if isinstance(identifier, dict):
        pid = identifier.get("id") or identifier.get("element")
        name = identifier.get("web_name") or identifier.get("name") or (f"player_{pid}" if pid else "غير محدد")
        if pid and pid in id_map:
            name = id_map[pid].get("web_name", name)
        return pid, name

    # لو كان رقماً (ID)
    if isinstance(identifier, int):
        if identifier in id_map:
            return identifier, id_map[identifier].get("web_name", f"player_{identifier}")
        return identifier, f"player_{identifier}"

    # لو كان نصاً (اسم اللاعب)
    if isinstance(identifier, str):
        cleaned = identifier.strip()
        cleaned_lower = cleaned.lower()
        if cleaned_lower in name_map:
            p = name_map[cleaned_lower]
            return p.get("id"), p.get("web_name", cleaned)
        return None, cleaned

    return None, str(identifier)


def detect_pending_evaluation(
    team_id: int,
    bootstrap_data: dict,
    history_dir: Optional[Path] = None,
) -> list[int]:
    """
    يفحص الجولات المنتهية بـ bootstrap-static ويحدد الجولات التي لها ملف توصيات
    (gw_{n}.json) ولم يتم تقييمها بعد (لا يوجد outcomes_gw_{n}.json).

    Args:
        team_id: معرّف الفريق (FPL entry ID)
        bootstrap_data: بيانات bootstrap-static
        history_dir: مسار مجلد الأرشيف (اختياري، افتراضياً data/history)

    Returns:
        قائمة بأرقام الجولات المنتظرة للتقييم مرتبة تصاعدياً.
    """
    events = bootstrap_data.get("events", [])
    finished_gws = [
        int(e["id"]) for e in events
        if e.get("finished") and e.get("id") is not None
    ]

    base_dir = history_dir or HISTORY_DIR
    team_dir = base_dir / str(team_id)

    pending_gws = []
    for gw in sorted(finished_gws):
        # التحقق من وجود ملف التوصيات السابق
        gw_file_in_team = team_dir / f"gw_{gw}.json"
        gw_file_in_root = base_dir / f"gw_{gw}.json"
        gw_exists = gw_file_in_team.exists() or gw_file_in_root.exists()

        # التحقق من وجود ملف التقييم
        outcome_file_in_team = team_dir / f"outcomes_gw_{gw}.json"
        outcome_file_in_root = base_dir / f"outcomes_gw_{gw}.json"
        outcome_exists = outcome_file_in_team.exists() or outcome_file_in_root.exists()

        if gw_exists and not outcome_exists:
            pending_gws.append(gw)

    logger.info(
        "🔍 الجولات المنتهية المنتظرة للتقييم للفريق %d: %s",
        team_id, pending_gws or "لا يوجد"
    )
    return pending_gws


def fetch_actual_team(team_id: int, gameweek: int) -> dict:
    """
    يجلب التشكيلة الفعلية التي لعب بها الفريق بتلك الجولة من FPL API.

    Args:
        team_id: معرّف الفريق
        gameweek: رقم الجولة

    Returns:
        dict تشكيلة الفريق الفعلية، أو dict فارغ عند الفشل.
    """
    try:
        data = get_my_team(team_id, gameweek)
        return data or {}
    except Exception as e:
        logger.warning(
            "⚠️ تعذّر جلب التشكيلة الفعلية للفريق %d بالجولة GW%d: %s",
            team_id, gameweek, e
        )
        return {}


def evaluate_transfer_recommendation(
    decision_record: dict,
    actual_team: dict,
    gameweek: int,
    bootstrap_data: Optional[dict] = None,
    points_getter: Optional[Callable[[int, int], int]] = None,
) -> list[dict]:
    """
    يقيّم التحويلات المقترحة بتلك الجولة:
    - هل تم اتباع التحويل فعلياً من قبل المستخدم؟
    - ما هو فارق النقاط الافتراضي (نقاط اللاعب الداخل - نقاط اللاعب الخارج)؟

    Args:
        decision_record: كائن قرار الجولة المقروء من gw_{n}.json
        actual_team: التشكيلة الفعلية من fetch_actual_team
        gameweek: رقم الجولة
        bootstrap_data: بيانات bootstrap للبحث عن أسماء ومعرفات اللاعبين
        points_getter: دالة جلب النقاط (افتراضياً get_player_gameweek_points)

    Returns:
        قائمة بقواميس تقييم التحويلات.
    """
    pts_fn = points_getter or get_player_gameweek_points
    id_map, name_map = _build_players_map(bootstrap_data)

    forced_transfers = decision_record.get("forced_transfers", [])
    if not forced_transfers:
        return []

    # استخراج اللاعبين الفعليين بالتشكيلة
    actual_picks = actual_team.get("picks", [])
    actual_player_ids = {p.get("element") for p in actual_picks if p.get("element")}
    actual_player_names = {
        id_map[pid].get("web_name", "").strip().lower()
        for pid in actual_player_ids if pid in id_map
    }

    evaluations = []
    for transfer in forced_transfers:
        out_raw = transfer.get("out") or transfer.get("player_out_name") or transfer.get("player_out_id")
        in_raw = transfer.get("in") or transfer.get("player_in_name") or transfer.get("player_in_id")

        out_id, out_name = _resolve_player(out_raw, id_map, name_map)
        in_id, in_name = _resolve_player(in_raw, id_map, name_map)

        # هل اتبع المستخدم التوصية؟ (اللاعب الداخل موجود بتشكيلته الفعلية)
        followed = False
        if in_id and in_id in actual_player_ids:
            followed = True
        elif in_name and in_name.strip().lower() in actual_player_names:
            followed = True

        # جلب النقاط الفعلية (0 صراحة إذا لم يلعب)
        out_points = pts_fn(out_id, gameweek) if out_id else 0
        in_points = pts_fn(in_id, gameweek) if in_id else 0

        # الفائدة الافتراضية
        points_gained = in_points - out_points

        evaluations.append({
            "out": out_name,
            "in": in_name,
            "followed_by_user": followed,
            "points_gained_if_followed": points_gained,
        })

    return evaluations


def evaluate_captain_recommendation(
    decision_record: dict,
    actual_team: dict,
    gameweek: int,
    bootstrap_data: Optional[dict] = None,
    points_getter: Optional[Callable[[int, int], int]] = None,
) -> dict:
    """
    يقيّم توصية الكابتن:
    - نقاط الكابتن المقترح الفعلية.
    - أعلى نقاط حققها أي لاعب آخر بالتشكيلة (كابتن مثالي بأثر رجعي).
    - الفارق (gap) كمقياس لجودة الاختيار.

    Args:
        decision_record: كائن القرار من gw_{n}.json
        actual_team: التشكيلة الفعلية للجولة
        gameweek: رقم الجولة
        bootstrap_data: بيانات bootstrap
        points_getter: دالة جلب النقاط

    Returns:
        dict تقييم الكابتن {"suggested": "...", "actual_points": ..., "best_possible_points": ..., "gap": ...}
    """
    pts_fn = points_getter or get_player_gameweek_points
    id_map, name_map = _build_players_map(bootstrap_data)

    suggested_raw = decision_record.get("captain")
    cap_id, cap_name = _resolve_player(suggested_raw, id_map, name_map)

    actual_cap_points = pts_fn(cap_id, gameweek) if cap_id else 0

    # حساب نقاط جميع لاعبي التشكيلة الفعلية لمعرفة الخيار المثالي بأثر رجعي
    actual_picks = actual_team.get("picks", [])
    squad_points = []
    for pick in actual_picks:
        pid = pick.get("element")
        if pid:
            pts = pts_fn(pid, gameweek)
            squad_points.append(pts)

    if squad_points:
        best_possible_points = max(squad_points)
    else:
        best_possible_points = actual_cap_points

    gap = max(0, best_possible_points - actual_cap_points)

    return {
        "suggested": cap_name,
        "actual_points": actual_cap_points,
        "best_possible_points": best_possible_points,
        "gap": gap,
    }


def evaluate_differential_suggestions(
    decision_record: dict,
    gameweek: int,
    bootstrap_data: Optional[dict] = None,
    points_getter: Optional[Callable[[int, int], int]] = None,
) -> list[dict]:
    """
    يقيّم اقتراحات الـ Differentials (الموصى بمتابعتهم):
    يجلب النقاط الفعلية لكل لاعب مقترح لبناء قاعدة بيانات لجودة الفلاتر.

    Args:
        decision_record: كائن القرار من gw_{n}.json
        gameweek: رقم الجولة
        bootstrap_data: بيانات bootstrap
        points_getter: دالة جلب النقاط

    Returns:
        قائمة بقواميس تقييم لاعبي الـ differential.
    """
    pts_fn = points_getter or get_player_gameweek_points
    id_map, name_map = _build_players_map(bootstrap_data)

    diff_suggestions = decision_record.get("differential_suggestions", [])
    if not diff_suggestions:
        return []

    evaluations = []
    for diff in diff_suggestions:
        raw_id = diff.get("id")
        raw_name = diff.get("name")
        diff_id, diff_name = _resolve_player(raw_id or raw_name, id_map, name_map)

        points = pts_fn(diff_id, gameweek) if diff_id else 0

        evaluations.append({
            "name": diff_name,
            "actual_points": points,
        })

    return evaluations


def build_outcome_record(
    gameweek: int,
    transfer_evaluations: list[dict],
    captain_evaluation: dict,
    differential_evaluations: list[dict],
) -> dict:
    """
    يجمع كل نتائج التقييم في كائن قياسي موحد وفق 13_outcome_tracker.md.
    """
    return {
        "gameweek": gameweek,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "transfer_evaluations": transfer_evaluations,
        "captain_evaluation": captain_evaluation,
        "differential_evaluations": differential_evaluations,
    }


def save_outcome_record(
    outcome_record: dict,
    gameweek: int,
    team_id: int,
    history_dir: Optional[Path] = None,
) -> Path:
    """
    يحفظ سجل النتائج في data/history/{team_id}/outcomes_gw_{n}.json.
    """
    base_dir = history_dir or HISTORY_DIR
    team_history_dir = base_dir / str(team_id)
    team_history_dir.mkdir(parents=True, exist_ok=True)

    outcome_path = team_history_dir / f"outcomes_gw_{gameweek}.json"
    with open(outcome_path, "w", encoding="utf-8") as f:
        json.dump(outcome_record, f, ensure_ascii=False, indent=2)

    logger.info(
        "💾 تم حفظ تقييم نتائج GW%d للفريق %d في: %s",
        gameweek, team_id, outcome_path
    )
    return outcome_path


def process_pending_outcomes(
    team_id: int,
    bootstrap_data: dict,
    history_dir: Optional[Path] = None,
    points_getter: Optional[Callable[[int, int], int]] = None,
) -> list[dict]:
    """
    الدالة التنفيذية الشاملة: تكتشف جميع الجولات المنتهية المعلقة وتقيّمها
    وتحفظ ملفات outcomes_gw_{n}.json لكل جولة.

    Args:
        team_id: معرّف الفريق
        bootstrap_data: بيانات bootstrap-static
        history_dir: مسار مجلد الأرشيف (اختياري)
        points_getter: دالة جلب النقاط (اختياري للاختبارات)

    Returns:
        قائمة بالسجلات المقيمة والمحفوظة.
    """
    pending_gws = detect_pending_evaluation(team_id, bootstrap_data, history_dir)
    if not pending_gws:
        return []

    base_dir = history_dir or HISTORY_DIR
    team_dir = base_dir / str(team_id)

    evaluated_records = []

    for gw in pending_gws:
        logger.info("⚡ بدء تقييم نتائج الجولة المنتهية GW%d للفريق %d...", gw, team_id)
        try:
            # قراءة ملف التوصيات السابق
            gw_file = team_dir / f"gw_{gw}.json"
            if not gw_file.exists():
                gw_file = base_dir / f"gw_{gw}.json"

            if not gw_file.exists():
                logger.warning("⚠️ تعذّر العثور على ملف gw_%d.json — تخطي التقييم", gw)
                continue

            with open(gw_file, "r", encoding="utf-8") as f:
                decision_record = json.load(f)

            # جلب التشكيلة الفعلية
            actual_team = fetch_actual_team(team_id, gw)

            # التقييمات
            transfer_evals = evaluate_transfer_recommendation(
                decision_record=decision_record,
                actual_team=actual_team,
                gameweek=gw,
                bootstrap_data=bootstrap_data,
                points_getter=points_getter,
            )

            captain_eval = evaluate_captain_recommendation(
                decision_record=decision_record,
                actual_team=actual_team,
                gameweek=gw,
                bootstrap_data=bootstrap_data,
                points_getter=points_getter,
            )

            diff_evals = evaluate_differential_suggestions(
                decision_record=decision_record,
                gameweek=gw,
                bootstrap_data=bootstrap_data,
                points_getter=points_getter,
            )

            # بناء السجل وحفظه
            outcome_record = build_outcome_record(
                gameweek=gw,
                transfer_evaluations=transfer_evals,
                captain_evaluation=captain_eval,
                differential_evaluations=diff_evals,
            )

            save_outcome_record(outcome_record, gw, team_id, history_dir)
            evaluated_records.append(outcome_record)

        except Exception as e:
            logger.error(
                "❌ خطأ أثناء تقييم نتائج GW%d للفريق %d: %s",
                gw, team_id, e, exc_info=True
            )

    return evaluated_records
