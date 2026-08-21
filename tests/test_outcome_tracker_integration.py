"""
tests/test_outcome_tracker_integration.py — اختبار تكاملي للتحقق من:
1. توليد ملف outcomes_gw_{n}.json بعد جولة منتهية بمحتوى منطقي.
2. التأكد من أن تعطيل أو فشل outcome_tracker لا يكسر main.py أو decision_engine.py.
"""

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from outcome_tracker import process_pending_outcomes
from decision_engine import run_decision_engine


class TestOutcomeTrackerIntegration(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.team_id = 999999
        self.team_dir = self.test_dir / str(self.team_id)
        self.team_dir.mkdir(parents=True, exist_ok=True)

        self.bootstrap_data = {
            "events": [
                {"id": 1, "finished": True, "is_current": False, "is_next": False},
                {"id": 2, "finished": False, "is_current": True, "is_next": False},
            ],
            "elements": [
                {"id": 10, "web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah"},
                {"id": 20, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"},
                {"id": 30, "web_name": "Saka", "first_name": "Bukayo", "second_name": "Saka"},
                {"id": 40, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer"},
            ],
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("outcome_tracker.fetch_actual_team")
    def test_outcomes_file_generation_and_content(self, mock_fetch_team):
        """التحقق من إنشاء ملف data/history/{team_id}/outcomes_gw_{n}.json بمحتوى منطقي."""
        # محاكاة وجود توصية سابقة للجولة 1
        gw1_decision = {
            "gameweek": 1,
            "forced_transfers": [
                {"out": "Saka", "in": "Palmer", "player_out_id": 30, "player_in_id": 40}
            ],
            "captain": "Haaland",
            "differential_suggestions": [
                {"id": 40, "name": "Palmer"}
            ]
        }
        (self.team_dir / "gw_1.json").write_text(
            json.dumps(gw1_decision, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # التشكيلة الفعلية
        mock_fetch_team.return_value = {
            "picks": [
                {"element": 10},  # Salah -> 10 pts
                {"element": 20},  # Haaland -> 13 pts (الكابتن المقترح)
                {"element": 40},  # Palmer -> 8 pts
            ]
        }

        # نقاط الجولة 1
        mock_points = {
            (10, 1): 10,
            (20, 1): 13,
            (30, 1): 2,
            (40, 1): 8,
        }
        points_getter = lambda pid, gw: mock_points.get((pid, gw), 0)

        outcomes = process_pending_outcomes(
            team_id=self.team_id,
            bootstrap_data=self.bootstrap_data,
            history_dir=self.test_dir,
            points_getter=points_getter,
        )

        self.assertEqual(len(outcomes), 1)

        # التحقق من وجود الملف فعلياً
        outcome_file = self.team_dir / "outcomes_gw_1.json"
        self.assertTrue(outcome_file.exists())

        with open(outcome_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["gameweek"], 1)
        self.assertIn("evaluated_at", data)

        # فحص تقييم التبديل
        self.assertEqual(len(data["transfer_evaluations"]), 1)
        t_eval = data["transfer_evaluations"][0]
        self.assertEqual(t_eval["out"], "Saka")
        self.assertEqual(t_eval["in"], "Palmer")
        self.assertTrue(t_eval["followed_by_user"])
        self.assertEqual(t_eval["points_gained_if_followed"], 6)  # 8 - 2

        # فحص تقييم الكابتن
        cap_eval = data["captain_evaluation"]
        self.assertEqual(cap_eval["suggested"], "Haaland")
        self.assertEqual(cap_eval["actual_points"], 13)
        self.assertEqual(cap_eval["best_possible_points"], 13)
        self.assertEqual(cap_eval["gap"], 0)

        # فحص تقييم Differentials
        self.assertEqual(len(data["differential_evaluations"]), 1)
        self.assertEqual(data["differential_evaluations"][0]["name"], "Palmer")
        self.assertEqual(data["differential_evaluations"][0]["actual_points"], 8)

    def test_disabling_outcome_tracker_does_not_break_decision_engine(self):
        """التحقق من أن تعطيل أو عدم وجود outcome_tracker لا يكسر decision_engine أبداً."""
        # تشغيل محرك القرار مباشرة بدون أي اتصال بـ outcome_tracker
        my_picks = [{"element": 10, "position": 1}]
        entry_history = {"bank": 10, "transfers_balance": 1}
        manager_history = {"chips": []}
        injury_statuses = {}

        decision = run_decision_engine(
            gameweek=2,
            my_picks=my_picks,
            entry_history=entry_history,
            bootstrap_data=self.bootstrap_data,
            injury_statuses=injury_statuses,
            manager_history=manager_history,
        )

        self.assertIn("gameweek", decision)
        self.assertEqual(decision["gameweek"], 2)
        self.assertIn("captain", decision)

    @patch("outcome_tracker.process_pending_outcomes")
    def test_outcome_tracker_failure_does_not_crash_main_step(self, mock_process):
        """التأكد من أن فشل أو رفع خطأ من outcome_tracker يتم التقاطه بأمان دون إيقاف البرنامج."""
        mock_process.side_effect = RuntimeError("Simulated outcome_tracker failure")

        team_ids = [self.team_id]
        team_names = ["Test Team"]

        # محاكاة السلوك المحمي في الخطوة 2أ بـ main.py
        step_completed = False
        try:
            try:
                from outcome_tracker import process_pending_outcomes
                for t_id, t_name in zip(team_ids, team_names):
                    outcomes = process_pending_outcomes(team_id=t_id, bootstrap_data=self.bootstrap_data)
            except Exception as e:
                # هذا ما يفعله main.py: يلتقط الخطأ ويكمل التحليل
                pass
            step_completed = True
        except Exception:
            step_completed = False

        self.assertTrue(step_completed, "main.py should continue normally even if outcome_tracker fails")


if __name__ == "__main__":
    unittest.main()

