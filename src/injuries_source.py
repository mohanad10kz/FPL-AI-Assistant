"""
injuries_source.py — تحديد حالة كل لاعب (سليم/مشكوك/مصاب/موقوف).

مصدران بالترتيب من الأكثر موثوقية:
1. FPL API نفسه (أساسي ومفضّل — رسمي، لا يحتاج طلب HTTP إضافي).
2. مصدر خارجي عبر Scraping (طبقة إضافية اختيارية لمزيد من التفاصيل).

بيانات FPL الرسمية دائماً لها الأولوية عند التعارض.
"""

import logging
import requests
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── ثوابت التصنيف ──────────────────────────────────────────────────────────
# تعيين حرف status من FPL API إلى تصنيف موحّد
FPL_STATUS_MAP = {
    "a": "fit",          # available
    "d": "doubtful",     # doubtful
    "i": "injured",      # injured
    "s": "suspended",    # suspended
    "u": "injured",      # unavailable (نعامله كمصاب)
}

# تحويل chance_of_playing إلى تصنيف موحّد (إذا لم يكن هناك status صريح)
CHANCE_TO_STATUS = {
    0:   "injured",
    25:  "injured",
    50:  "doubtful",
    75:  "doubtful",
    100: "fit",
}

HTTP_TIMEOUT = 10  # ثواني


# ───────────────────────────────────────────────────────────────────────────
# 1. المصدر الأساسي: FPL API نفسه
# ───────────────────────────────────────────────────────────────────────────

def get_injury_status_from_fpl(bootstrap_data: dict) -> dict[int, dict]:
    """
    يبني قاموس حالات الإصابة مباشرة من بيانات bootstrap-static.
    لا يُجري أي طلب HTTP إضافي — يستخدم البيانات الموجودة أصلاً.

    Args:
        bootstrap_data: النتيجة المباشرة من fpl_client.get_bootstrap_static()

    Returns:
        dict بمفتاح player_id:
        {
            player_id: {
                "status": "fit"|"doubtful"|"injured"|"suspended",
                "chance_of_playing": int (0-100),
                "note": str,
                "source": "fpl_official"
            }
        }
    """
    elements = bootstrap_data.get("elements", [])
    result: dict[int, dict] = {}

    for player in elements:
        player_id = player.get("id")
        if player_id is None:
            continue

        raw_status = player.get("status", "a")  # افتراضي: available
        chance = player.get("chance_of_playing_next_round")  # None أو 0-100
        news = player.get("news", "").strip() or ""

        # تحديد الحالة
        if raw_status in FPL_STATUS_MAP:
            status = FPL_STATUS_MAP[raw_status]
        elif chance is not None:
            status = CHANCE_TO_STATUS.get(chance, "fit")
        else:
            status = "fit"

        # تحديد نسبة اللعب
        if chance is None:
            # لو لا توجد شكوك، نفترض 100%
            chance_of_playing = 100 if status == "fit" else 0
        else:
            chance_of_playing = chance

        result[player_id] = {
            "status": status,
            "chance_of_playing": chance_of_playing,
            "note": news,
            "source": "fpl_official",
        }

    logger.info(
        "FPL injury data: %d لاعب مُحلَّل، منهم %d مشكوك/مصاب/موقوف",
        len(result),
        sum(1 for v in result.values() if v["status"] != "fit")
    )
    return result


# ───────────────────────────────────────────────────────────────────────────
# 2. المصدر الثانوي: موقع خارجي (اختياري)
# ───────────────────────────────────────────────────────────────────────────

