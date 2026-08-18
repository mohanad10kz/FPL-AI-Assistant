"""
main.py — نقطة التشغيل الوحيدة للمشروع.

ينسّق تسلسل الاستدعاء الكامل من البداية للنهاية.
التسلسل المفصّل موثّق بـ 10_main.md.
"""

import sys
import os
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime

# ─── إعداد Logging قبل أي استيراد ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── إضافة مجلد src للمسار ───────────────────────────────────────────────────
src_dir = Path(__file__).parent
sys.path.insert(0, str(src_dir))

# ─── مسارات الملفات ──────────────────────────────────────────────────────────
DATA_DIR = src_dir.parent / "data"
HISTORY_DIR = DATA_DIR / "history"
STATE_DIR = DATA_DIR / "state"
INITIAL_SQUAD_FLAG = STATE_DIR / "initial_squad_built.flag"


def _send_error_notification(
    bot_token: str,
    chat_id: str,
    error_type: str,
    gameweek: object = None,
) -> None:
    """
    يُرسل رسالة تيليجرام مختصرة عند حدوث خطأ — لا فشل صامت أبداً.
    """
    try:
        from telegram_notifier import send_message
        gw_text = f"الجولة {gameweek}" if gameweek else "جولة غير محددة"
        error_text = (
            f"⚠️ *FPL AI Assistant — خطأ في التشغيل*\n\n"
            f"فشل إنتاج تقرير {gw_text}\\.\n"
            f"السبب: `{error_type}`\n\n"
            f"_يُرجى التحقق من سجلات GitHub Actions\\._"
        )
        send_message(bot_token, chat_id, error_text)
    except Exception as e:
        logger.error("فشل حتى إرسال رسالة الخطأ: %s", e)


def _archive_result(decision: dict, gameweek: int) -> None:
    """يحفظ الكائن الكامل بملف أرشيف لكل جولة."""
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = HISTORY_DIR / f"gw_{gameweek}.json"
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False, indent=2, default=str)
        logger.info("تم أرشفة نتيجة الجولة %d في: %s", gameweek, archive_path)
    except Exception as e:
        logger.warning("⚠️ فشل أرشفة نتيجة الجولة %d: %s", gameweek, e)


def _handle_gw1_initial_squad(
    bootstrap_data: dict,
    bot_token: str,
    chat_id: str,
) -> None:
    """
    يُشغّل squad_optimizer للجولة الأولى ويُرسل توصية التشكيلة الأولية.
    """
    from squad_optimizer import build_initial_squad
    from telegram_notifier import send_message

    logger.info("الجولة 1 — بناء التشكيلة الأولية...")
    players = bootstrap_data.get("elements", [])
    result = build_initial_squad(players)

    if result.get("solver_status") != "Optimal":
        logger.error("فشل بناء التشكيلة الأولية: %s", result.get("solver_status"))
        send_message(
            bot_token, chat_id,
            "❌ فشل بناء التشكيلة الأولية — تحقق من السجلات."
        )
        return

    squad = result.get("squad", [])
    captain = result.get("captain", "غير محدد")
    vice = result.get("vice_captain", "غير محدد")
    cost = result.get("total_cost", 0)
    remaining = result.get("budget_remaining", 0)

    # بناء نص التقرير الأولي
    lines = [
        "📊 *FPL AI Assistant — تشكيلة الجولة الأولى المقترحة*",
        "",
        "_هذه توصية مبنية على نسب الامتلاك والأداء السابق — القرار النهائي لك._",
        "",
        "⚽ *التشكيلة الأساسية المقترحة \\(11\\):*",
    ]

    xi = result.get("starting_xi", [])
    bench = result.get("bench", [])

    pos_names = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    for p in xi:
        pos = pos_names.get(p.get("element_type", 0), "")
        lines.append(f"  • \\[{pos}\\] {p.get('web_name', '?')} — £{p.get('now_cost', 0)/10:.1f}م")

    if bench:
        lines.append("\n🪑 *البدلاء:*")
        for p in bench:
            pos = pos_names.get(p.get("element_type", 0), "")
            lines.append(f"  • \\[{pos}\\] {p.get('web_name', '?')} — £{p.get('now_cost', 0)/10:.1f}م")

    lines.extend([
        f"\n🏆 *الكابتن المقترح:* {captain}",
        f"🥈 *نائب الكابتن:* {vice}",
        f"\n💰 *التكلفة الإجمالية:* £{cost:.1f}م / 100م",
        f"💵 *الرصيد المتبقي:* £{remaining:.1f}م",
        "\n_⚡ تقرير اقتراح — القرار النهائي لك دائماً\\._",
    ])

    report_text = "\n".join(lines)
    send_message(bot_token, chat_id, report_text)

    # وضع العلم لمنع إعادة التشغيل بهذا المسار
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INITIAL_SQUAD_FLAG.write_text(
        datetime.utcnow().isoformat(),
        encoding="utf-8"
    )
    logger.info("تم حفظ علم التشكيلة الأولية: %s", INITIAL_SQUAD_FLAG)

    # أرشفة
    _archive_result(result, gameweek=1)


