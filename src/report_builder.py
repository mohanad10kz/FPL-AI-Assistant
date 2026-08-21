"""
report_builder.py — تحويل مخرجات decision_engine لنص تقرير عربي منسّق.

النص جاهز للإرسال مباشرة عبر Telegram Bot API (Markdown).
القاعدة: التوصيات صيغة اقتراح لا أمر. لا أقسام فارغة بالتقرير.
"""

import logging

logger = logging.getLogger(__name__)

# ── حد طول الرسالة بتيليجرام (4096 حرف) ───────────────────────────────────
TELEGRAM_MAX_LENGTH = 4096


def build_report_text(decision_data: dict, team_name: str = "", team_id: int = 0) -> str:
    """
    يبني نص التقرير الكامل من مخرجات decision_engine.run_decision_engine().

    الترتيب محدد بـ 08_report_builder.md — لا تغيّر الترتيب.

    Args:
        decision_data: الكائن النهائي من decision_engine.run_decision_engine()
        team_name: اسم الفريق لعرضه بعنوان التقرير ("" = لا فريق محدد)
        team_id: رقم الفريق (يُستخدم كاحتياطي لو لم يُعطَب team_name)

    Returns:
        نص Markdown جاهز للإرسال عبر تيليجرام
    """
    gw = decision_data.get("gameweek", "؟")
    forced_transfers = decision_data.get("forced_transfers", [])
    still_pending = decision_data.get("still_pending", [])
    flagged_players = decision_data.get("flagged_players", [])
    captain = decision_data.get("captain")
    vice_captain = decision_data.get("vice_captain")
    chip_suggestion = decision_data.get("chip_suggestion", {})
    bank_after = decision_data.get("bank_after", 0.0)
    free_transfers = decision_data.get("free_transfers_remaining", 0)
    transfers_cost = decision_data.get("transfers_cost", 0)

    # بناء اسم الفريق للعنوان
    display_name = team_name if team_name else (f"فريق {team_id}" if team_id else "")

    sections = []

    # ── رأس التقرير ──────────────────────────────────────────────────────────
    if display_name:
        sections.append(f"📊 *\\[{display_name}\\] تقرير الجولة \\#{gw}*")
    else:
        sections.append(f"📊 *تقرير الجولة \\#{gw}*")
    sections.append("─" * 30)

    # ── قسم 1: التحويلات المنفَّذة الآن ──────────────────────────────────────
    if forced_transfers:
        header = f"✅ *التحويلات المقترحة الآن ({len(forced_transfers)}):*"
        lines = [header]
        for t in forced_transfers:
            cost_note = ""
            if t.get("cost_in_points", 0) < 0:
                cost_note = f" ⚠️ _خصم {abs(t['cost_in_points'])} نقطة_"
            lines.append(
                f"  • إخراج: *{t.get('out', '؟')}* ← إدخال: *{t.get('in', '؟')}*{cost_note}"
            )
            if t.get("reason"):
                lines.append(f"    _السبب: {t['reason']}_")
        sections.append("\n".join(lines))

    # ── قسم 2: التحويلات المؤجلة ─────────────────────────────────────────────
    if still_pending:
        lines = [f"⏳ *تحويلات مؤجَّلة — سيُعاد تقييمها الجولة القادمة ({len(still_pending)}):*"]
        for t in still_pending:
            lines.append(f"  • *{t.get('out', '؟')}*: {t.get('reason', '')}")
        lines.append("  _\\(لا داعي لأي خصم نقاط الآن — سيُعاد تقييمها بالجولة القادمة\\)_")
        sections.append("\n".join(lines))

    # ── قسم 3: لاعبون للمراجعة اليدوية ──────────────────────────────────────
    if flagged_players:
        lines = ["⚠️ *لاعبون يحتاجون مراجعتك \\(إشارة غير مؤكدة — القرار لك\\):*"]
        for p in flagged_players:
            lines.append(f"  • *{p.get('name', '؟')}*: {p.get('reason', '')}")
        sections.append("\n".join(lines))

    # ── قسم 4: الكابتن ───────────────────────────────────────────────────────
    captain_section = []
    if captain:
        captain_section.append(f"🏆 *الكابتن المقترح:* {captain}")
    if vice_captain:
        captain_section.append(f"🥈 *نائب الكابتن المقترح:* {vice_captain}")
    if captain_section:
        sections.append("\n".join(captain_section))

    # ── قسم 5: اقتراح الرقاقة ────────────────────────────────────────────────
    if chip_suggestion:
        chip_name = chip_suggestion.get("chip")
        recommended = chip_suggestion.get("recommended", False)
        chip_reason = chip_suggestion.get("reason", "")

        if recommended and chip_name:
            chip_text = (
                f"🎯 *اقتراح رقاقة:* نعم\n"
                f"  النوع: *{chip_name}*\n"
                f"  _السبب: {chip_reason}_"
            )
        else:
            chip_text = f"🎯 *اقتراح رقاقة:* لا \\— {chip_reason}"
        sections.append(chip_text)

    # ── قسم 6: ملخص مالي ─────────────────────────────────────────────────────
    financial_lines = []
    financial_lines.append(f"💰 *الرصيد المتوقع بعد التحويلات:* £{bank_after:.1f}م")
    financial_lines.append(f"🔄 *التحويلات المجانية المتبقية:* {free_transfers}")
    if transfers_cost < 0:
        financial_lines.append(f"❗ *خصم نقاط متوقع:* {transfers_cost} نقطة")
    else:
        financial_lines.append("❗ *خصم نقاط متوقع:* لا يوجد")
    sections.append("\n".join(financial_lines))

    # ── تذييل إلزامي ─────────────────────────────────────────────────────────
    sections.append("─" * 30)
    sections.append(
        "_⚡ هذا تقرير اقتراح للمراجعة فقط — القرار النهائي لك دائماً._"
    )

    report = "\n\n".join(sections)

    # ── تحقق من الطول ────────────────────────────────────────────────────────
    if len(report) > TELEGRAM_MAX_LENGTH:
        logger.warning(
            "⚠️ التقرير أطول من الحد المسموح (%d حرف) — سيُقطع",
            TELEGRAM_MAX_LENGTH
        )
        # قطع بأمان مع إشارة للمستخدم
        report = report[:TELEGRAM_MAX_LENGTH - 50] + "\n\n_...تم تقليص التقرير بسبب الطول._"

    logger.info("تم بناء التقرير: %d حرف", len(report))
    return report


def build_season_ended_message() -> str:
    """يُرجع رسالة نهاية الموسم لو لا توجد جولة قادمة."""
    return (
        "📊 *FPL AI Assistant*\n\n"
        "🏁 _انتهى الموسم الحالي — لا توجد جولات قادمة._\n"
        "ترقّب بداية الموسم الجديد!"
    )
