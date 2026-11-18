import unittest
from src.lineup import LineupError, inspect_lineup, prepare_swap, verify_swap, player_ids


class LineupTests(unittest.TestCase):
    def setUp(self):
        self.weekly = {"weeklyResults": {"matchup": {"franchise": [
            {"id": "0001", "starters": "101,102,", "nonstarters": "103,"},
            {"id": "0002", "starters": "999,"},
        ]}}}
        self.roster = {"rosters": {"franchise": [
            {"id": "0001", "player": [{"id": "101", "status": "ROSTER"},
                                       {"id": "102", "status": "ROSTER"},
                                       {"id": "103", "status": "ROSTER"},
                                       {"id": "104", "status": "IR"}]},
        ]}}
        self.players = {"players": {"player": [
            {"id": "101", "name": "Alpha, First", "position": "RB", "team": "GB"},
            {"id": "102", "name": "Beta, Second", "position": "WR", "team": "SF"},
            {"id": "103", "name": "Gamma, Third", "position": "RB", "team": "PHI"},
            {"id": "104", "name": "Delta, Fourth", "position": "RB", "team": "NYG"},
        ]}}

    def test_weekly_lineup_and_bench(self):
        d = inspect_lineup(self.weekly, self.roster, self.players, "0001")
        self.assertEqual(d["starter_ids"], ["101", "102"])
        self.assertEqual([p["id"] for p in d["bench"]], ["103"])
        self.assertEqual(d["starters"][0]["name"], "First Alpha")

    def test_same_position_swap_keeps_all_other_starters(self):
        d = inspect_lineup(self.weekly, self.roster, self.players, "0001")
        proposed = prepare_swap(d, "101", "103")
        self.assertEqual(proposed, ["103", "102"])
        self.assertTrue(verify_swap(d["starter_ids"], proposed, "101", "103"))

    def test_cross_position_swap_rejected(self):
        d = inspect_lineup(self.weekly, self.roster, self.players, "0001")
        with self.assertRaisesRegex(LineupError, "same-position"):
            prepare_swap(d, "102", "103")

    def test_ir_candidate_rejected(self):
        d = inspect_lineup(self.weekly, self.roster, self.players, "0001")
        with self.assertRaisesRegex(LineupError, "eligible bench"):
            prepare_swap(d, "101", "104")

    def test_missing_submitted_lineup_fails_closed(self):
        with self.assertRaisesRegex(LineupError, "No submitted"):
            inspect_lineup({"weeklyResults": {"franchise": {"id": "0001", "starters": ""}}},
                           self.roster, self.players, "0001")

    def test_invalid_source_rejected(self):
        self.assertRaises(LineupError, player_ids, "101,101,")
        self.assertRaises(LineupError, player_ids, "101,xyz")
        self.assertRaises(LineupError, inspect_lineup, {"weeklyResults": {}},
                          self.roster, self.players, "0001")

    def test_verify_requires_exact_one_out_one_in(self):
        self.assertFalse(verify_swap(["1", "2"], ["3", "4"], "1", "3"))
        self.assertFalse(verify_swap(["1", "2"], ["3", "3"], "1", "3"))


if __name__ == "__main__":
    unittest.main()
