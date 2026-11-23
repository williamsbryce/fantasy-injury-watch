"""Independent pregame RotoWire and NFL.com signal tests (no network)."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src import pregame_news as n

NOW = datetime(2026, 11, 22, 16, 40, tzinfo=timezone.utc)
PLAYERS = [{
    "player_id": "100", "name": "Anthony Hill Jr.", "nfl_team": "TEN",
    "lineup_role": "starter", "state": "pending",
    "kickoff": "2026-11-22T18:00:00+00:00",
}, {
    "player_id": "101", "name": "Brandon Jones", "nfl_team": "DEN",
    "lineup_role": "starter", "state": "pending",
    "kickoff": "2026-11-22T21:25:00+00:00",
}, {
    "player_id": "102", "name": "Bench Player", "nfl_team": "TEN",
    "lineup_role": "bench", "state": "pending",
    "kickoff": "2026-11-22T18:00:00+00:00",
}]
SOURCE = "https://www.rotowire.com/football/headlines/hill-example"


class PregameHeadlineTests(unittest.TestCase):
    def test_only_definitive_headlines_count(self):
        for text in ("Ruled out Sunday", "Won't play Sunday",
                     "Listed inactive for Week 11", "Not playing Sunday",
                     "Will miss Sunday", "Set to miss Week 11"):
            with self.subTest(headline=text):
                self.assertTrue(n.explicit_out(text))
        for text in ("Questionable for Sunday", "Not expected to play",
                     "Could be ruled out", "Not ruled out",
                     "Ruled out for remainder of game", "Unlikely to play",
                     "Cleared to play", "Available Sunday"):
            with self.subTest(headline=text):
                self.assertFalse(n.explicit_out(text))

    def test_date_within_same_sunday_week_only(self):
        self.assertTrue(n.fresh_on_sunday("November 22, 2026", NOW))
        self.assertTrue(n.fresh_on_sunday("November 20, 2026", NOW))
        self.assertFalse(n.fresh_on_sunday("November 19, 2026", NOW))
        self.assertFalse(n.fresh_on_sunday("November 29, 2026", NOW))
        self.assertFalse(n.fresh_on_sunday("Unclear", NOW))

    def test_rotowire_newest_headline_must_be_out_and_match_exact_name(self):
        updates = [
            {"title": "Anthony Hill Jr.: Cleared to play Sunday",
             "published": "November 22, 2026", "url": SOURCE},
            {"title": "Anthony Hill Jr.: Ruled out for Sunday",
             "published": "November 21, 2026", "url": SOURCE},
            {"title": "Other Hill: Ruled out", "published": "November 22, 2026",
             "url": SOURCE}
        ]
        with patch.object(n.rotowire, "_fetch_news_page", return_value=updates):
            self.assertEqual(n._rotowire_out_for_team("TEN", PLAYERS, NOW), {})
        updates[0] = {
            "title": "Anthony Hill Jr.: Won't play Sunday",
            "published": "November 22, 2026", "url": SOURCE,
        }
        with patch.object(n.rotowire, "_fetch_news_page", return_value=updates):
            found = n._rotowire_out_for_team("TEN", PLAYERS, NOW)
        self.assertEqual(list(found), ["100"])
        self.assertEqual(found["100"]["source"], "RotoWire")

    def test_old_or_untrusted_link_is_not_accepted(self):
        updates = [{"title": "Anthony Hill Jr.: Ruled out",
                    "published": "November 15, 2026", "url": SOURCE}]
        with patch.object(n.rotowire, "_fetch_news_page", return_value=updates):
            self.assertEqual(n._rotowire_out_for_team("TEN", PLAYERS, NOW), {})
        updates[0]["published"] = "November 22, 2026"
        updates[0]["url"] = "https://example.org/fake"
        with patch.object(n.rotowire, "_fetch_news_page", return_value=updates):
            self.assertEqual(n._rotowire_out_for_team("TEN", PLAYERS, NOW), {})

    def test_only_current_verified_starters_and_future_games_scanned(self):
        self.assertEqual(
            [p["player_id"] for p in n.candidates(PLAYERS, NOW)],
            ["100", "101"],
        )
        later = datetime(2026, 11, 22, 18, 1, tzinfo=timezone.utc)
        self.assertEqual([p["player_id"] for p in n.candidates(PLAYERS, later)],
                         ["101"])

    def test_nfl_sunday_pregame_report_extracts_explicit_out(self):
        html = (
            "<html><h1>NFL Week 11 injuries to monitor for Sunday's games</h1>"
            "<ul><li>LB Anthony Hill Jr. (neck) is inactive for Sunday's game.</li>"
            "<li>CB Brandon Jones (hamstring) is questionable for Week 11.</li>"
            "<li>Bench Player is not expected to play.</li></ul></html>"
        )
        found = n.parse_nfl_pregame(html, 11, PLAYERS)
        self.assertEqual(list(found), ["100"])
        self.assertEqual(found["100"]["source"], "NFL.com pregame report")
        self.assertEqual(n.parse_nfl_pregame(html, 12, PLAYERS), {})

    def test_news_checks_nfl_and_team_pages_with_no_mfl_injury_data(self):
        updates = [{
            "title": "Anthony Hill Jr.: Ruled out for Sunday",
            "published": "November 22, 2026", "url": SOURCE,
        }]
        with patch.object(n, "fetch_nfl_pregame", return_value={}) as nfl, \
             patch.object(n.rotowire, "_fetch_news_page", return_value=updates) as roto:
            found = n.fetch_pregame_reports(PLAYERS, 2026, 11, NOW)
        self.assertIn("100", found)
        self.assertNotIn("102", found)
        self.assertEqual(nfl.call_count, 1)
        self.assertGreater(roto.call_count, 0)


if __name__ == "__main__":
    unittest.main()
