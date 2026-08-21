"""
fpl_client.py — الوسيط الوحيد بين المشروع وFPL API الرسمي.
لا يُسمح لأي ملف آخر بالمشروع بعمل HTTP requests مباشرة لـ FPL API.
"""

import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# ─── ثوابت API ───────────────────────────────────────────────────────────────
FPL_BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_TIMEOUT = 10       # ثواني
MAX_RETRIES = 2            # إعادة المحاولة مرة واحدة قبل رفع الخطأ
RETRY_DELAY = 3            # ثواني بين المحاولات

# Headers تحاكي المتصفح — FPL API أحياناً يرفض طلبات Python العارية
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://fantasy.premierleague.com/",
}


class FPLAPIError(RuntimeError):
    """خطأ خاص بفشل اتصال FPL API."""
    pass


def _get(url: str, params: Optional[dict] = None) -> dict:
    """
    دالة مساعدة داخلية: تنفّذ GET request مع retry تلقائي.
    تُسجّل الخطأ وترفعه لو فشلت بعد كل المحاولات.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug("GET %s (محاولة %d/%d)", url, attempt, MAX_RETRIES)
            response = requests.get(
                url,
                params=params,
                headers=DEFAULT_HEADERS,
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning("⏱ Timeout على %s (محاولة %d) — %s", url, attempt, e)
        except requests.exceptions.HTTPError as e:
            last_error = e
            logger.warning("❌ HTTP Error على %s (محاولة %d) — %s", url, attempt, e)
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning("🔌 Connection Error على %s (محاولة %d) — %s", url, attempt, e)
        except Exception as e:
            last_error = e
            logger.warning("⚠️ خطأ غير متوقع على %s (محاولة %d) — %s", url, attempt, e)

        if attempt < MAX_RETRIES:
            logger.info("⏳ الانتظار %d ثانية قبل إعادة المحاولة...", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    raise FPLAPIError(
        f"فشل الاتصال بـ FPL API بعد {MAX_RETRIES} محاولات.\n"
        f"URL: {url}\n"
        f"الخطأ الأخير: {last_error}"
    )


# ─── الدوال العامة ───────────────────────────────────────────────────────────

def get_bootstrap_static() -> dict:
    """
    يجلب بيانات الموسم الكاملة: اللاعبين، الأندية، الجولات.

    Returns:
        dict يحوي:
            - 'elements': قائمة كل اللاعبين
            - 'teams': قائمة الأندية
            - 'events': قائمة الجولات

    Note:
        يجب استدعاء هذه الدالة مرة واحدة في بداية التشغيل وتمرير
        نتيجتها لباقي الدوال — لا تكرر الطلب.
    """
    url = f"{FPL_BASE_URL}/bootstrap-static/"
    logger.info("📥 جلب bootstrap-static...")
    data = _get(url)
    n_players = len(data.get("elements", []))
    n_teams = len(data.get("teams", []))
    n_events = len(data.get("events", []))
    logger.info(
        "✅ bootstrap-static: %d لاعب، %d نادي، %d جولة",
        n_players, n_teams, n_events
    )
    return data


def get_current_gameweek(bootstrap_data: dict) -> Optional[int]:
    """
    يستخرج رقم الجولة القادمة (المخطَّط لها) من بيانات bootstrap.

    Args:
        bootstrap_data: النتيجة المباشرة من get_bootstrap_static()

    Returns:
        رقم الجولة القادمة (int)، أو None لو انتهى الموسم.

    Note:
        نستهدف is_next=True (الجولة القادمة التي نخطط لها).
        لو كانت جولة جارية (is_current=True) بدون is_next، نرجعها.
        لو انتهى الموسم (كل الجولات finished=True)، نرجع None.
    """
    events = bootstrap_data.get("events", [])

    # الجولة القادمة (الأولوية القصوى — هي المخططة للتحليل)
    next_gw = next(
        (e["id"] for e in events if e.get("is_next")),
        None
    )
    if next_gw:
        logger.info("📅 الجولة القادمة: GW%d", next_gw)
        return next_gw

    # لو ما في "next"، ابحث عن "current" (الجولة الجارية)
    current_gw = next(
        (e["id"] for e in events if e.get("is_current")),
        None
    )
    if current_gw:
        logger.info("📅 الجولة الحالية (جارية): GW%d", current_gw)
        return current_gw

    # الموسم انتهى كلياً
    logger.warning("⚠️ لا توجد جولة قادمة أو جارية — الموسم قد انتهى.")
    return None


def get_next_gameweek_deadline(bootstrap_data: dict) -> Optional["datetime"]:
    """
    يستخرج وقت الديدلاين الفعلي للجولة القادمة من bootstrap-static.

    Args:
        bootstrap_data: النتيجة المباشرة من get_bootstrap_static()

    Returns:
        datetime بـ UTC لو وُجدت جولة قادمة، أو None لو انتهى الموسم.

    Note:
        FPL يُرجع deadline_time بصيغة ISO 8601 دائماً بـ UTC
        (مثال: "2024-10-19T10:00:00Z").
        نستهدف الجولة ذات is_next=True بالأولوية، ثم is_current=True.
    """
    from datetime import datetime, timezone

    events = bootstrap_data.get("events", [])

    # ابحث عن الجولة القادمة أولاً، ثم الحالية
    target_event = next(
        (e for e in events if e.get("is_next")),
        None
    ) or next(
        (e for e in events if e.get("is_current")),
        None
    )

    if not target_event:
        logger.warning("⚠️ get_next_gameweek_deadline: لا توجد جولة قادمة أو جارية.")
        return None

    deadline_str = target_event.get("deadline_time", "")
    if not deadline_str:
        logger.warning(
            "⚠️ get_next_gameweek_deadline: الجولة GW%d ليس لها deadline_time.",
            target_event.get("id", "?")
        )
        return None

    try:
        # صيغة FPL: "2024-10-19T10:00:00Z" أو "2024-10-19T10:00:00+00:00"
        deadline_str_clean = deadline_str.replace("Z", "+00:00")
        deadline_utc = datetime.fromisoformat(deadline_str_clean)
        # تأكد أن القيمة لها timezone info
        if deadline_utc.tzinfo is None:
            deadline_utc = deadline_utc.replace(tzinfo=timezone.utc)
        logger.info(
            "📅 ديدلاين GW%d: %s UTC",
            target_event.get("id", "?"),
            deadline_utc.strftime("%Y-%m-%d %H:%M")
        )
        return deadline_utc
    except (ValueError, TypeError) as e:
        logger.error(
            "❌ خطأ في تحليل deadline_time '%s': %s",
            deadline_str, e
        )
        return None



def get_my_team(team_id: int, gameweek: int) -> dict:
    """
    يجلب تشكيلة مدير معين بجولة معينة.

    Args:
        team_id: معرّف الفريق (FPL entry ID)
        gameweek: رقم الجولة

    Returns:
        dict يحوي:
            - 'picks': قائمة الـ15 لاعب مع مراكزهم والكابتن
            - 'entry_history': الرصيد والتحويلات المستخدمة والنقاط
            - 'active_chip': الرقاقة الفعّالة بهذه الجولة (أو None)

    Note:
        هذا الـ endpoint يعمل فقط بعد بدء الجولة الأولى فعلياً.
        يُستخدم لجلب تشكيلة المستخدم وتشكيلات أفضل المدراء على حد سواء.
    """
    url = f"{FPL_BASE_URL}/entry/{team_id}/event/{gameweek}/picks/"
    logger.info("📥 جلب تشكيلة team_id=%d للجولة GW%d...", team_id, gameweek)
    data = _get(url)
    picks_count = len(data.get("picks", []))
    active_chip = data.get("active_chip")
    logger.info(
        "✅ تشكيلة team_id=%d: %d لاعب، الرقاقة الفعّالة: %s",
        team_id, picks_count, active_chip or "لا شيء"
    )
    return data


def get_manager_history(team_id: int) -> dict:
    """
    يجلب تاريخ مدير معين: كل الجولات + الرقائق المستخدمة.

    Args:
        team_id: معرّف الفريق (FPL entry ID)

    Returns:
        dict يحوي:
            - 'current': نقاط وتحويلات كل جولة هذا الموسم
            - 'past': إحصائيات مواسم سابقة
            - 'chips': قائمة الرقائق المستخدمة {name, event, time}

    Note:
        ضروري لـ decision_engine.py لتفادي اقتراح رقاقة مستخدمة سابقاً.
    """
    url = f"{FPL_BASE_URL}/entry/{team_id}/history/"
    logger.info("📥 جلب تاريخ team_id=%d...", team_id)
    data = _get(url)
    chips_used = [c["name"] for c in data.get("chips", [])]
    logger.info(
        "✅ تاريخ team_id=%d: %d جولة مسجّلة، الرقائق المستخدمة: %s",
        team_id,
        len(data.get("current", [])),
        chips_used or "لا شيء"
    )
    return data


def get_league_standings(league_id: int = 314, page: int = 1) -> dict:
    """
    يجلب ترتيب الدوري الكلاسيكي (افتراضياً: الدوري العام العالمي 314).

    Args:
        league_id: معرّف الدوري (314 = Overall World League)
        page: رقم الصفحة في نتائج الترتيب

    Returns:
        dict يحوي:
            - 'standings': {'results': [{entry, entry_name, rank, total, ...}, ...]}
            - 'league': معلومات الدوري
            - 'new_entries': مدراء جدد

    Note:
        يُستخدم حصراً من top_managers.py لجلب أفضل N مدير عالمياً.
    """
    url = f"{FPL_BASE_URL}/leagues-classic/{league_id}/standings/"
    logger.info("📥 جلب ترتيب league_id=%d (صفحة %d)...", league_id, page)
    data = _get(url, params={"page_standings": page})
    results = data.get("standings", {}).get("results", [])
    logger.info(
        "✅ ترتيب league_id=%d: %d مدير بهذه الصفحة",
        league_id, len(results)
    )
    return data
