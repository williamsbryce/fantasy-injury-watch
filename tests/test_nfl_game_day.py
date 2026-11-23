"""Official NFL inactive lists override uncertainty, not the MFL lineup."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from src import nfl_game_day as game

NOW = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)  # 11 AM SK, Sunday
GAME = {
    "week": 11,
    "games": [{
        "kickoff": datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc),
        "teams": ["TEN", "DAL"],
    }, {
        "kickoff": datetime(2026, 11, 22, 21, 25, tzinfo=timezone.utc),
        "teams": ["DEN", "LV"],
    }],
}
HTML = (
    "<html><head><title>NFL football inactives</title></head><body><article>"
    "<h1>NFL Week 11 inactives: Players ruled out for Sunday's 11 games</h1>"
    "<h2>EARLY GAMES</h2>"
    "<h3>TITANS</h3><ul>"
    "<li>RB Nick Singleton</li><li>CB Jaylon Jones</li>"
    "<li>LB Mohamoud Diabate</li><li>OT Brandon Crenshaw-Dickson</li>"
    "<li>DT Jackie Marshall</li></ul>"
    "<h3>COWBOYS</h3><ul>"
    "<li>S P.J. Locke III</li><li>WR Jonathan Mingo</li>"
    "<li>G Tyler Booker</li><li>LB Jaishawn Barham</li>"
    "<li>TE Jake Ferguson</li><li>DT Jonathan Bullard</li></ul>"
    "<h2>RELATED CONTENT</h2><ul><li>Anthony Hill inactive for other week</li></ul>"
    + "<p>Official NFL list</p>" * 35
    + "</article></body></html>"
)
PLAYERS = [
    {"player_id": "17560", "name": "Anthony Hill Jr.", "position": "LB",
     "nfl_team": "TEN", "lineup_role": "bench"},
    {"player_id": "200", "name": "Nick Singleton", "position": "RB",
     "nfl_team": "TEN", "lineup_role": "starter"},
    {"player_id": "201", "name": "Brandon Jones", "position": "S",
     "nfl_team": "DEN", "lineup_role": "starter"},
]
REPORT = {
    "synced_at": "2026-11-22T11:33:51Z",
    "leagues": [{
        "id": "40298", "players_checked": 53,
        "lineup": {"state": "submitted", "week": 11},
        "alerts": [
            {"player_id": "17560", "name": "Anthony Hill Jr.",
             "nfl_team": "TEN", "status": "Questionable", "lineup_role": "bench"},
            {"player_id": "201", "name": "Brandon Jones",
             "nfl_team": "DEN", "status": "Questionable", "lineup_role": "starter"},
        ]
    }]
}


class OfficialHTMLTests(unittest.TestCase):
    def test_nfl_official_article_lists_only_verified_teams(self):
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        self.assertEqual(sorted(lists), ["DAL", "TEN"])
        self.assertEqual(len(lists["TEN"]), 5)
        self.assertEqual(len(lists["DAL"]), 6)
        self.assertEqual(game.classify_player(PLAYERS[0], GAME["games"], lists)["state"],
                         "eligible")
        self.assertEqual(game.classify_player(PLAYERS[1], GAME["games"], lists)["state"],
                         "inactive")
        self.assertEqual(game.classify_player(PLAYERS[2], GAME["games"], lists)["state"],
                         "pending")

    def test_wrong_week_does_not_make_a_player_eligible(self):
        self.assertEqual(game.parse_nfl_inactives(HTML, 2026, 12), {})
        self.assertEqual(game.parse_nfl_inactives(HTML.replace("inactives:", "practices:"),
                                                  2026, 11), {})

    def test_partial_team_list_refuses_positive_confirmation(self):
        partial = HTML.replace("<li>CB Jaylon Jones</li>", "")
        partial = partial.replace("<li>LB Mohamoud Diabate</li>", "")
        lists = game.parse_nfl_inactives(partial, 2026, 11)
        self.assertNotIn("TEN", lists)
        self.assertEqual(game.classify_player(PLAYERS[0], GAME["games"], lists)["state"],
                         "pending")

    def test_normalize_suffixes_without_matching_wrong_surname(self):
        self.assertEqual(game._name("LB Anthony Hill Jr."), "anthony hill")
        self.assertNotEqual(game._name("Anthony Harris"), "anthony hill")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.report = root / "report.json"
        self.snapshot = root / "game-day.json"
        self.report.write_text(json.dumps(REPORT))
        self.paths = patch.multiple(game, REPORT_PATH=self.report,
                                    GAME_DAY_PATH=self.snapshot)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.env = patch.dict("os.environ", {
            "MFL_SEASON": "2026", "MFL_LEAGUE_ID": "40298",
            "MFL_FRANCHISE_ID": "0001", "MFL_API_KEY": "",
            "RESEND_API_KEY": "test-key", "ALERT_FROM": "from@example.com",
            "ALERT_TO": "to@example.com", "GITHUB_RUN_ID": "1234567",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_only_confirmed_roster_statuses_get_emails(self):
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        self.assertTrue(game.prepare(NOW, context=GAME,
                                     official=(lists, game.official_sunday_url(2026, 11)),
                                     roster=PLAYERS))
        snapshot = json.loads(self.snapshot.read_text())
        self.assertEqual(snapshot["week"], 11)
        states = {p["name"]: p["state"] for p in snapshot["players"]}
        self.assertEqual(states["Anthony Hill Jr."], "eligible")
        self.assertEqual(states["Nick Singleton"], "inactive")
        self.assertEqual(states["Brandon Jones"], "pending")
        batch = snapshot["pending_batch"]
        self.assertEqual(len(batch["items"]), 1)
        self.assertIn("Nick Singleton", batch["text"])
        self.assertIn("OFFICIALLY INACTIVE | FANTASY STARTER", batch["text"])
        self.assertNotIn("Anthony Hill Jr.", batch["text"])
        with patch.object(game, "send_resend", return_value=True) as mock_sender:
            self.assertTrue(game.send(NOW))
            self.assertFalse(game.send(NOW))
            mock_sender.assert_called_once()
        confirmed = json.loads(self.snapshot.read_text())
        self.assertIsNone(confirmed["pending_batch"])
        self.assertEqual(len(confirmed["notified_keys"]), 1)
        self.assertEqual(mock_sender.call_args.kwargs["idempotency_key"],
                         batch["idempotency_key"])
        # Repeat the same list: never send twice.
        self.assertTrue(game.prepare(NOW, context=GAME,
                                     official=(lists, game.official_sunday_url(2026, 11)),
                                     roster=PLAYERS))
        self.assertIsNone(json.loads(self.snapshot.read_text())["pending_batch"])

    def test_no_source_is_not_healthy_and_does_not_send_email(self):
        self.assertTrue(game.prepare(NOW, context=GAME,
                                     official=({}, game.official_sunday_url(2026, 11)),
                                     roster=PLAYERS))
        snapshot = json.loads(self.snapshot.read_text())
        self.assertEqual({p["state"] for p in snapshot["players"]}, {"pending"})
        self.assertIsNone(snapshot["pending_batch"])
        with patch.object(game, "send_resend") as sender:
            self.assertFalse(game.send(NOW))
            sender.assert_not_called()

    def test_missing_official_list_near_kickoff_does_not_spam(self):
        close_to_kickoff = datetime(2026, 11, 22, 17, 30, tzinfo=timezone.utc)
        game.prepare(close_to_kickoff, context=GAME,
                     official=({}, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        state = json.loads(self.snapshot.read_text())
        self.assertEqual({p["state"] for p in state["players"]}, {"pending"})
        self.assertIsNone(state["pending_batch"])
        with patch.object(game, "send_resend") as sender:
            self.assertFalse(game.send(close_to_kickoff))
            sender.assert_not_called()

    def test_eligible_starter_and_inactive_bench_do_not_send(self):
        players = [
            {**PLAYERS[0], "lineup_role": "starter"},
            {**PLAYERS[1], "lineup_role": "bench"},
            PLAYERS[2],
        ]
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=players)
        state = json.loads(self.snapshot.read_text())
        self.assertIsNone(state["pending_batch"])
        self.assertEqual(state["players"][0]["state"], "eligible")
        self.assertEqual(state["players"][1]["state"], "inactive")

    def test_late_official_inactive_is_not_emailed_after_kickoff(self):
        from datetime import timedelta
        late = GAME["games"][0]["kickoff"] + timedelta(minutes=1)
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(late, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        self.assertIsNone(json.loads(self.snapshot.read_text())["pending_batch"])
        with patch.object(game, "send_resend") as sender:
            self.assertFalse(game.send(late))
            sender.assert_not_called()

    def test_batch_expires_between_preparation_and_delivery(self):
        from datetime import timedelta
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        late = GAME["games"][0]["kickoff"] - timedelta(minutes=4)
        with patch.object(game, "send_resend") as sender:
            self.assertFalse(game.send(late))
            sender.assert_not_called()
        self.assertIsNone(json.loads(self.snapshot.read_text())["pending_batch"])

    def test_obsolete_eligible_notifications_are_not_retried(self):
        prior = {
            "date": "2026-11-22", "week": 11, "notified_keys": [],
            "pending_batch": {
                "items": [{"name": "Anthony Hill Jr.", "player_id": "17560",
                           "state": "eligible", "lineup_role": "bench",
                           "kickoff": GAME["games"][0]["kickoff"].isoformat()}],
                "text": "Old eligibility email", "html": "<p>Old</p>",
                "idempotency_key": "old",
            },
        }
        self.snapshot.write_text(json.dumps(prior))
        players = [{**PLAYERS[1], "lineup_role": "bench"}, PLAYERS[0], PLAYERS[2]]
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=players)
        self.assertIsNone(json.loads(self.snapshot.read_text())["pending_batch"])

    def test_cached_injured_starter_does_not_authorize_email(self):
        players = game.cached_players(REPORT, 2026, 11)
        self.assertTrue(players)
        self.assertTrue(all(p["lineup_role"] == "unknown" for p in players))

    def test_injured_reserve_is_not_mistaken_for_eligible(self):
        report = json.loads(self.report.read_text())
        report["leagues"][0]["alerts"].append({
            "player_id": "200", "name": "Nick Singleton", "nfl_team": "TEN",
            "status": "IR", "lineup_role": "starter",
        })
        self.report.write_text(json.dumps(report))
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        state = json.loads(self.snapshot.read_text())
        person = next(p for p in state["players"] if p["name"] == "Nick Singleton")
        self.assertEqual(person["state"], "unavailable")
        self.assertIsNone(state["pending_batch"])

    def test_regular_healthy_bench_players_are_not_published(self):
        players = PLAYERS + [{
            "player_id": "999", "name": "Healthy Bench", "position": "RB",
            "nfl_team": "TEN", "lineup_role": "bench",
        }]
        game.prepare(NOW, context=GAME, official=({}, game.official_sunday_url(2026, 11)),
                     roster=players)
        names = [p["name"] for p in json.loads(self.snapshot.read_text())["players"]]
        self.assertNotIn("Healthy Bench", names)

    def test_keeps_verified_status_during_short_source_outage(self):
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        game.prepare(NOW, context=GAME,
                     official=({}, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        snapshot = json.loads(self.snapshot.read_text())
        by_name = {p["name"]: p["state"] for p in snapshot["players"]}
        self.assertEqual(by_name["Anthony Hill Jr."], "eligible")
        self.assertEqual(by_name["Nick Singleton"], "inactive")

    def test_late_game_unknown_until_its_team_list_publishes(self):
        lists = game.parse_nfl_inactives(HTML, 2026, 11)
        game.prepare(NOW, context=GAME,
                     official=(lists, game.official_sunday_url(2026, 11)),
                     roster=PLAYERS)
        self.assertEqual(json.loads(self.snapshot.read_text())["players"][2]["state"],
                         "pending")

    def test_only_sunday_games_considered(self):
        other = {"week": 11, "games": [{
            "kickoff": datetime(2026, 11, 23, 18, 0, tzinfo=timezone.utc),
            "teams": ["TEN", "DAL"],
        }]}
        self.assertFalse(game.prepare(NOW, context=other,
                                      official=({}, game.official_sunday_url(2026, 11)),
                                      roster=PLAYERS))


if __name__ == "__main__":
    unittest.main()
