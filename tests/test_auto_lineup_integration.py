"""No-network integration checks for alert, readback and write safety."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from decimal import Decimal
from src.auto_lineup_guard import run, AutoGuardFailure

ROOT = "src.auto_lineup_guard."


class AutoLineupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original = [str(i) for i in range(100, 117)]
        self.proposed = ["900"] + self.original[1:]
        self.form = {"starters": self.original, "all_selectable": self.original + ["900"],
                     "form_week_values": [11]}
        self.after_form = {"starters": self.proposed, "all_selectable": self.original + ["900"],
                           "form_week_values": [11]}
        self.plan = {
            "status": "ready", "proposed_lineup": self.proposed,
            "changes": [{
                "out_player_id": "100", "in_player_id": "900",
                "out_name": "Out Starter", "in_name": "Healthy Bench",
                "position": "RB", "recent_average": "15", "recent_games": 3,
            }], "unresolved": [],
        }
        self.env = {
            "GITHUB_REPOSITORY": "williamsbryce/fantasy-injury-watch",
            "GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "LINEUP_AUTOMATION_MODE": "LIVE", "LINEUP_WRITE_ENABLED": "true",
            "MFL_SEASON": "2026", "MFL_LEAGUE_ID": "40298",
            "MFL_FRANCHISE_ID": "0001", "MFL_OWNER_USERNAME": "fake",
            "MFL_OWNER_PASSWORD": "fake", "MFL_API_KEY": "fake",
            "RESEND_API_KEY": "fake", "ALERT_FROM": "sender@test.example",
            "ALERT_TO": "recipient@test.example",
        }
        self.now = datetime(2026, 11, 22, 17, tzinfo=timezone.utc)
        self.feeds = {
            "rosters": {"rosters": {"franchise": {
                "id": "0001", "player": [{"id": x} for x in self.original + ["900"]]
            }}},
            "players": {"players": {"player": []}},
            "injuries": {"injuries": {"injury": [{"id": "100", "status": "Out"}]}}
        }
        self.patches = []
        def mock(name, value=None, **kwargs):
            p = patch(ROOT + name, return_value=value, **kwargs)
            m = p.start()
            self.patches.append(p)
            return m
        self.mock = mock
        mock("discover_current_nfl_week", 11)
        mock("fetch_espn_week", {"TEN": datetime(2026, 11, 22, 18, tzinfo=timezone.utc)})
        mock("check_due", {"due": True, "reason": "pregame_window"})
        mock("_make_opener", object())
        mock("get_session", "MFL_USER_ID=fake")
        self.get_form = mock("get_form", side_effect=[
            ("<html></html>", self.form), ("<html></html>", self.form),
            ("<html></html>", self.after_form),
        ])
        mock("fetch_all", self.feeds)
        mock("check_injury_freshness")
        self.out_ids = mock("out_starter_ids", ["100"])
        mock("recent_scores_for_week", [{"900": Decimal("15")}])
        mock("rank_recent_weekly", {"900": {"average": Decimal("15"), "games": 3}})
        mock("eligible_teams", {"TEN"})
        self.selector = mock("select_replacements", self.plan)
        self.prepare = mock("prepare_post", ("https://www46.myfantasyleague.com/2026/lineup", b"safe"))
        self.submit = mock("submit_native", {"http_status": 200, "response_bytes": 50000})
        self.notify = mock("notify_owner")
        mock("time.sleep")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_live_writes_once_verifies_readback_and_emails(self):
        result = run(env=self.env, now=self.now)
        self.assertEqual(result["status"], "verified")
        self.submit.assert_called_once()
        self.prepare.assert_called_once()
        self.assertEqual(self.get_form.call_count, 3)
        self.notify.assert_called_once()
        self.assertIn("Lineup changed", self.notify.call_args.args[1])

    def test_dry_run_never_submits_or_emails(self):
        env = dict(self.env, LINEUP_AUTOMATION_MODE="DRY_RUN",
                   GITHUB_EVENT_NAME="workflow_dispatch")
        result = run(env=env, now=self.now)
        self.assertEqual(result["status"], "dry_run")
        self.submit.assert_not_called()
        self.notify.assert_not_called()

    def test_partial_valid_change_still_applies_and_reports_unresolved(self):
        partial = dict(self.plan)
        partial["status"] = "partial"
        partial["unresolved"] = [{"player_id": "101", "name": "Other Out",
                                   "reason": "no_healthy_same_position_bench_option_with_recent_scores"}]
        self.selector.return_value = partial
        result = run(env=self.env, now=self.now)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["unresolved"]), 1)
        self.submit.assert_called_once()
        self.assertIn("Other Out", self.notify.call_args.args[2])

    def test_owner_change_before_post_blocks_write_and_sends_alert(self):
        altered = dict(self.form)
        altered["starters"] = self.original[:-1] + ["900"]
        self.get_form.side_effect = [
            ("<html></html>", self.form), ("<html></html>", altered),
        ]
        with self.assertRaises(AutoGuardFailure):
            run(env=self.env, now=self.now)
        self.submit.assert_not_called()
        self.notify.assert_called_once()
        self.assertIn("IMPORTANT", self.notify.call_args.args[1])

    def test_unverified_post_sends_urgent_message_never_retries_or_reverts(self):
        self.get_form.side_effect = [
            ("<html></html>", self.form), ("<html></html>", self.form),
            ("<html></html>", self.form),
        ]
        with self.assertRaises(AutoGuardFailure):
            run(env=self.env, now=self.now)
        self.submit.assert_called_once()
        self.notify.assert_called_once()
        self.assertIn("UNVERIFIED WRITE", self.notify.call_args.args[2])

    def test_no_out_starter_never_fetches_scores_or_writes(self):
        self.out_ids.return_value = []
        result = run(env=self.env, now=self.now)
        self.assertEqual(result["status"], "healthy")
        self.submit.assert_not_called()
        self.notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
