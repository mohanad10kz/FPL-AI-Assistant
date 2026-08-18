"""
tests/test_decision_engine.py — Unit tests لمحرك القرار بالمهمة 8.
يستخدم بيانات وهمية (mock) لاختبار كل قاعدة بمعزل.
"""

import sys
import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from decision_engine import (
    run_decision_engine,
    _get_used_chips_this_half,
    _select_captain,
    _evaluate_chip,
)
from transfer_planner import QUEUE_FILE


def make_player(pid, name, pos, team, price_raw, form, ep_next, status="a", chance=None, news=""):
    """مساعد لإنشاء لاعب وهمي."""
    return {
        "id": pid,
        "web_name": name,
        "element_type": pos,
        "team": team,
        "now_cost": price_raw,
        "form": str(form),
        "ep_next": str(ep_next),
        "points_per_game": str(form),
        "selected_by_percent": "10.0",
        "status": status,
        "chance_of_playing_next_round": chance,
        "news": news,
        "total_points": int(form * 5),
    }


def make_pick(pid, position, captain=False, vice=False):
    """مساعد لإنشاء pick وهمي."""
    return {
        "element": pid,
        "position": position,
        "is_captain": captain,
        "is_vice_captain": vice,
        "multiplier": 2 if captain else (1 if not vice else 1),
    }


