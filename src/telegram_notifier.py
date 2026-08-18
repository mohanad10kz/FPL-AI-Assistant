"""
telegram_notifier.py — إرسال التقرير النهائي عبر Telegram Bot API.

نقطة الخروج الوحيدة للمشروع تجاه المستخدم.
المسؤولية: آلية الإرسال فقط — المحتوى يُبنى من report_builder.py.
"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# ── ثوابت ──────────────────────────────────────────────────────────────────
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
SEND_MESSAGE_ENDPOINT = "/sendMessage"
MAX_MESSAGE_LENGTH = 4096   # حد Telegram Bot API
HTTP_TIMEOUT = 15           # ثانية


def _split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """
    يقسّم نص طويل لأجزاء تحت الحد الأقصى مع الحفاظ على الأسطر كاملة.
    يتفادى قطع الكلمات في المنتصف.

    Args:
        text: النص الكامل
        max_length: الحد الأقصى لكل جزء (افتراضي 4096)

    Returns:
        قائمة أجزاء نصية، كل جزء ≤ max_length
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    lines = text.split("\n")
    current_part = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1  # +1 للسطر الجديد
        if current_length + line_len > max_length and current_part:
            parts.append("\n".join(current_part))
            current_part = [line]
            current_length = line_len
        else:
            current_part.append(line)
            current_length += line_len

    if current_part:
        parts.append("\n".join(current_part))

    logger.info("تم تقسيم الرسالة إلى %d جزء", len(parts))
    return parts


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
) -> bool:
    """
    يُرسل رسالة واحدة عبر Telegram Bot API.

    Args:
        bot_token: توكن البوت
        chat_id: معرّف المحادثة
        text: نص الرسالة (≤ 4096 حرف)
        parse_mode: "Markdown" أو "HTML"

    Returns:
        True عند نجاح الإرسال، False عند الفشل
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        response = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        data = response.json()

        if response.ok and data.get("ok"):
            msg_id = data.get("result", {}).get("message_id", "؟")
            logger.info("✅ تم إرسال الرسالة بنجاح (message_id=%s)", msg_id)
            return True
        else:
            error_desc = data.get("description", "خطأ غير معروف")
            error_code = data.get("error_code", "")
            logger.error(
                "❌ فشل إرسال الرسالة — كود الخطأ: %s | التفاصيل: %s",
                error_code, error_desc
            )
            print(f"[TELEGRAM ERROR] code={error_code}: {error_desc}")
            return False

    except requests.exceptions.Timeout:
        logger.error("❌ انتهت مهلة اتصال Telegram API (timeout=%ds)", HTTP_TIMEOUT)
        print(f"[TELEGRAM ERROR] Connection timeout after {HTTP_TIMEOUT}s")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.error("❌ فشل الاتصال بـ Telegram API: %s", e)
        print(f"[TELEGRAM ERROR] Connection error: {e}")
        return False
    except Exception as e:
        logger.error("❌ خطأ غير متوقع عند إرسال الرسالة: %s", e)
        print(f"[TELEGRAM ERROR] Unexpected error: {e}")
        return False


def send_report(
    bot_token: str,
    chat_id: str,
    message_text: str,
) -> bool:
    """
    يُرسل التقرير كاملاً — يُقسَّم تلقائياً لو تجاوز 4096 حرف.

    الدالة الرئيسية المستخدَمة من main.py.

    Args:
        bot_token: توكن البوت من TELEGRAM_BOT_TOKEN
        chat_id: معرّف المحادثة من TELEGRAM_CHAT_ID
        message_text: نص التقرير من report_builder.build_report_text()

    Returns:
        True لو كل الأجزاء أُرسلت بنجاح، False لو فشل أي جزء
    """
    parts = _split_message(message_text)
    all_success = True

    for i, part in enumerate(parts, 1):
        if len(parts) > 1:
            # إضافة ترقيم لو الرسالة مقسّمة
            part_header = f"_\\[جزء {i}/{len(parts)}\\]_\n\n"
            part = part_header + part

        success = send_message(bot_token, chat_id, part)
        if not success:
            all_success = False
            logger.error(
                "❌ فشل إرسال الجزء %d/%d — تحقق من TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID",
                i, len(parts)
            )

    if all_success:
        logger.info("✅ كل أجزاء التقرير (%d) وصلت بنجاح", len(parts))
    else:
        logger.error(
            "❌ بعض أجزاء التقرير فشلت — تحقق من السجلات أعلاه"
        )

    return all_success


def send_test_message(bot_token: str, chat_id: str) -> bool:
    """
    يُرسل رسالة اختبار بسيطة للتحقق من صحة الإعداد.

    استخدم هذه الدالة أول مرة للتأكد أن البوت مضبوط بشكل صحيح
    قبل الاعتماد على الجدولة الأسبوعية.

    Returns:
        True لو وصلت رسالة الاختبار بنجاح
    """
    test_text = (
        "🤖 *FPL AI Assistant — رسالة اختبار*\n\n"
        "✅ الإعداد صحيح\\! البوت يعمل بشكل طبيعي\\.\n\n"
        "_هذه رسالة اختبار تلقائية — يمكنك تجاهلها\\._"
    )
    logger.info("إرسال رسالة اختبار إلى chat_id=%s", chat_id)
    return send_message(bot_token, chat_id, test_text)
