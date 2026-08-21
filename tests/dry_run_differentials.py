"""
dry_run_differentials.py — اختبار تشغيلي فعلي ببيانات حقيقية من FPL API.
"""

import sys
import logging
from pathlib import Path

# إعداد logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from fpl_client import get_bootstrap_static, get_fixtures, get_current_gameweek
from differential_finder import find_differentials
from report_builder import build_report_text


def run_verification():
    print("📥 1. جلب البيانات الحقيقية من FPL API...")
    bootstrap = get_bootstrap_static()
    fixtures = get_fixtures()
    current_gw = get_current_gameweek(bootstrap) or 1
    print(f"✅ الجولة المستهدفة: GW{current_gw}")

    # محاكاة تشكيلة حالية (أول 15 لاعب)
    sample_squad_ids = {p["id"] for p in bootstrap["elements"][:15]}

    print("🔍 2. تشغيل differential_finder ببيانات حقيقية...")
    diffs = find_differentials(
        all_players=bootstrap["elements"],
        my_squad_ids=sample_squad_ids,
        consensus_data=None,
        top_n_total=0,
        injury_statuses=None,
        fixtures_data=fixtures,
        current_gw=current_gw,
    )

    print(f"\n📊 تم العثور على {len(diffs)} لاعبين Differentials:")
    for i, d in enumerate(diffs, 1):
        print(f"  {i}. {d['name']} ({d['position']}) | £{d['price']}M | Ownership: {d['ownership']}% | Form: {d['form']} | FDR: {d['next_fixtures_difficulty']}")
        print(f"     السبب: {d['reason']}")

    # التحقق من القيود
    assert len(diffs) <= 5, "يجب ألا تتجاوز القائمة 5 لاعبين"
    for d in diffs:
        assert d["ownership"] >= 2.0 and d["ownership"] <= 15.0, f"نسبة الامتلاك {d['ownership']} خارج النطاق (2%-15%)"

    print("\n📝 3. بناء تقرير تيليجرام الكامل مع القسم الجديد...")
    mock_decision = {
        "gameweek": current_gw,
        "forced_transfers": [
            {
                "out": "PlayerA",
                "in": "PlayerB",
                "reason": "إصابة مؤكدة",
                "cost_in_points": 0,
            }
        ],
        "still_pending": [],
        "flagged_players": [],
        "captain": "Haaland",
        "vice_captain": "Salah",
        "chip_suggestion": {
            "chip": None,
            "recommended": False,
            "reason": "لا توجد حاجة للرقاقة بهذه الجولة",
        },
        "bank_after": 1.2,
        "free_transfers_remaining": 1,
        "differential_suggestions": diffs if diffs else [
            {
                "name": "SampleDiff",
                "position": "MID",
                "price": 6.5,
                "ownership": 5.2,
                "form": 5.8,
                "next_fixtures_difficulty": "سهلة",
                "reason": "فورم ممتاز ومباريات سهلة",
            }
        ],
    }

    report = build_report_text(mock_decision, team_name="فريق التجربة", team_id=999999)
    print("\n" + "=" * 50)
    print(report)
    print("=" * 50)

    # تأكيدات التقرير
    assert "لاعبون يستحقون المتابعة" in report, "عنوان القسم يجب أن يظهر بالتقرير"
    assert "التحويلات المقترحة (1):" in report, "عدد التحويلات لم يتغير أبداً"
    print("\n✅ تم التحقق النهائي بنجاح: القسم يظهر بصورة منسقة وبدون أي تأثير على التحويلات المقترحة!")


if __name__ == "__main__":
    run_verification()
