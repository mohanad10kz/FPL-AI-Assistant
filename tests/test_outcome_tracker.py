"""
tests/test_outcome_tracker.py — اختبارات شاملة لوحدة outcome_tracker.py
"""

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# إضافة src إلى مسار الاستيراد
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from outcome_tracker import (
    detect_pending_evaluation,
    fetch_actual_team,
    evaluate_transfer_recommendation,
    evaluate_captain_recommendation,
    evaluate_differential_suggestions,
    build_outcome_record,
    save_outcome_record,
    process_pending_outcomes,
    _resolve_player,
    _build_players_map,
)


class TestOutcomeTracker(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.team_id = 123456

        # نموذج مصغر لبيانات bootstrap
        self.bootstrap_data = {
            "events": [
                {"id": 1, "finished": True, "name": "Gameweek 1"},
                {"id": 2, "finished": True, "name": "Gameweek 2"},
                {"id": 3, "finished": False, "name": "Gameweek 3"},
            ],
            "elements": [
                {"id": 10, "web_name": "Salah", "first_name": "Mohamed", "second_name": "Salah"},
                {"id": 20, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"},
                {"id": 30, "web_name": "Saka", "first_name": "Bukayo", "second_name": "Saka"},
                {"id": 40, "web_name": "Palmer", "first_name": "Cole", "second_name": "Palmer"},
                {"id": 50, "web_name": "Wood", "first_name": "Chris", "second_name": "Wood"},
                {"id": 60, "web_name": "BenchedZero", "first_name": "Zero", "second_name": "Player"},
            ],
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_detect_pending_evaluation(self):
        """اختبار تحديد الجولات المنتهية التي لم تُقيَّم بعد."""
        team_history = self.test_dir / str(self.team_id)
        team_history.mkdir(parents=True, exist_ok=True)

        # الجولة 1: مقيمة مسبقاً (يوجد gw_1 و outcomes_gw_1)
        (team_history / "gw_1.json").write_text("{}", encoding="utf-8")
        (team_history / "outcomes_gw_1.json").write_text("{}", encoding="utf-8")

        # الجولة 2: لم تقيم بعد (يوجد gw_2 ولا يوجد outcomes_gw_2)
        (team_history / "gw_2.json").write_text("{}", encoding="utf-8")

        # الجولة 3: غير منتهية أصلاً (finished=False)
        (team_history / "gw_3.json").write_text("{}", encoding="utf-8")

        pending = detect_pending_evaluation(
            team_id=self.team_id,
            bootstrap_data=self.bootstrap_data,
            history_dir=self.test_dir,
        )

        self.assertEqual(pending, [2])

    def test_detect_pending_evaluation_no_double_eval(self):
        """التأكد من عدم إعادة تقييم جولة مقيمة مسبقاً."""
        team_history = self.test_dir / str(self.team_id)
        team_history.mkdir(parents=True, exist_ok=True)

        (team_history / "gw_1.json").write_text("{}", encoding="utf-8")
        (team_history / "outcomes_gw_1.json").write_text("{}", encoding="utf-8")
        (team_history / "gw_2.json").write_text("{}", encoding="utf-8")
        (team_history / "outcomes_gw_2.json").write_text("{}", encoding="utf-8")

        pending = detect_pending_evaluation(
            team_id=self.team_id,
            bootstrap_data=self.bootstrap_data,
            history_dir=self.test_dir,
        )
        self.assertEqual(pending, [])

    @patch("outcome_tracker.get_my_team")
    def test_fetch_actual_team_success(self, mock_get_team):
        mock_get_team.return_value = {"picks": [{"element": 10}, {"element": 20}]}
        res = fetch_actual_team(self.team_id, 2)
        self.assertEqual(len(res.get("picks", [])), 2)

    @patch("outcome_tracker.get_my_team")
    def test_fetch_actual_team_error_handling(self, mock_get_team):
        mock_get_team.side_effect = Exception("API Error")
        res = fetch_actual_team(self.team_id, 2)
        self.assertEqual(res, {})

    def test_evaluate_transfer_recommendation(self):
        """اختبار تقييم التبديلات وحساب فرق النقاط والفحص هل اتبع المستخدم التوصية."""
        decision_record = {
            "forced_transfers": [
                # تبديل 1: اتبع التوصية (Palmer دخل التشكيلة بدلاً من Saka)
                {"out": "Saka", "in": "Palmer", "player_out_id": 30, "player_in_id": 40},
                # تبديل 2: لم يتبع التوصية (Wood لم يدخل التشكيلة)
                {"out": "Salah", "in": "Wood", "player_out_id": 10, "player_in_id": 50},
            ]
        }

        # تشكيلة المستخدم الفعلية: فيها Palmer (40) وليس فيها Wood (50)
        actual_team = {
            "picks": [
                {"element": 10},  # Salah
                {"element": 20},  # Haaland
                {"element": 40},  # Palmer
            ]
        }

        # دالة نقاط وهمية: Palmer=10, Saka=3, Wood=2, Salah=8
        mock_points = {
            (40, 2): 10,
            (30, 2): 3,
            (50, 2): 2,
            (10, 2): 8,
        }
        points_getter = lambda pid, gw: mock_points.get((pid, gw), 0)

        evals = evaluate_transfer_recommendation(
            decision_record=decision_record,
            actual_team=actual_team,
            gameweek=2,
            bootstrap_data=self.bootstrap_data,
            points_getter=points_getter,
        )

        self.assertEqual(len(evals), 2)

        # التبديل الأول
        self.assertEqual(evals[0]["out"], "Saka")
        self.assertEqual(evals[0]["in"], "Palmer")
        self.assertTrue(evals[0]["followed_by_user"])
        self.assertEqual(evals[0]["points_gained_if_followed"], 7)  # 10 - 3

        # التبديل الثاني
        self.assertEqual(evals[1]["out"], "Salah")
        self.assertEqual(evals[1]["in"], "Wood")
        self.assertFalse(evals[1]["followed_by_user"])
        self.assertEqual(evals[1]["points_gained_if_followed"], -6)  # 2 - 8

    def test_evaluate_captain_recommendation(self):
        """اختبار تقييم اختيار الكابتن ومقارنته بأعلى نقاط ممكنة بالتشكيلة."""
        decision_record = {
            "captain": "Haaland"  # معرف 20
        }

        actual_team = {
            "picks": [
                {"element": 10},  # Salah -> 15 نقطة (الأفضل)
                {"element": 20},  # Haaland -> 8 نقاط (الكابتن المقترح)
                {"element": 40},  # Palmer -> 10 نقاط
            ]
        }

        mock_points = {
            (20, 2): 8,
            (10, 2): 15,
            (40, 2): 10,
        }
        points_getter = lambda pid, gw: mock_points.get((pid, gw), 0)

        cap_eval = evaluate_captain_recommendation(
            decision_record=decision_record,
            actual_team=actual_team,
            gameweek=2,
            bootstrap_data=self.bootstrap_data,
            points_getter=points_getter,
        )

        self.assertEqual(cap_eval["suggested"], "Haaland")
        self.assertEqual(cap_eval["actual_points"], 8)
        self.assertEqual(cap_eval["best_possible_points"], 15)
        self.assertEqual(cap_eval["gap"], 7)  # 15 - 8

    def test_evaluate_differential_suggestions(self):
        """اختبار تقييم لاعبي الـ Differentials المقترحين."""
        decision_record = {
            "differential_suggestions": [
                {"id": 50, "name": "Wood"},
                {"id": 60, "name": "BenchedZero"},
            ]
        }

        mock_points = {
            (50, 2): 9,
            (60, 2): 0,  # لم يلعب -> 0 نقطة صراحة
        }
        points_getter = lambda pid, gw: mock_points.get((pid, gw), 0)

        diff_evals = evaluate_differential_suggestions(
            decision_record=decision_record,
            gameweek=2,
            bootstrap_data=self.bootstrap_data,
            points_getter=points_getter,
        )

        self.assertEqual(len(diff_evals), 2)
        self.assertEqual(diff_evals[0]["name"], "Wood")
        self.assertEqual(diff_evals[0]["actual_points"], 9)
        self.assertEqual(diff_evals[1]["name"], "BenchedZero")
        self.assertEqual(diff_evals[1]["actual_points"], 0)
        self.assertIsInstance(diff_evals[1]["actual_points"], int)

    def test_build_and_save_outcome_record(self):
        """اختبار بناء كائن النتائج وحفظه بصيغة JSON مطابقة للمواصفات."""
        transfer_evals = [{"out": "Saka", "in": "Palmer", "followed_by_user": True, "points_gained_if_followed": 4}]
        captain_eval = {"suggested": "Haaland", "actual_points": 8, "best_possible_points": 12, "gap": 4}
        diff_evals = [{"name": "Wood", "actual_points": 9}]

        record = build_outcome_record(
            gameweek=6,
            transfer_evaluations=transfer_evals,
            captain_evaluation=captain_eval,
            differential_evaluations=diff_evals,
        )

        self.assertEqual(record["gameweek"], 6)
        self.assertIn("evaluated_at", record)
        self.assertEqual(record["transfer_evaluations"], transfer_evals)
        self.assertEqual(record["captain_evaluation"], captain_eval)
        self.assertEqual(record["differential_evaluations"], diff_evals)

        # حفظ
        saved_path = save_outcome_record(record, gameweek=6, team_id=self.team_id, history_dir=self.test_dir)
        self.assertTrue(saved_path.exists())

        with open(saved_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["gameweek"], 6)
        self.assertEqual(len(loaded["transfer_evaluations"]), 1)

    @patch("outcome_tracker.fetch_actual_team")
    def test_process_pending_outcomes_e2e(self, mock_fetch_team):
        """اختبار المعالجة الشاملة للجولات المعلقة وحفظ الملفات."""
        team_history = self.test_dir / str(self.team_id)
        team_history.mkdir(parents=True, exist_ok=True)

        gw_data = {
            "gameweek": 2,
            "forced_transfers": [{"out": "Saka", "in": "Palmer", "player_out_id": 30, "player_in_id": 40}],
            "captain": "Haaland",
            "differential_suggestions": [{"id": 50, "name": "Wood"}],
        }
        (team_history / "gw_2.json").write_text(json.dumps(gw_data), encoding="utf-8")

        mock_fetch_team.return_value = {
            "picks": [{"element": 20}, {"element": 40}]
        }

        mock_points = {
            (20, 2): 10,
            (40, 2): 8,
            (30, 2): 2,
            (50, 2): 6,
        }
        points_getter = lambda pid, gw: mock_points.get((pid, gw), 0)

        results = process_pending_outcomes(
            team_id=self.team_id,
            bootstrap_data=self.bootstrap_data,
            history_dir=self.test_dir,
            points_getter=points_getter,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["gameweek"], 2)

        # التحقق من إنشاء ملف outcomes_gw_2.json
        outcome_file = team_history / "outcomes_gw_2.json"
        self.assertTrue(outcome_file.exists())

        with open(outcome_file, "r", encoding="utf-8") as f:
            saved_json = json.load(f)

        self.assertEqual(saved_json["gameweek"], 2)
        self.assertEqual(saved_json["captain_evaluation"]["suggested"], "Haaland")
        self.assertEqual(saved_json["captain_evaluation"]["actual_points"], 10)

    def test_decision_engine_does_not_import_outcome_tracker(self):
        """التأكد الحاسم من أن decision_engine.py لا يستورد outcome_tracker نهائياً."""
        decision_engine_path = src_dir / "decision_engine.py"
        content = decision_engine_path.read_text(encoding="utf-8")
        self.assertNotIn("outcome_tracker", content)
        self.assertNotIn("evaluate_transfer_recommendation", content)
        self.assertNotIn("process_pending_outcomes", content)


if __name__ == "__main__":
    unittest.main()
