"""Synthetic, completely offline tests for the single authorized swap-and-restore harness."""
import unittest
from datetime import datetime, timedelta, timezone
from src.reversible_lineup_test import identify_pair, verify_list, validate_one_shot_environment
from src.manual_lineup_test import ManualSwapError


class ReversibleSwapSafetyTests(unittest.TestCase):
    def setUp(self):
        self.start = [str(n) for n in range(100, 117)]
        self.start[3] = "500"
        self.before = {
            "form_week_values": [11], "starters": self.start,
            "all_selectable": self.start + ["501", "503"],
        }
        self.rosters = {"rosters": {"franchise": [{
            "id": "0001", "player": [
                *[{"id": p, "status": "ROSTER"} for p in self.start],
                {"id": "501", "status": "ROSTER"},
                {"id": "503", "status": "ROSTER"},
            ],
        }]}}
        self.players = {"players": {"player": [
            *[{"id": p, "name": ("Gray, Cedric" if p == "500" else "Some, Starter"),
               "position": "LB" if p == "500" else "WR",
               "team": "TEN" if p == "500" else "CHI"} for p in self.start],
            {"id": "501", "name": "Hill Jr., Anthony", "position": "LB", "team": "TEN"},
            {"id": "503", "name": "Wrong, Player", "position": "QB", "team": "TEN"},
        ]}}
        self.schedule = {"TEN": datetime.now(timezone.utc) + timedelta(days=3)}

    def test_swap_preserves_other_16_starters(self):
        original, proposed = identify_pair(self.before, self.rosters,
                                           self.players, self.schedule)
        self.assertEqual(proposed[3], "501")
        self.assertEqual({p for p in original if p != "500"},
                         {p for p in proposed if p != "501"})
        self.assertTrue(verify_list(original, self.before["starters"]))
        self.assertFalse(verify_list(original, proposed))

    def test_refuse_wrong_week(self):
        self.before["form_week_values"] = [12]
        with self.assertRaisesRegex(ManualSwapError, "Week 11"):
            identify_pair(self.before, self.rosters, self.players, self.schedule)

    def test_refuse_unselectable_replacement(self):
        self.before["all_selectable"].remove("501")
        with self.assertRaisesRegex(ManualSwapError, "not selectable"):
            identify_pair(self.before, self.rosters, self.players, self.schedule)

    def test_refuse_team_bye(self):
        self.schedule = {"DAL": datetime.now(timezone.utc) + timedelta(days=3)}
        with self.assertRaisesRegex(ManualSwapError, "Tennessee"):
            identify_pair(self.before, self.rosters, self.players, self.schedule)

    def test_refuse_kickoff_less_than_four_hours(self):
        self.schedule["TEN"] = datetime.now(timezone.utc) + timedelta(hours=2)
        with self.assertRaisesRegex(ManualSwapError, "kickoff"):
            identify_pair(self.before, self.rosters, self.players, self.schedule)

    def test_refuse_inactive_bench_roster(self):
        self.rosters["rosters"]["franchise"][0]["player"][-2]["status"] = "IR"
        with self.assertRaisesRegex(ManualSwapError, "active roster"):
            identify_pair(self.before, self.rosters, self.players, self.schedule)

    def test_reject_unapproved_run(self):
        env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "williamsbryce/fantasy-injury-watch",
            "GITHUB_ACTOR": "williamsbryce",
            "LIVE_REVERSIBLE_TEST": "AUTHORIZED_CEDRIC_GRAY_TO_ANTHONY_HILL_WEEK_11",
            "CONFIRM_SWAP_RESTORE": "APPROVE CEDRIC GRAY TO ANTHONY HILL JR WEEK 11 AND RESTORE",
        }
        validate_one_shot_environment(env)
        for key, value in [
            ("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_REF", "refs/heads/feature/out-starter-guard"),
            ("LIVE_REVERSIBLE_TEST", "yes"),
            ("GITHUB_ACTOR", "someone-else"),
            ("CONFIRM_SWAP_RESTORE", "wrong"),
        ]:
            with self.subTest(key=key):
                modified = dict(env)
                modified[key] = value
                with self.assertRaises(ManualSwapError):
                    validate_one_shot_environment(modified)


if __name__ == "__main__":
    unittest.main()