class TestDecisionEngineCore(unittest.TestCase):

    def setUp(self):
        """إعداد بيانات وهمية مشتركة."""
        # تنظيف ملف الطابور قبل كل اختبار
        if QUEUE_FILE.exists():
            QUEUE_FILE.unlink()

        # 15 لاعب وهمي: 2GK + 5DEF + 5MID + 3FWD
        self.players = [
            # GK (1)
            make_player(1, "GK1", 1, 1, 50, 5.0, 5.0),
            make_player(2, "GK2", 1, 2, 45, 4.0, 4.0),
            # DEF (2)
            make_player(3, "DEF1", 2, 3, 55, 6.0, 6.0),
            make_player(4, "DEF2", 2, 4, 52, 5.5, 5.5),
            make_player(5, "DEF3", 2, 5, 48, 5.0, 5.0),
            make_player(6, "DEF4", 2, 6, 46, 4.5, 4.5),
            make_player(7, "DEF5", 2, 7, 44, 4.0, 4.0),
            # MID (3)
            make_player(8, "MID1", 3, 8, 100, 9.0, 9.0),  # نجم كبير
            make_player(9, "MID2", 3, 9, 85, 7.0, 7.0),
            make_player(10, "MID3", 3, 10, 70, 6.0, 6.0),
            make_player(11, "MID4", 3, 11, 65, 5.5, 5.5),
            make_player(12, "MID5", 3, 12, 60, 5.0, 5.0),
            # FWD (4)
            make_player(13, "FWD1", 4, 13, 90, 8.0, 8.0),
            make_player(14, "FWD2", 4, 14, 75, 7.0, 7.0),
            make_player(15, "FWD3", 4, 15, 60, 6.0, 6.0),
            # لاعبون للاستبدال (خارج تشكيلتي)
            make_player(20, "SubGK", 1, 16, 40, 3.0, 3.0),
            make_player(21, "SubDEF", 2, 17, 45, 5.0, 5.0),
            make_player(22, "SubMID", 3, 18, 65, 6.5, 6.5),
            make_player(23, "SubFWD", 4, 19, 70, 7.0, 7.0),
        ]

        self.bootstrap = {
            "elements": self.players,
            "teams": [{"id": i} for i in range(1, 21)],
            "events": [],
        }

        # تشكيلتي: 15 لاعب الأوائل
        self.my_picks = [make_pick(i, i) for i in range(1, 16)]

        self.entry_history = {
            "bank": 5,     # 0.5M
            "event_transfers": 0,
            "event_transfers_cost": 0,
            "transfers_balance": 1,
        }

        self.injury_statuses = {
            i: {"status": "fit", "chance_of_playing": 100, "note": ""}
            for i in range(1, 24)
        }

        self.manager_history = {"chips": [], "current": [], "past": []}

    def test_no_injuries_no_forced_transfers(self):
        """لو كل اللاعبين سليمين، لا يوجد تحويل إجباري."""
        result = run_decision_engine(
            gameweek=2,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        self.assertEqual(result["forced_transfers"], [])
        self.assertIsNotNone(result["captain"])
        self.assertIsNotNone(result["vice_captain"])

    def test_injured_player_triggers_forced_transfer(self):
        """لاعب مصاب يظهر بقائمة forced_transfers."""
        self.injury_statuses[8] = {  # MID1 مصاب
            "status": "injured",
            "chance_of_playing": 0,
            "note": "Muscle injury",
        }
        result = run_decision_engine(
            gameweek=2,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        out_names = [t["out"] for t in result["forced_transfers"] + [
            {"out": p["out"]} for p in result["still_pending"]
        ]]
        self.assertIn("MID1", out_names)

    def test_no_captain_if_injured(self):
        """لا يُقترح كابتن حالته injured."""
        # نصب كل اللاعبين مصابين عدا واحد
        for pid in range(1, 16):
            self.injury_statuses[pid]["status"] = "injured"
        # اللاعب 15 فقط سليم
        self.injury_statuses[15] = {"status": "fit", "chance_of_playing": 100, "note": ""}

        result = run_decision_engine(
            gameweek=3,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        # الكابتن يجب أن يكون FWD3 (الوحيد السليم)
        self.assertEqual(result["captain"], "FWD3")

    def test_used_chip_not_suggested(self):
        """رقاقة مستخدمة بهذا النصف لا تُقترح."""
        self.manager_history["chips"] = [
            {"name": "3xc", "event": 5},   # Triple Captain بالجولة 5 (نصف أول)
        ]
        result = run_decision_engine(
            gameweek=10,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        # 3xc مستخدمة → لا يُقترح Triple Captain
        if result["chip_suggestion"]["chip"] == "Triple Captain":
            self.fail("Triple Captain اقترحت رغم كونها مستخدمة!")

    def test_gw1_no_consensus_used(self):
        """في الجولة 1، consensus_data=None → لا يُستخدم الإجماع."""
        result = run_decision_engine(
            gameweek=1,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        # لا يجب أن يكون هناك flagged_players بناءً على الإجماع
        self.assertEqual(result["flagged_players"], [])

    def test_transfers_cost_is_zero_within_free(self):
        """التحويلات ضمن الرصيد المجاني لا تكلّف نقاطاً."""
        self.injury_statuses[8] = {"status": "injured", "chance_of_playing": 0, "note": ""}
        result = run_decision_engine(
            gameweek=2,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=None,
        )
        # تحويل واحد ضمن رصيد مجاني واحد → تكلفة 0
        self.assertEqual(result["transfers_cost"], 0)

    def test_get_used_chips_this_half(self):
        """اختبار استخراج الرقائق المستخدمة بالنصف الحالي."""
        chips = [
            {"name": "wildcard", "event": 5},   # نصف أول
            {"name": "3xc", "event": 22},        # نصف ثاني
        ]
        # في الجولة 10 (نصف أول) → نرى wildcard فقط
        used_h1 = _get_used_chips_this_half(chips, current_gw=10)
        self.assertIn("wildcard", used_h1)
        self.assertNotIn("3xc", used_h1)

        # في الجولة 25 (نصف ثاني) → نرى 3xc فقط
        used_h2 = _get_used_chips_this_half(chips, current_gw=25)
        self.assertIn("3xc", used_h2)
        self.assertNotIn("wildcard", used_h2)


class TestConsensusIntegration(unittest.TestCase):
    """اختبارات دمج الإجماع مع القرار."""

    def setUp(self):
        if QUEUE_FILE.exists():
            QUEUE_FILE.unlink()

        self.players = [
            make_player(1, "GK1", 1, 1, 50, 5.0, 5.0),
            make_player(2, "GK2", 1, 2, 45, 4.0, 4.0),
            make_player(3, "DEF1", 2, 3, 55, 6.0, 6.0),
            make_player(4, "DEF2", 2, 4, 52, 5.5, 5.5),
            make_player(5, "DEF3", 2, 5, 48, 5.0, 5.0),
            make_player(6, "DEF4", 2, 6, 46, 4.5, 4.5),
            make_player(7, "DEF5", 2, 7, 44, 4.0, 4.0),
            make_player(8, "MID1", 3, 8, 100, 9.0, 9.0),
            make_player(9, "MID2", 3, 9, 85, 7.0, 7.0),
            make_player(10, "MID3", 3, 10, 70, 6.0, 6.0),
            make_player(11, "MID4", 3, 11, 65, 5.5, 5.5),
            make_player(12, "MID5", 3, 12, 60, 5.0, 5.0),
            make_player(13, "FWD1", 4, 13, 90, 8.0, 8.0),
            make_player(14, "FWD2", 4, 14, 75, 7.0, 7.0),
            make_player(15, "FWD3", 4, 15, 60, 6.0, 6.0),
            make_player(20, "SubGK", 1, 16, 40, 3.0, 3.0),
            make_player(21, "SubDEF", 2, 17, 45, 5.0, 5.0),
            make_player(22, "SubMID", 3, 18, 65, 6.5, 6.5),
        ]
        self.bootstrap = {"elements": self.players, "teams": [], "events": []}
        self.my_picks = [make_pick(i, i) for i in range(1, 16)]
        self.entry_history = {"bank": 10, "event_transfers": 0,
                               "event_transfers_cost": 0, "transfers_balance": 1}
        self.injury_statuses = {
            i: {"status": "fit", "chance_of_playing": 100, "note": ""}
            for i in range(1, 23)
        }
        self.manager_history = {"chips": [], "current": [], "past": []}

    def test_consensus_absent_fit_goes_to_flagged(self):
        """لاعب غائب عن الإجماع لكن سليم → flagged_players فقط (لا تحويل)."""
        # MID5 (id=12) غائب تماماً عن الإجماع لكن سليم
        consensus_data = {i: 8 for i in range(1, 16) if i != 12}
        consensus_data[12] = 0  # MID5 غائب

        result = run_decision_engine(
            gameweek=3,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=consensus_data,
            total_top_n=10,
        )
        flagged_names = [p["name"] for p in result["flagged_players"]]
        forced_out_names = [t["out"] for t in result["forced_transfers"]]

        self.assertIn("MID5", flagged_names)
        self.assertNotIn("MID5", forced_out_names)

    def test_consensus_absent_doubtful_goes_to_forced(self):
        """لاعب غائب عن الإجماع + Doubtful → forced_transfers."""
        consensus_data = {i: 8 for i in range(1, 16) if i != 12}
        consensus_data[12] = 0  # MID5 غائب
        self.injury_statuses[12] = {"status": "doubtful", "chance_of_playing": 50, "note": "Knee"}

        result = run_decision_engine(
            gameweek=3,
            my_picks=self.my_picks,
            entry_history=self.entry_history,
            bootstrap_data=self.bootstrap,
            injury_statuses=self.injury_statuses,
            manager_history=self.manager_history,
            consensus_data=consensus_data,
            total_top_n=10,
        )
        all_outs = (
            [t["out"] for t in result["forced_transfers"]]
            + [t["out"] for t in result["still_pending"]]
        )
        self.assertIn("MID5", all_outs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