def get_injury_status_from_external_source(url: str) -> dict[str, dict]:
    """
    يجلب بيانات إصابات إضافية من مصدر خارجي عبر Scraping.
    مفتاح القاموس هو اسم اللاعب (web_name تقريبي) لأن الـ player_id غير متاح خارجياً.

    ⚠️ هذه الطبقة اختيارية — فشلها لا يوقف البرنامج.
    يُستخدم `try/except` شامل ويُسجَّل تحذير ويُعاد {} عند أي خطأ.

    Args:
        url: رابط صفحة الإصابات الخارجية (من config.injury_source_url)

    Returns:
        dict بمفتاح player_name (str):
        {
            "player_name": {
                "status": "fit"|"doubtful"|"injured"|"suspended",
                "chance_of_playing": int,
                "note": str,
                "source": "external"
            }
        }
    """
    try:
        logger.info("جلب بيانات إصابات من مصدر خارجي: %s", url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")
        result: dict[str, dict] = {}

        # محاولة تحليل جداول HTML شائعة (بنية عامة مرنة)
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # تخطي صف العناوين
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                # محاولة استخراج الاسم والحالة (البنية تختلف بين المواقع)
                player_name = cells[0].get_text(strip=True)
                if not player_name:
                    continue

                status_text = ""
                chance_text = ""
                note_text = ""

                # بحث عن خلية تحوي حالة معروفة
                for cell in cells[1:]:
                    text = cell.get_text(strip=True).lower()
                    if any(kw in text for kw in ["injured", "doubt", "suspend", "fit", "%"]):
                        if "%" in text:
                            chance_text = text
                        elif "injured" in text or "out" in text:
                            status_text = "injured"
                        elif "doubt" in text:
                            status_text = "doubtful"
                        elif "suspend" in text:
                            status_text = "suspended"
                        elif "fit" in text or "available" in text:
                            status_text = "fit"
                        else:
                            note_text = text

                # استخراج النسبة
                chance = 100
                if chance_text:
                    import re
                    m = re.search(r"(\d+)\s*%", chance_text)
                    if m:
                        chance = int(m.group(1))
                        if not status_text:
                            status_text = CHANCE_TO_STATUS.get(
                                min(CHANCE_TO_STATUS.keys(), key=lambda k: abs(k - chance)),
                                "fit"
                            )

                if not status_text:
                    status_text = "fit"

                result[player_name] = {
                    "status": status_text,
                    "chance_of_playing": chance,
                    "note": note_text,
                    "source": "external",
                }

        logger.info("بيانات خارجية: %d لاعب جُلب من المصدر الخارجي", len(result))
        return result

    except requests.exceptions.RequestException as e:
        logger.warning("⚠️ فشل الاتصال بالمصدر الخارجي (%s): %s — سيُكتفى ببيانات FPL الرسمية", url, e)
        return {}
    except Exception as e:
        logger.warning("⚠️ خطأ في تحليل المصدر الخارجي (%s): %s — سيُكتفى ببيانات FPL الرسمية", url, e)
        return {}


# ───────────────────────────────────────────────────────────────────────────
# 3. دمج المصدرين
# ───────────────────────────────────────────────────────────────────────────

def merge_injury_data(
    fpl_data: dict[int, dict],
    external_data: dict[str, dict],
    elements: Optional[list[dict]] = None,
) -> dict[int, dict]:
    """
    يدمج بيانات FPL الرسمية مع البيانات الخارجية.
    بيانات FPL دائماً لها الأولوية عند التعارض.

    Args:
        fpl_data: مخرجات get_injury_status_from_fpl()
        external_data: مخرجات get_injury_status_from_external_source()
        elements: قائمة اللاعبين من bootstrap-static (لمطابقة الأسماء)

    Returns:
        قاموس موحّد بمفتاح player_id مع note مدمجة إن وجدت
    """
    merged = dict(fpl_data)  # نسخة عميقة كافية هنا

    if not external_data or not elements:
        return merged

    # بناء خريطة اسم → player_id لمطابقة الأسماء
    name_to_id: dict[str, int] = {}
    for player in elements:
        pid = player.get("id")
        web_name = player.get("web_name", "").lower()
        full_name = (
            (player.get("first_name", "") + " " + player.get("second_name", ""))
            .strip()
            .lower()
        )
        if pid:
            if web_name:
                name_to_id[web_name] = pid
            if full_name:
                name_to_id[full_name] = pid

    enriched = 0
    for ext_name, ext_info in external_data.items():
        # محاولة مطابقة الاسم
        pid = name_to_id.get(ext_name.lower())
        if pid and pid in merged:
            # إضافة ملاحظة خارجية فقط إذا كانت FPL فارغة
            if not merged[pid].get("note") and ext_info.get("note"):
                merged[pid]["note"] = ext_info["note"]
                merged[pid]["external_note"] = True
                enriched += 1

    logger.info("تم إثراء %d لاعب ببيانات المصدر الخارجي", enriched)
    return merged


# ───────────────────────────────────────────────────────────────────────────
# 4. الدالة الرئيسية للاستخدام من باقي الوحدات
# ───────────────────────────────────────────────────────────────────────────

def get_all_injury_statuses(
    bootstrap_data: dict,
    injury_source_url: Optional[str] = None,
) -> dict[int, dict]:
    """
    نقطة دخول واحدة لجلب وضع الإصابات لكل اللاعبين.

    Args:
        bootstrap_data: من fpl_client.get_bootstrap_static()
        injury_source_url: رابط المصدر الخارجي (اختياري)

    Returns:
        قاموس {player_id: {"status", "chance_of_playing", "note", "source"}}
    """
    fpl_data = get_injury_status_from_fpl(bootstrap_data)

    if injury_source_url:
        external_data = get_injury_status_from_external_source(injury_source_url)
        elements = bootstrap_data.get("elements", [])
        return merge_injury_data(fpl_data, external_data, elements)

    return fpl_data


def get_injury_status(player_id: int, all_statuses: dict[int, dict]) -> dict:
    """
    يُرجع حالة إصابة لاعب معين.

    Args:
        player_id: معرّف اللاعب
        all_statuses: مخرجات get_all_injury_statuses()

    Returns:
        {"status": "fit", "chance_of_playing": 100, "note": ""}
        الحالة الافتراضية "fit" إذا لم يُوجد اللاعب بالقاموس.
    """
    return all_statuses.get(
        player_id,
        {
            "status": "fit",
            "chance_of_playing": 100,
            "note": "",
            "source": "default",
        }
    )
