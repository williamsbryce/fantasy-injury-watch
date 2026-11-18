"""Read-only lineup guard tests. No MFL write credentials or API calls."""
import unittest

from src.lineup_guard import find_unavailable_starters, read_submitted_starters


def feeds():
    return {
        "rosters": {"rosters": {"franchise": {
            "id": "0001", "player": [
                {"id": "111", "status": "ROSTER"},
                {"id": "222", "status": "ROSTER"},
                {"id": "333", "status": "ROSTER"},
                {"id": "444", "status": "ROSTER"},
                {"id": "555", "status": "INJURED_RESERVE"},
                {"id": "0532", "status": "ROSTER"},
                {"id": "666", "status": "ROSTER"},
            ]}}},
        "players": {"players": {"player": [
            {"id": "111", "name": "Smith, Out", "position": "WR"},
            {"id": "222", "name": "Jones, Healthy", "position": "WR"},
            {"id": "333", "name": "Brown, Questionable", "position": "WR"},
            {"id": "444", "name": "Back, Out", "position": "RB"},
            {"id": "555", "name": "Injured, Reserve", "position": "WR"},
            {"id": "0532", "name": "Texans, Defense", "position": "Def"},
            {"id": "666", "name": "Runner, Doubtful", "position": "RB"},
        ]}},
        "injuries": {"injuries": {"injury": [
            {"id": "111", "status": "Out"},
            {"id": "333", "status": "Questionable"},
            {"id": "444", "status": "Out"},
            {"id": "555", "status": "Out"},
            {"id": "666", "status": "Doubtful"},
        ]}},
    }


def weekly(starters="111,0532,666,"):
    return {"weeklyResults": {"matchup": {"franchise": [
        {"id": "0001", "starters": starters},
        {"id": "0002", "starters": "888"},
    ]}}}


class TestLineupGuard(unittest.TestCase):
    def test_out_starter_found_bench_out_excluded(self):
        result = find_unavailable_starters(weekly(), feeds(), "0001")
        self.assertTrue(result["lineup_submitted"])
        self.assertEqual(result["starter_ids"], ["111", "0532", "666"])
        self.assertEqual(len(result["unavailable_starters"]), 1)
        issue = result["unavailable_starters"][0]
        self.assertEqual(issue["player_id"], "111")
        # Healthy exact-position candidate first; questionable noted separately.
        self.assertEqual(
            [p["player_id"] for p in issue["preliminary_same_position_bench"]],
            ["222", "333"],
        )
        self.assertEqual(issue["preliminary_same_position_bench"][1]["injury_status"],
                         "Questionable")

    def test_blank_lineup_does_not_mean_safe_or_submitted(self):
        result = find_unavailable_starters(weekly(""), feeds(), "0001")
        self.assertFalse(result["lineup_submitted"])
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["unavailable_starters"], [])

    def test_preserve_zero_prefixed_defense_id(self):
        self.assertIn("0532", read_submitted_starters(weekly(), "0001"))

    def test_legacy_flat_franchises(self):
        payload = {"weeklyResults": {"franchise": {"id": "0001", "starters": "111,0532"}}}
        self.assertEqual(read_submitted_starters(payload, "0001"), ["111", "0532"])

    def test_player_row_fallback(self):
        payload = {"weeklyResults": {"franchise": {"id": "0001", "player": [
            {"id": "111", "status": "starter"}, {"id": "222", "status": "nonstarter"},
        ]}}}
        self.assertEqual(read_submitted_starters(payload, "0001"), ["111"])

    def test_duplicate_starters_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            read_submitted_starters(weekly("111,111"), "0001")

    def test_missing_franchise_or_feed_rejected(self):
        with self.assertRaises(ValueError):
            read_submitted_starters(weekly(), "0003")
        with self.assertRaises(ValueError):
            read_submitted_starters({}, "0001")

    def test_stale_lineup_vs_roster_rejected(self):
        with self.assertRaisesRegex(ValueError, "reconciled"):
            find_unavailable_starters(weekly("111,999"), feeds(), "0001")


if __name__ == "__main__":
    unittest.main()
