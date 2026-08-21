"""
tests/test_fpl_client.py — اختبارات دوال fpl_client.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# إضافة src إلى مسار الاستيراد
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from fpl_client import get_player_gameweek_points


class TestFPLClient(unittest.TestCase):

    @patch("fpl_client._get")
    def test_get_player_gameweek_points_normal(self, mock_get):
        """اختبار جلب نقاط لاعب في جولة عادية."""
        mock_get.return_value = {
            "history": [
                {"round": 1, "total_points": 6, "minutes": 90},
                {"round": 2, "total_points": 12, "minutes": 90},
            ]
        }
        points = get_player_gameweek_points(player_id=101, gameweek=2)
        self.assertEqual(points, 12)

    @patch("fpl_client._get")
    def test_get_player_gameweek_points_zero_minutes(self, mock_get):
        """اختبار لاعب لم يلعب أو حقق 0 نقطة."""
        mock_get.return_value = {
            "history": [
                {"round": 1, "total_points": 0, "minutes": 0},
            ]
        }
        points = get_player_gameweek_points(player_id=102, gameweek=1)
        self.assertEqual(points, 0)
        self.assertIsInstance(points, int)

    @patch("fpl_client._get")
    def test_get_player_gameweek_points_round_not_found(self, mock_get):
        """اختبار جولة غير موجودة بتاريخ اللاعب (إرجاع 0 صراحة)."""
        mock_get.return_value = {
            "history": [
                {"round": 1, "total_points": 5, "minutes": 90},
            ]
        }
        points = get_player_gameweek_points(player_id=103, gameweek=5)
        self.assertEqual(points, 0)
        self.assertIsInstance(points, int)

    @patch("fpl_client._get")
    def test_get_player_gameweek_points_dgw(self, mock_get):
        """اختبار جولة مضاعفة DGW (مباراتان بنفس الجولة)."""
        mock_get.return_value = {
            "history": [
                {"round": 7, "total_points": 4, "minutes": 90},
                {"round": 7, "total_points": 8, "minutes": 90},
            ]
        }
        points = get_player_gameweek_points(player_id=104, gameweek=7)
        self.assertEqual(points, 12)

    @patch("fpl_client._get")
    def test_get_player_gameweek_points_api_error(self, mock_get):
        """اختبار خطأ في الاتصال (إرجاع 0 صراحة بدون رفع خطأ)."""
        mock_get.side_effect = Exception("API connection failed")
        points = get_player_gameweek_points(player_id=105, gameweek=3)
        self.assertEqual(points, 0)
        self.assertIsInstance(points, int)

    def test_get_player_gameweek_points_invalid_id(self):
        """اختبار تمرير معرف غير صالح."""
        self.assertEqual(get_player_gameweek_points(0, 1), 0)
        self.assertEqual(get_player_gameweek_points(None, 1), 0)


if __name__ == "__main__":
    unittest.main()
