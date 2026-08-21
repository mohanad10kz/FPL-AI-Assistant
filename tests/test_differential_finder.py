"""
test_differential_finder.py — اختبارات شاملة لميزة differential_finder.py
"""

import sys
import unittest
from pathlib import Path

# إضافة src إلى مسار الاستيراد
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from differential_finder import (
    filter_candidates,
    score_and_rank,
    build_differential_section,
    find_differentials,
    _calculate_team_fdr_avg,
    MIN_OWNERSHIP,
    MAX_OWNERSHIP,
)


class TestDifferentialFinder(unittest.TestCase):

    def setUp(self):
        # إعداد بيانات وهمية للاختبار
        self.players = [
            # ID 1: في تشكيلتي (يجب استبعاده بفلتر 1)
            {
                "id": 1,
                "web_name": "MyPlayer",
                "element_type": 3,
                "now_cost": 60,
                "selected_by_percent": "5.0",
                "form": "6.0",
                "status": "a",
                "team": 1,
            },
            # ID 2: إجماع عالي 8/10 (يجب استبعاده بفلتر 2)
            {
                "id": 2,
                "web_name": "ConsensusStar",
                "element_type": 3,
                "now_cost": 65,
                "selected_by_percent": "8.0",
                "form": "6.5",
                "status": "a",
                "team": 1,
            },
            # ID 3: امتلاك منخفض جداً 1.0% (يجب استبعاده بفلتر 3)
            {
                "id": 3,
                "web_name": "TooLowOwn",
                "element_type": 3,
                "now_cost": 55,
                "selected_by_percent": "1.0",
                "form": "5.0",
                "status": "a",
                "team": 2,
            },
            # ID 4: امتلاك عالي جداً 25.0% (يجب استبعاده بفلتر 3)
            {
                "id": 4,
                "web_name": "TemplatePlayer",
                "element_type": 3,
                "now_cost": 70,
                "selected_by_percent": "25.0",
                "form": "7.0",
                "status": "a",
                "team": 2,
            },
            # ID 5: سعر غالي جداً (يجب استبعاده بفلتر 4)
            {
                "id": 5,
                "web_name": "TooExpensive",
                "element_type": 3,
                "now_cost": 130,  # 13.0M
                "selected_by_percent": "6.0",
                "form": "8.0",
                "status": "a",
                "team": 3,
            },
            # ID 6: فورم منخفض (يجب استبعاده بفلتر 5)
            {
                "id": 6,
                "web_name": "LowForm",
                "element_type": 3,
                "now_cost": 50,
                "selected_by_percent": "4.0",
                "form": "1.0",
                "status": "a",
                "team": 3,
            },
            # ID 7: مصاب (يجب استبعاده بفلتر 6)
            {
                "id": 7,
                "web_name": "InjuredGuy",
                "element_type": 3,
                "now_cost": 60,
                "selected_by_percent": "5.0",
                "form": "6.0",
                "status": "i",
                "team": 4,
            },
            # ID 8: مؤهل تماماً (Differential مثالي 1)
            {
                "id": 8,
                "web_name": "PerfectDiff1",
                "element_type": 3,
                "now_cost": 60,
                "selected_by_percent": "5.5",
                "form": "6.2",
                "status": "a",
                "team": 4,
            },
            # ID 9: مؤهل تماماً (Differential مثالي 2 - مدافع)
            {
                "id": 9,
                "web_name": "PerfectDiff2",
                "element_type": 2,
                "now_cost": 45,
                "selected_by_percent": "4.0",
                "form": "5.5",
                "status": "a",
                "team": 5,
            },
            # ID 10: لاعب تعبئة لموازنة متوسطات المراكز
            {
                "id": 10,
                "web_name": "FillerDef",
                "element_type": 2,
                "now_cost": 50,
                "selected_by_percent": "3.0",
                "form": "2.0",
                "status": "a",
                "team": 5,
            },
        ]

        self.my_squad_ids = {1}
        self.consensus_data = {2: 8}  # 8 من أصل 10
        self.top_n_total = 10
        self.injury_statuses = {
            7: {"status": "injured", "chance_of_playing": 0},
            8: {"status": "fit", "chance_of_playing": 100},
            9: {"status": "fit", "chance_of_playing": 100},
        }
        self.fixtures = [
            {"event": 1, "team_h": 4, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 4, "finished": False},
            {"event": 2, "team_h": 7, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 2, "finished": False},
            {"event": 1, "team_h": 5, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 5, "finished": False},
        ]

    def test_filter_candidates(self):
        filtered = filter_candidates(
            all_players=self.players,
            my_squad_ids=self.my_squad_ids,
            consensus_data=self.consensus_data,
            top_n_total=self.top_n_total,
            injury_statuses=self.injury_statuses,
        )
        survivor_ids = {p["id"] for p in filtered}

        # تأكد من استبعاد غير المؤهلين
        self.assertNotIn(1, survivor_ids, "يجب استبعاد لاعب تشكيلتي")
        self.assertNotIn(2, survivor_ids, "يجب استبعاد لاعب الإجماع العالي")
        self.assertNotIn(3, survivor_ids, "يجب استبعاد لاعب الامتلاك المنخفض جداً (<2%)")
        self.assertNotIn(4, survivor_ids, "يجب استبعاد لاعب الامتلاك العالي (>15%)")
        self.assertNotIn(5, survivor_ids, "يجب استبعاد لاعب السعر المرتفع")
        self.assertNotIn(6, survivor_ids, "يجب استبعاد لاعب الفورم المنخفض")
        self.assertNotIn(7, survivor_ids, "يجب استبعاد اللاعب المصاب")

        # تأكد من بقاء المؤهلين
        self.assertIn(8, survivor_ids, "يجب قبول PerfectDiff1")
        self.assertIn(9, survivor_ids, "يجب قبول PerfectDiff2")

    def test_score_and_rank_limit(self):
        # إنشاء 25 لاعب مؤهل للتأكد من اقتطاع أفضل 5
        many_players = []
        for i in range(100, 125):
            many_players.append({
                "id": i,
                "web_name": f"Player_{i}",
                "element_type": (i % 4) + 1,
                "now_cost": 55,
                "selected_by_percent": "5.0",
                "form": str(float(i % 10 + 2)),
                "status": "a",
                "team": (i % 20) + 1,
            })

        ranked = score_and_rank(many_players, fixtures_data=self.fixtures, current_gw=1)
        self.assertLessEqual(len(ranked), 5, "يجب ألا تتجاوز القائمة النهائية 5 لاعبين")
        self.assertTrue(all("_score" in p for p in ranked))
        # تحقق من الترتيب التنازلي
        scores = [p["_score"] for p in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_build_differential_section(self):
        ranked = score_and_rank(
            [self.players[7], self.players[8]],
            fixtures_data=self.fixtures,
            current_gw=1,
        )
        section = build_differential_section(ranked)
        self.assertIn("differential_suggestions", section)
        suggestions = section["differential_suggestions"]
        self.assertEqual(len(suggestions), 2)
        s1 = suggestions[0]
        self.assertIn("name", s1)
        self.assertIn("position", s1)
        self.assertIn("price", s1)
        self.assertIn("ownership", s1)
        self.assertIn("form", s1)
        self.assertIn("next_fixtures_difficulty", s1)
        self.assertIn("reason", s1)

    def test_find_differentials_end_to_end(self):
        result = find_differentials(
            all_players=self.players,
            my_squad_ids=self.my_squad_ids,
            consensus_data=self.consensus_data,
            top_n_total=self.top_n_total,
            injury_statuses=self.injury_statuses,
            fixtures_data=self.fixtures,
            current_gw=1,
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        names = [r["name"] for r in result]
        self.assertIn("PerfectDiff1", names)
        self.assertIn("PerfectDiff2", names)

    def test_report_builder_with_differentials(self):
        from report_builder import build_report_text
        diffs = [
            {
                "name": "Eze",
                "position": "MID",
                "price": 6.8,
                "ownership": 6.2,
                "form": 6.5,
                "next_fixtures_difficulty": "سهلة",
                "reason": "فورم ممتاز (6.5) + مباريات قادمة سهلة جداً",
            }
        ]
        decision_data = {
            "gameweek": 3,
            "forced_transfers": [],
            "still_pending": [],
            "flagged_players": [],
            "captain": "Salah",
            "vice_captain": "Haaland",
            "chip_suggestion": {},
            "bank_after": 1.5,
            "free_transfers_remaining": 1,
            "transfers_cost": 0,
            "differential_suggestions": diffs,
        }
        report = build_report_text(decision_data, team_name="فريق التجربة")
        self.assertIn("لاعبون يستحقون المتابعة", report)
        self.assertIn("Eze", report)
        self.assertIn("MID", report)
        self.assertIn("£6.8م", report)
        self.assertIn("امتلاك: 6.2%", report)
        self.assertIn("فورم: 6.5", report)

    def test_report_builder_without_differentials(self):
        from report_builder import build_report_text
        decision_data = {
            "gameweek": 3,
            "forced_transfers": [],
            "still_pending": [],
            "flagged_players": [],
            "captain": "Salah",
            "vice_captain": "Haaland",
            "chip_suggestion": {},
            "bank_after": 1.5,
            "free_transfers_remaining": 1,
            "transfers_cost": 0,
            "differential_suggestions": [],
        }
        report = build_report_text(decision_data, team_name="فريق التجربة")
        self.assertNotIn("لاعبون يستحقون المتابعة", report)


if __name__ == "__main__":
    unittest.main()

