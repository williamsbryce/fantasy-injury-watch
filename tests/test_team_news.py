"""Targeted RotoWire team pages fill gaps in the general news list."""
import unittest
from unittest.mock import patch

from src.news import fetch_recent_news, _matches_player


class TeamNewsTests(unittest.TestCase):
    def test_brandon_jones_appears_even_when_missing_from_global_feed(self):
        main = [{"title": "Other Person: Limited in practice", "url": "https://www.rotowire.com/example"}]
        broncos = [{
            "title": "Brandon Jones: Still working through hamstring issue",
            "published": "November 18, 2026",
            "source": "RotoWire",
            "url": "https://www.rotowire.com/football/headlines/brandon-jones-injury-123",
        }]
        def fetch(url="https://www.rotowire.com/football/news.php"):
            return broncos if url.endswith("team=DEN") else main
        alert = {"name": "Brandon Jones", "nfl_team": "DEN"}
        with patch("src.news._fetch_news_page", side_effect=fetch) as mocked:
            found = fetch_recent_news([alert])
        self.assertTrue(any(_matches_player(item["title"], "Brandon Jones")
                            for item in found))
        self.assertEqual(mocked.call_count, 2)

    def test_team_request_skipped_if_player_already_present(self):
        articles = [{"title": "Brandon Jones: Limited Wednesday",
                     "url": "https://www.rotowire.com/somewhere"}]
        with patch("src.news._fetch_news_page", return_value=articles) as mocked:
            found = fetch_recent_news([{"name": "Brandon Jones", "nfl_team": "DEN"}])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(found, articles)

    def test_invalid_team_is_not_used_for_url(self):
        with patch("src.news._fetch_news_page", return_value=[]) as mocked, \
             patch("src.news._fetch_rss", return_value=None):
            self.assertIsNone(fetch_recent_news([
                {"name": "Brandon Jones", "nfl_team": "DEN&APIKEY=x"}
            ]))
        self.assertEqual(mocked.call_count, 1)

    def test_mfl_aliases_to_rotowire_team_codes(self):
        with patch("src.news._fetch_news_page", return_value=[]) as mocked, \
             patch("src.news._fetch_rss", return_value=[]):
            fetch_recent_news([{"name": "Person", "nfl_team": "SFO"}])
        self.assertEqual(mocked.call_args.args[0],
                         "https://www.rotowire.com/football/news.php?team=SF")


if __name__ == "__main__":
    unittest.main()
