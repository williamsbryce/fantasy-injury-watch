"""Offline regression tests for autonomous CFFL lineup choice and safeguards."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from src.auto_lineup_policy import select_replacements, AutoLineupError
from src.auto_lineup_schedule import check_due
from src.auto_lineup_guard import live_allowed, check_injury_freshness
from src.recent_scores import parse_week_scores, rank_recent_weekly, RecentScoresError
from src.mfl_native_lineup import prepare_post
from src.manual_lineup_test import ManualSwapError


class AutoGuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.starters = [str(i) for i in range(100, 117)]
        self.starters[0] = "500"  # Out RB
        self.starters[1] = "600"  # Out LB, no healthy bench player
        self.bench = ["501", "502", "503", "601"]
        all_players = self.starters + self.bench
        roster = [{"id": x, "status": "ROSTER"} for x in all_players]
        ids = [
            {"id": x, "position": "WR", "name": f"Player, Starter{x}", "team": "TEN"}
            for x in self.starters if x not in ("500", "600")
        ]
        ids.extend([
            {"id": "500", "position": "RB", "name": "Out, Runner", "team": "TEN"},
            {"id": "600", "position": "LB", "name": "Out, Defender", "team": "TEN"},
            {"id": "501", "position": "RB", "name": "Healthy, Runner", "team": "TEN"},
            {"id": "502", "position": "RB", "name": "Questionable, Runner", "team": "TEN"},
            {"id": "503", "position": "RB", "name": "Bye, Runner", "team": "SEA"},
            {"id": "601", "position": "LB", "name": "Questionable, Defender", "team": "TEN"},
        ])
        self.feeds = {
            "rosters": {"rosters": {"franchise": {"id": "0001", "player": roster}}},
            "players": {"players": {"player": ids}},
            "injuries": {"injuries": {"timestamp": "1795028465", "injury": [
                {"id": "500", "status": "Out"},
                {"id": "600", "status": "Inactive"},
                {"id": "502", "status": "Questionable"},
                {"id": "601", "status": "Questionable"},
            ]}},
        }
        self.recent = {
            "501": {"average": Decimal("9"), "games": 3},
            "502": {"average": Decimal("25"), "games": 3},
            "503": {"average": Decimal("30"), "games": 3},
            "601": {"average": Decimal("30"), "games": 3},
        }

    def test_partial_swap_succeeds_when_second_out_starter_has_no_bench(self):
        p = select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"TEN"})
        self.assertEqual(p["status"], "partial")
        self.assertEqual(p["proposed_lineup"][0], "501")
        self.assertEqual(p["proposed_lineup"][1], "600")
        self.assertEqual(len(p["changes"]), 1)
        self.assertEqual(len(p["unresolved"]), 1)
        self.assertEqual(p["changes"][0]["recent_average"], "9")

    def test_only_healthy_same_position_players_selected(self):
        self.feeds["injuries"]["injuries"]["injury"] = [
            {"id": "500", "status": "Out"}, {"id": "600", "status": "Inactive"},
            {"id": "502", "status": "Questionable"}, {"id": "601", "status": "Doubtful"}]
        p = select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"TEN"})
        self.assertEqual([c["in_player_id"] for c in p["changes"]], ["501"])
        self.assertEqual(p["proposed_lineup"][2:], self.starters[2:])

    def test_other_starter_kept_even_if_healthy_bench_has_more_points(self):
        self.feeds["injuries"]["injuries"]["injury"] = []
        self.recent["501"]["average"] = Decimal("200")
        p = select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"TEN"})
        self.assertEqual(p["status"], "healthy")
        self.assertEqual(p["proposed_lineup"], self.starters)

    def test_does_not_swap_players_after_own_game_started(self):
        p = select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"SEA"})
        self.assertEqual(p["status"], "unresolved")
        self.assertEqual(p["changes"], [])

    def test_prevents_ir_taxi_or_missing_scoring_candidate(self):
        self.feeds["rosters"]["rosters"]["franchise"]["player"][-4]["status"] = "IR"
        p = select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"TEN"})
        self.assertEqual(len(p["changes"]), 0)
        self.assertEqual(len(p["unresolved"]), 2)

    def test_missing_injury_feed_is_not_an_all_clear(self):
        del self.feeds["injuries"]["injuries"]["injury"]
        with self.assertRaises(AutoLineupError):
            select_replacements(self.starters, self.starters + self.bench,
                                self.feeds, self.recent, {"TEN"})

    def test_freshness_rejects_old_or_missing_mfl_timestamp(self):
        now = datetime.fromtimestamp(1795028465, timezone.utc)
        check_injury_freshness(self.feeds, now + timedelta(hours=2))
        with self.assertRaises(Exception):
            check_injury_freshness(self.feeds, now + timedelta(hours=5))
        self.feeds["injuries"]["injuries"].pop("timestamp")
        with self.assertRaises(Exception):
            check_injury_freshness(self.feeds, now)


class RecentScoreTests(unittest.TestCase):
    def test_recent_three_observed_scores_not_season_average(self):
        scores = [
            {"501": Decimal("14.0"), "502": Decimal("30")},
            {"501": Decimal("8.0"), "502": Decimal("0")},
            {"501": Decimal("20.0"), "502": Decimal("24")},
            {"501": Decimal("100.0"), "502": Decimal("90")},
        ]
        r = rank_recent_weekly(scores, ["501", "502", "missing"])
        self.assertEqual(r["501"]["average"], Decimal("14.0"))
        self.assertEqual(r["502"]["average"], Decimal("18"))
        self.assertEqual(r["501"]["games"], 3)
        self.assertNotIn("missing", r)

    def test_sparse_player_uses_available_completed_score_records(self):
        r = rank_recent_weekly([{}, {"503": Decimal("5")}, {}], ["503"])
        self.assertEqual(r["503"]["games"], 1)
        self.assertEqual(r["503"]["average"], Decimal("5"))

    def test_mfl_score_schema_parses_and_fails_when_empty(self):
        self.assertEqual(parse_week_scores({"playerScores": {"playerScore": [
            {"id": "501", "score": "12.25"},
            {"id": "502", "score": "0"},
        ]}}), {"501": Decimal("12.25"), "502": Decimal("0")})
        with self.assertRaises(RecentScoresError):
            parse_week_scores({"playerScores": {}})


class ScheduleAndAuthTests(unittest.TestCase):
    def test_only_thursday_or_sunday_first_game_window(self):
        # 2026 Nov 22 is Sunday. First kickoff 18:00 UTC, check at 17:00.
        first = datetime(2026, 11, 22, 18, tzinfo=timezone.utc)
        schedule = {"TEN": first, "NYJ": first + timedelta(hours=3)}
        self.assertTrue(check_due(schedule, first - timedelta(minutes=60))["due"])
        self.assertFalse(check_due(schedule, first - timedelta(minutes=20))["due"])
        self.assertFalse(check_due(schedule, first - timedelta(days=1))["due"])

    def test_thursday_game_window(self):
        first = datetime(2026, 11, 20, 1, 15, tzinfo=timezone.utc)
        self.assertTrue(check_due({"TEN": first}, first - timedelta(minutes=60))["due"])

    def test_live_requires_scheduled_main_and_explicit_enable(self):
        e = {
            "LINEUP_AUTOMATION_MODE": "LIVE",
            "LINEUP_WRITE_ENABLED": "true",
            "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "williamsbryce/fantasy-injury-watch",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        self.assertTrue(live_allowed(e))
        for key, value in (
            ("GITHUB_EVENT_NAME", "workflow_dispatch"),
            ("LINEUP_WRITE_ENABLED", "false"),
            ("GITHUB_REF", "refs/heads/feature/out-starter-guard"),
            ("GITHUB_RUN_ATTEMPT", "2"),
        ):
            with self.subTest(key=key):
                wrong = dict(e)
                wrong[key] = value
                self.assertFalse(live_allowed(wrong))


if __name__ == "__main__":
    unittest.main()
