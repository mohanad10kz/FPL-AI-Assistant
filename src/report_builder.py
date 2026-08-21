"""
report_builder.py — تحويل مخرجات decision_engine لنص تقرير عربي منسّق.

النص جاهز للإرسال مباشرة عبر Telegram Bot API (Markdown).
القاعدة: التوصيات صيغة اقتراح لا أمر. لا أقسام فارغة بالتقرير.
التصميم: منسّق بعناية للقراءة من اليمين لليسار (RTL) بدون تشوهات BiDi.
"""

import logging

logger = logging.getLogger(__name__)

# ── حد طول الرسالة بتيليجرام (4096 حرف) ───────────────────────────────────
TELEGRAM_MAX_LENGTH = 4096
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def build_report_text(decision_data: dict, team_name: str = "", team_id: int = 0) -> str:
    """
    يبني نص التقرير الكامل من مخرجات decision_engine.run_decision_engine().

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
        sections.append(f"📊 *تقرير الجولة #{gw}*\n👤 *الفريق:* {display_name}\n{DIVIDER}")
    else:
        sections.append(f"📊 *تقرير الجولة #{gw}*\n{DIVIDER}")

    # ── قسم 1: التحويلات المنفَّذة الآن ──────────────────────────────────────
    if forced_transfers:
        header = f"🔄 *التحويلات المقترحة ({len(forced_transfers)}):*"
        lines = [header]
        for t in forced_transfers:
            cost_note = ""
            if t.get("cost_in_points", 0) < 0:
                cost_note = f" ⚠️ _(خصم {abs(t['cost_in_points'])} نقطة)_"
            lines.append(f"• 🔻 خروج: *{t.get('out', '؟')}*")
            lines.append(f"  🔺 دخول: *{t.get('in', '؟')}*{cost_note}")
            if t.get("reason"):
                lines.append(f"  📌 السبب: _{t['reason']}_")
        sections.append("\n".join(lines))

    # ── قسم 2: التحويلات المؤجلة ─────────────────────────────────────────────
    if still_pending:
        lines = [f"⏳ *تحويلات مؤجَّلة للجولة القادمة ({len(still_pending)}):*"]
        for t in still_pending:
            lines.append(f"• 👤 *{t.get('out', '؟')}*")
            if t.get("reason"):
                lines.append(f"  📌 السبب: _{t['reason']}_")
        lines.append("  _(لا داعي لأي خصم نقاط الآن — سيُعاد تقييمها بالجولة القادمة)_")
        sections.append("\n".join(lines))

    # ── قسم 3: لاعبون للمراجعة اليدوية ──────────────────────────────────────
    if flagged_players:
        lines = [f"⚠️ *لاعبون يحتاجون مراجعتك ({len(flagged_players)}):*"]
        for p in flagged_players:
            lines.append(f"• 👤 *{p.get('name', '؟')}*")
            if p.get("reason"):
                lines.append(f"  📌 الملاحظة: _{p['reason']}_")
        lines.append("  _(إشارة غير مؤكدة — القرار النهائي لك)_")
        sections.append("\n".join(lines))

    # ── قسم 4: الكابتن ───────────────────────────────────────────────────────
    captain_lines = ["👑 *شارة القيادة:*"]
    if captain:
        captain_lines.append(f"• 🏆 الكابتن المقترح: *{captain}*")
    if vice_captain:
        captain_lines.append(f"• 🥈 نائب الكابتن: *{vice_captain}*")
    if len(captain_lines) > 1:
        sections.append("\n".join(captain_lines))

    # ── قسم 5: اقتراح الرقاقة ────────────────────────────────────────────────
    if chip_suggestion:
        chip_name = chip_suggestion.get("chip")
        recommended = chip_suggestion.get("recommended", False)
        chip_reason = chip_suggestion.get("reason", "")

        chip_lines = ["🃏 *اقتراح الرقاقة:*"]
        if recommended and chip_name:
            chip_lines.append("• 🎯 الحالة: *مُقترحة*")
            chip_lines.append(f"• 🏷️ النوع: *{chip_name}*")
            if chip_reason:
                chip_lines.append(f"• 📌 السبب: _{chip_reason}_")
        else:
            chip_lines.append("• 🎯 الحالة: *غير مستحسنة بهذه الجولة*")
            if chip_reason:
                chip_lines.append(f"• 📌 السبب: _{chip_reason}_")
        sections.append("\n".join(chip_lines))

    # ── قسم 6: ملخص مالي ─────────────────────────────────────────────────────
    financial_lines = ["💰 *الوضع المالي ورصيد التحويلات:*"]
    financial_lines.append(f"• 💵 الرصيد المتبقي في البنك: *£{bank_after:.1f}M*")
    financial_lines.append(f"• 🔄 التحويلات المجانية المتبقية: *{free_transfers}*")
    if transfers_cost < 0:
        financial_lines.append(f"• 📉 خصم النقاط المتوقع: *⚠️ خصم {abs(transfers_cost)} نقطة*")
    else:
        financial_lines.append("• 📉 خصم النقاط المتوقع: *لا يوجد (مجاني)*")
    sections.append("\n".join(financial_lines))

    # ── قسم 7: لاعبون يستحقون المتابعة (Differentials — اختياري) ──────────────
    differential_suggestions = decision_data.get("differential_suggestions", [])
    if differential_suggestions:
        diff_lines = [f"💎 *لاعبون يستحقون المتابعة (Differentials) ({len(differential_suggestions)}):*"]
        for p in differential_suggestions:
            diff_lines.append(f"• ⭐ *{p.get('name', '؟')}* ({p.get('position', 'MID')})")
            diff_lines.append(
                f"  💵 السعر: £{p.get('price', 0.0):.1f}M | 📈 الامتلاك: {p.get('ownership', 0.0):.1f}% | ⚡ الفورم: {p.get('form', 0.0):.1f}"
            )
            if p.get("reason"):
                diff_lines.append(f"  📌 السبب: _{p['reason']}_")
        diff_lines.append("  _(اختياري بالكامل — لا يستهلك تحويلاتك المخططة)_")
        sections.append("\n".join(diff_lines))

    # ── تذييل إلزامي ─────────────────────────────────────────────────────────
    sections.append(f"{DIVIDER}\n⚡ _تقرير تحليلي استشاري — القرار النهائي لك دائماً._")

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
        f"📊 *FPL AI Assistant*\n"
        f"{DIVIDER}\n\n"
        f"🏁 _انتهى الموسم الحالي — لا توجد جولات قادمة._\n\n"
        f"ترقّب بداية الموسم الجديد! ⚽"
    )