def main():
    """نقطة الدخول الرئيسية — تسلسل التشغيل الكامل."""

    # ─── الخطوة 1: تحميل الإعدادات ──────────────────────────────────────────
    try:
        from config import config, ConfigError
    except Exception as e:
        logger.critical("❌ فشل تحميل الإعدادات: %s", e)
        sys.exit(1)

    bot_token = config.telegram_bot_token
    chat_id = config.telegram_chat_id
    team_id = config.fpl_team_id
    top_n = config.top_n_managers
    injury_url = config.injury_source_url

    logger.info("=== FPL AI Assistant — بدء التشغيل ===")
    current_gw = None

    try:
        # ─── الخطوة 2: جلب بيانات FPL الأساسية ──────────────────────────────
        from fpl_client import get_bootstrap_static, get_current_gameweek
        logger.info("الخطوة 2: جلب bootstrap-static...")
        bootstrap_data = get_bootstrap_static()
        current_gw = get_current_gameweek(bootstrap_data)

        # ─── الخطوة 3: تحديد الحالة ──────────────────────────────────────────
        if current_gw is None:
            # الموسم انتهى
            logger.info("الموسم انتهى — لا توجد جولة قادمة")
            from report_builder import build_season_ended_message
            from telegram_notifier import send_message
            send_message(bot_token, chat_id, build_season_ended_message())
            return

        logger.info("الجولة الحالية/القادمة: GW%d", current_gw)

        if current_gw == 1 and not INITIAL_SQUAD_FLAG.exists():
            # الجولة الأولى — بناء تشكيلة أولية فقط
            logger.info("GW1 — مسار التشكيلة الأولية")
            _handle_gw1_initial_squad(bootstrap_data, bot_token, chat_id)
            logger.info("=== تم إنهاء تشغيل GW1 بنجاح ===")
            return

        # ─── الخطوة 4: جلب تشكيلتي وتاريخ الرقائق ────────────────────────
        from fpl_client import get_my_team, get_manager_history
        logger.info("الخطوة 4: جلب تشكيلة team_id=%d للجولة %d...", team_id, current_gw)
        my_team_data = get_my_team(team_id, current_gw)
        my_picks = my_team_data.get("picks", [])
        entry_history = my_team_data.get("entry_history", {})

        logger.info("الخطوة 4b: جلب تاريخ الرقائق...")
        manager_history = get_manager_history(team_id)

        # ─── الخطوة 5: جلب حالة الإصابات ─────────────────────────────────
        from injuries_source import get_all_injury_statuses
        logger.info("الخطوة 5: جلب حالة الإصابات...")
        injury_data = get_all_injury_statuses(bootstrap_data, injury_url)

        # ─── الخطوة 6: جلب بيانات إجماع أفضل N (GW≥2 فقط) ────────────────
        consensus_data = None
        if current_gw > 1:
            from top_managers import (
                get_top_n_manager_ids,
                get_top_n_squads,
                calculate_consensus,
            )
            logger.info(
                "الخطوة 6: جلب أفضل %d مدير للجولة %d...",
                top_n, current_gw - 1
            )
            try:
                manager_ids = get_top_n_manager_ids(n=top_n)
                if manager_ids:
                    top_squads = get_top_n_squads(manager_ids, gameweek=current_gw - 1)
                    consensus_data = calculate_consensus(top_squads)
                    logger.info("إجماع: %d لاعب فريد", len(consensus_data))
                else:
                    logger.warning("لا يوجد مدراء بالإجماع بعد — تشغيل بدون بيانات إجماع")
            except Exception as e:
                logger.warning("⚠️ فشل جلب بيانات إجماع أفضل N: %s — المتابعة بدونها", e)

        # ─── الخطوة 7: تشغيل محرك القرار ────────────────────────────────────
        from decision_engine import run_decision_engine
        logger.info("الخطوة 7: تشغيل محرك القرار...")
        decision = run_decision_engine(
            gameweek=current_gw,
            my_picks=my_picks,
            entry_history=entry_history,
            bootstrap_data=bootstrap_data,
            injury_statuses=injury_data,
            manager_history=manager_history,
            consensus_data=consensus_data,
            total_top_n=top_n,
        )

        # ─── الخطوة 8: بناء التقرير وإرساله ─────────────────────────────────
        from report_builder import build_report_text
        from telegram_notifier import send_report
        logger.info("الخطوة 8: بناء التقرير وإرساله...")
        report_text = build_report_text(decision)
        success = send_report(bot_token, chat_id, report_text)
        if not success:
            logger.error("❌ فشل إرسال التقرير — لكن الأرشفة ستتم على أي حال")

        # ─── الخطوة 9: أرشفة النتيجة ─────────────────────────────────────────
        _archive_result(decision, current_gw)

        logger.info("=== تم إنهاء التشغيل بنجاح — الجولة GW%d ===", current_gw)

    except Exception as e:
        # معالجة الأخطاء العليا — لا فشل صامت
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("❌ خطأ غير متوقع: %s\n%s", error_msg, traceback.format_exc())

        # محاولة إرسال إشعار بالخطأ
        _send_error_notification(bot_token, chat_id, error_msg, current_gw)
        sys.exit(1)


if __name__ == "__main__":
    main()
