"""
main.py — نقطة التشغيل الوحيدة للمشروع.

ينسّق تسلسل الاستدعاء الكامل من البداية للنهاية.
التسلسل المفصّل موثّق بـ 10_main.md.

دعم الفرق المتعددة:
- البيانات المشتركة (bootstrap، إصابات، إجماع) تُجلب مرة واحدة.
- كل فريق يُعالَج بشكل مستقل بحلقة منفصلة.
- فشل أحد الفرق لا يوقف معالجة الباقي.
"""

import sys
import os
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime, timezone

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
LAST_SENT_GW_FILE = STATE_DIR / "last_sent_gw.json"

# ─── حد الفحص اليومي: أرسل التقرير فقط لو تبقّى أقل من هذا على الديدلاين ──
DEADLINE_WINDOW_HOURS = 24.0


def _load_last_sent_gw() -> int:
    """
    يقرأ رقم آخر جولة أُرسل تقريرها من ملف الحالة.
    يُرجع 0 لو الملف غير موجود (أول تشغيل).
    """
    try:
        if LAST_SENT_GW_FILE.exists():
            with open(LAST_SENT_GW_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_gw = int(data.get("last_sent_gw", 0))
                logger.info("آخر جولة مُرسَل تقريرها: GW%d", last_gw)
                return last_gw
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("⚠️ خطأ في قراءة last_sent_gw.json — سيُعامَل كأول تشغيل: %s", e)
    return 0


def _save_last_sent_gw(gameweek: int) -> None:
    """
    يحفظ رقم الجولة الأخيرة المُرسَل تقريرها لتفادي التكرار.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LAST_SENT_GW_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sent_gw": gameweek}, f, ensure_ascii=False, indent=2)
        logger.info("تم حفظ last_sent_gw = GW%d", gameweek)
    except OSError as e:
        logger.error("❌ فشل حفظ last_sent_gw.json: %s", e)


def _send_error_notification(
    bot_token: str,
    chat_id: str,
    error_type: str,
    gameweek: object = None,
    team_label: str = "",
) -> None:
    """
    يُرسل رسالة تيليجرام مختصرة عند حدوث خطأ — لا فشل صامت أبداً.
    team_label: وصف الفريق المتأثر (مثل "[فريق محمد]") — اختياري.
    """
    try:
        from telegram_notifier import send_message
        gw_text = f"الجولة {gameweek}" if gameweek else "جولة غير محددة"
        team_text = f" {team_label}" if team_label else ""
        error_text = (
            f"⚠️ *FPL AI Assistant — خطأ في التشغيل*\\n\\n"
            f"فشل إنتاج تقرير{team_text} {gw_text}\\.\n"
            f"السبب: `{error_type}`\\n\\n"
            f"_يُرجى التحقق من سجلات GitHub Actions\\._"
        )
        send_message(bot_token, chat_id, error_text)
    except Exception as e:
        logger.error("فشل حتى إرسال رسالة الخطأ: %s", e)


def _archive_result(decision: dict, gameweek: int, team_id: int) -> None:
    """يحفظ الكائن الكامل بملف أرشيف خاص بكل فريق وجولة."""
    try:
        team_history_dir = HISTORY_DIR / str(team_id)
        team_history_dir.mkdir(parents=True, exist_ok=True)
        archive_path = team_history_dir / f"gw_{gameweek}.json"
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False, indent=2, default=str)
        logger.info(
            "تم أرشفة نتيجة الجولة %d للفريق %d في: %s",
            gameweek, team_id, archive_path
        )
    except Exception as e:
        logger.warning(
            "⚠️ فشل أرشفة نتيجة الجولة %d للفريق %d: %s",
            gameweek, team_id, e
        )


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

    # أرشفة (الجولة 1 لا تنسب لفريق واحد — نحفظها بمجلد مشترك)
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = HISTORY_DIR / "gw_1_initial_squad.json"
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info("تم أرشفة التشكيلة الأولية في: %s", archive_path)
    except Exception as e:
        logger.warning("⚠️ فشل أرشفة التشكيلة الأولية: %s", e)


def _process_single_team(
    team_id: int,
    team_name: str,
    current_gw: int,
    bootstrap_data: dict,
    injury_data: dict,
    consensus_data,
    top_n: int,
    fixtures_data: Optional[list[dict]],
    bot_token: str,
    chat_id: str,
) -> bool:
    """
    يُعالج فريقاً واحداً كاملاً: جلب بياناته، تشغيل محرك القرار،
    بناء التقرير، إرساله، وأرشفته.

    Returns:
        True عند نجاح المعالجة الكاملة، False عند أي خطأ.
    """
    team_label = f"[{team_name}]"
    logger.info("=== بدء معالجة الفريق %s (ID=%d) ===", team_name, team_id)

    try:
        # ─── جلب تشكيلة الفريق وتاريخ الرقائق ───────────────────────────────
        from fpl_client import get_my_team, get_manager_history
        logger.info("%s الخطوة أ: جلب التشكيلة للجولة %d...", team_label, current_gw)
        my_team_data = get_my_team(team_id, current_gw)
        my_picks = my_team_data.get("picks", [])
        entry_history = my_team_data.get("entry_history", {})

        logger.info("%s الخطوة ب: جلب تاريخ الرقائق...", team_label)
        manager_history = get_manager_history(team_id)

        # ─── ملف حالة transfer_planner الخاص بهذا الفريق ────────────────────
        queue_file = STATE_DIR / f"transfer_queue_{team_id}.json"
        logger.info("%s ملف الحالة: %s", team_label, queue_file)

        # ─── تشغيل محرك القرار ───────────────────────────────────────────────
        from decision_engine import run_decision_engine
        logger.info("%s الخطوة ج: تشغيل محرك القرار...", team_label)
        decision = run_decision_engine(
            gameweek=current_gw,
            my_picks=my_picks,
            entry_history=entry_history,
            bootstrap_data=bootstrap_data,
            injury_statuses=injury_data,
            manager_history=manager_history,
            queue_file=queue_file,
            consensus_data=consensus_data,
            total_top_n=top_n,
        )

        # ─── خطوة إضافية مستقلة: اكتشاف الـ Differentials ──────────────────
        # ⚠️ قيد تصميم حرج: هذا القسم معلوماتي واختياري بالكامل.
        # لا يمرر أي لاعب لـ transfer_planner ولا يؤثر إطلاقاً على
        # forced_transfers أو عدد التحويلات المقترحة أو رصيد التحويلات المجانية.
        from differential_finder import find_differentials
        logger.info("%s مسح الـ Differentials (اختياري ومعلوماتي)...", team_label)
        my_squad_ids = {p.get("element") for p in my_picks if p.get("element")}
        diff_suggestions = find_differentials(
            all_players=bootstrap_data.get("elements", []),
            my_squad_ids=my_squad_ids,
            consensus_data=consensus_data,
            top_n_total=top_n,
            injury_statuses=injury_data,
            fixtures_data=fixtures_data,
            current_gw=current_gw,
        )
        decision["differential_suggestions"] = diff_suggestions

        # ─── بناء التقرير وإرساله ─────────────────────────────────────────────
        from report_builder import build_report_text
        from telegram_notifier import send_report
        logger.info("%s الخطوة د: بناء التقرير وإرساله...", team_label)
        report_text = build_report_text(
            decision,
            team_name=team_name,
            team_id=team_id,
        )
        success = send_report(bot_token, chat_id, report_text)
        if not success:
            logger.error(
                "%s ❌ فشل إرسال التقرير — لكن الأرشفة ستتم على أي حال",
                team_label
            )

        # ─── أرشفة النتيجة ────────────────────────────────────────────────────
        _archive_result(decision, current_gw, team_id)

        logger.info("=== انتهت معالجة الفريق %s بنجاح ===", team_name)
        return True

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            "❌ خطأ في معالجة الفريق %s (ID=%d): %s\n%s",
            team_name, team_id, error_msg, traceback.format_exc()
        )
        _send_error_notification(
            bot_token, chat_id, error_msg,
            gameweek=current_gw,
            team_label=team_label,
        )
        return False


def main():
    """نقطة الدخول الرئيسية — تسلسل التشغيل الكامل مع دعم الفرق المتعددة."""

    # ─── الخطوة 1: تحميل الإعدادات ──────────────────────────────────────────
    try:
        from config import config, ConfigError
    except Exception as e:
        logger.critical("❌ فشل تحميل الإعدادات: %s", e)
        sys.exit(1)

    bot_token = config.telegram_bot_token
    chat_id = config.telegram_chat_id
    team_ids = config.fpl_team_ids
    team_names = config.fpl_team_names
    top_n = config.top_n_managers
    injury_url = config.injury_source_url

    logger.info(
        "=== FPL AI Assistant — بدء التشغيل === فرق: %s",
        list(zip(team_ids, team_names))
    )
    current_gw = None

    try:
        # ─── الخطوة 2: جلب البيانات المشتركة (مرة واحدة لجميع الفرق) ─────────
        from fpl_client import get_bootstrap_static, get_current_gameweek, get_fixtures
        logger.info("الخطوة 2: جلب bootstrap-static وجدول المباريات (مشترك لجميع الفرق)...")
        bootstrap_data = get_bootstrap_static()
        current_gw = get_current_gameweek(bootstrap_data)

        fixtures_data = None
        try:
            fixtures_data = get_fixtures()
            logger.info("تم جلب %d مباراة من جدول المباريات (مشترك)", len(fixtures_data))
        except Exception as e:
            logger.warning("⚠️ تعذّر جلب جدول المباريات: %s — سيتم التقدير بـ FDR محايد", e)

        # ─── الخطوة 3: تحديد الحالة العامة ──────────────────────────────────
        if current_gw is None:
            # الموسم انتهى
            logger.info("الموسم انتهى — لا توجد جولة قادمة")
            from report_builder import build_season_ended_message
            from telegram_notifier import send_message
            send_message(bot_token, chat_id, build_season_ended_message())
            return

        logger.info("الجولة الحالية/القادمة: GW%d", current_gw)

        # ─── الخطوة 3أ: فحص الديدلاين — هل حان وقت الإرسال؟ ─────────────────
        from fpl_client import get_next_gameweek_deadline
        deadline_utc = get_next_gameweek_deadline(bootstrap_data)

        if deadline_utc is not None:
            now_utc = datetime.now(timezone.utc)
            hours_remaining = (deadline_utc - now_utc).total_seconds() / 3600

            if hours_remaining > DEADLINE_WINDOW_HOURS:
                logger.info(
                    "⏳ لم يحن وقت الإرسال بعد — متبقٍّ %.1f ساعة على ديدلاين GW%d "
                    "(الحد المطلوب: %g ساعة). إيقاف التشغيل.",
                    hours_remaining, current_gw, DEADLINE_WINDOW_HOURS
                )
                sys.exit(0)  # خروج طبيعي — ليس خطأً
            else:
                logger.info(
                    "✅ الديدلاين قريب — متبقٍّ %.1f ساعة على GW%d. المتابعة بالتحليل.",
                    hours_remaining, current_gw
                )
        else:
            # لو فشل استخراج الديدلاين — نكمل بدون فحص (أفضل من التوقف)
            logger.warning("⚠️ تعذّر استخراج الديدلاين — سيتم التشغيل بدون فحص الوقت.")

        if current_gw == 1 and not INITIAL_SQUAD_FLAG.exists():
            # الجولة الأولى — بناء تشكيلة أولية (مشتركة — لا تكرار لكل فريق)
            logger.info("GW1 — مسار التشكيلة الأولية")
            _handle_gw1_initial_squad(bootstrap_data, bot_token, chat_id)
            logger.info("=== تم إنهاء تشغيل GW1 بنجاح ===")
            return

        # ─── الخطوة 4: جلب حالة الإصابات (مشتركة) ──────────────────────────
        from injuries_source import get_all_injury_statuses
        logger.info("الخطوة 4: جلب حالة الإصابات (مشتركة)...")
        injury_data = get_all_injury_statuses(bootstrap_data, injury_url)

        # ─── الخطوة 5: جلب إجماع أفضل N (مشترك، GW≥2 فقط) ─────────────────
        consensus_data = None
        if current_gw > 1:
            from top_managers import (
                get_top_n_manager_ids,
                get_top_n_squads,
                calculate_consensus,
            )
            logger.info(
                "الخطوة 5: جلب أفضل %d مدير للجولة %d (مشترك)...",
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
                logger.warning(
                    "⚠️ فشل جلب بيانات إجماع أفضل N: %s — المتابعة بدونها", e
                )

    except Exception as e:
        # فشل في جلب البيانات المشتركة — لا يمكن المتابعة
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            "❌ خطأ فادح في جلب البيانات المشتركة: %s\n%s",
            error_msg, traceback.format_exc()
        )
        _send_error_notification(bot_token, chat_id, error_msg, current_gw)
        sys.exit(1)

    # ─── الخطوة 5أ: فحص last_sent_gw — هل أُرسل تقرير هذه الجولة مسبقاً؟ ──
    last_gw = _load_last_sent_gw()
    if current_gw <= last_gw:
        logger.info(
            "ℹ️ تقرير GW%d أُرسل مسبقاً (last_sent_gw=%d) — لا داعي للإرسال مجدداً. إيقاف.",
            current_gw, last_gw
        )
        sys.exit(0)  # خروج طبيعي — ليس خطأً

    # ─── الخطوة 6: حلقة الفرق — كل فريق بشكل مستقل ─────────────────────────
    logger.info(
        "=== بدء معالجة %d فريق (GW%d) ===",
        len(team_ids), current_gw
    )

    results = {}
    for team_id, team_name in zip(team_ids, team_names):
        success = _process_single_team(
            team_id=team_id,
            team_name=team_name,
            current_gw=current_gw,
            bootstrap_data=bootstrap_data,
            injury_data=injury_data,
            consensus_data=consensus_data,
            top_n=top_n,
            fixtures_data=fixtures_data,
            bot_token=bot_token,
            chat_id=chat_id,
        )
        results[team_name] = "✅ نجاح" if success else "❌ فشل"

    # ─── ملخص نهائي + حفظ last_sent_gw ──────────────────────────────────────
    logger.info("=== ملخص التشغيل — GW%d ===", current_gw)
    for name, status in results.items():
        logger.info("  %s: %s", name, status)

    failed = [n for n, s in results.items() if "فشل" in s]
    if failed:
        logger.error("❌ فشل معالجة: %s", ", ".join(failed))
        sys.exit(1)
    else:
        # نحفظ last_sent_gw فقط لو نجح الإرسال لكل الفرق
        _save_last_sent_gw(current_gw)
        logger.info("=== تم إنهاء التشغيل بنجاح لجميع الفرق ===")


if __name__ == "__main__":
    main()

