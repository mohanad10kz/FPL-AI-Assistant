"""
config.py — نقطة مركزية لقراءة كل الإعدادات والأسرار.
لا يوجد ملف آخر بالمشروع يقرأ متغيرات بيئة مباشرة — الكل يستورد من هنا.
"""

import os
import re
import logging
from dotenv import load_dotenv

# تحميل ملف .env محلياً (على GitHub Actions تأتي القيم من Secrets مباشرة)
load_dotenv()

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """خطأ يُرمى عند نقص إعداد إلزامي أو قيمة غير صالحة."""
    pass


class Config:
    """
    كائن إعدادات المشروع — كل الوحدات تستورد instance واحد من هنا:
        from config import config
    """

    def __init__(self):
        self._load_and_validate()

    def _load_and_validate(self):
        """تحميل والتحقق من جميع المتغيرات البيئية."""
        errors = []

        # ─── FPL_TEAM_ID (إلزامي، رقمي) ───────────────────────────────────
        team_id_raw = os.getenv("FPL_TEAM_ID", "").strip()
        if not team_id_raw:
            errors.append(
                "FPL_TEAM_ID مفقود — أضف رقم فريقك في ملف .env أو GitHub Secrets"
            )
        elif not team_id_raw.isdigit():
            errors.append(
                f"FPL_TEAM_ID يجب أن يكون رقماً صحيحاً، القيمة الحالية: '{team_id_raw}'"
            )
        else:
            self.fpl_team_id: int = int(team_id_raw)

        # ─── TELEGRAM_BOT_TOKEN (إلزامي، يطابق <digits>:<string>) ───────────
        bot_token_raw = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not bot_token_raw:
            errors.append(
                "TELEGRAM_BOT_TOKEN مفقود — احصل عليه من @BotFather وأضفه في .env أو GitHub Secrets"
            )
        elif not re.match(r"^\d+:[A-Za-z0-9_-]+$", bot_token_raw):
            errors.append(
                "TELEGRAM_BOT_TOKEN لا يطابق الصيغة المتوقعة (<digits>:<string>)"
                " — تحقق من القيمة في .env"
            )
        else:
            self.telegram_bot_token: str = bot_token_raw

        # ─── TELEGRAM_CHAT_ID (إلزامي، رقمي — قد يكون سالباً لو مجموعة) ──
        chat_id_raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not chat_id_raw:
            errors.append(
                "TELEGRAM_CHAT_ID مفقود — راجع README لطريقة استخراجه وأضفه في .env"
            )
        elif not re.match(r"^-?\d+$", chat_id_raw):
            errors.append(
                f"TELEGRAM_CHAT_ID يجب أن يكون رقماً صحيحاً (موجب أو سالب)، القيمة: '{chat_id_raw}'"
            )
        else:
            self.telegram_chat_id: str = chat_id_raw  # نحتفظ به كـ str لأن API يقبله كذلك

        # ─── INJURY_SOURCE_URL (اختياري، قيمة افتراضية) ────────────────────
        injury_url = os.getenv(
            "INJURY_SOURCE_URL",
            "https://www.premierinjuries.com/injury-table.php"
        ).strip()
        if injury_url and not injury_url.startswith(("http://", "https://")):
            errors.append(
                f"INJURY_SOURCE_URL لا يبدأ بـ http:// أو https://, القيمة: '{injury_url}'"
            )
        else:
            self.injury_source_url: str = injury_url

        # ─── TOP_N_MANAGERS (اختياري، افتراضي = 10، رقم صحيح موجب) ─────────
        top_n_raw = os.getenv("TOP_N_MANAGERS", "10").strip()
        try:
            top_n = int(top_n_raw)
            if top_n <= 0:
                raise ValueError
            self.top_n_managers: int = top_n
        except ValueError:
            errors.append(
                f"TOP_N_MANAGERS يجب أن يكون رقماً صحيحاً موجباً، القيمة: '{top_n_raw}'"
            )

        # ─── رمي الأخطاء المجمّعة دفعة واحدة ────────────────────────────────
        if errors:
            error_list = "\n".join(f"  • {e}" for e in errors)
            raise ConfigError(
                f"\n{'='*60}\n"
                f"❌ خطأ في الإعدادات — يرجى تصحيح المشاكل التالية:\n"
                f"{error_list}\n"
                f"{'='*60}\n"
                f"مرجع: انسخ .env.example إلى .env وأضف قيمك الحقيقية."
            )

        logger.info("✅ Config loaded successfully (team_id=%s, top_n=%s)",
                    self.fpl_team_id, self.top_n_managers)

    def __repr__(self) -> str:
        return (
            f"Config("
            f"fpl_team_id={self.fpl_team_id}, "
            f"top_n_managers={self.top_n_managers}, "
            f"injury_source_url='{self.injury_source_url}', "
            f"telegram_chat_id='{self.telegram_chat_id}')"
        )


# ─── Singleton: كل الوحدات تستورد هذا الكائن مباشرة ──────────────────────────
# استخدام: from config import config
try:
    config = Config()
except ConfigError as e:
    # نعيد رمي الخطأ ليُسجَّل بوضوح ويوقف التشغيل فوراً
    raise
