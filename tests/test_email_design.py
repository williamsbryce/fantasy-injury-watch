"""Email appearance and delivery tests, with no real email sent."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.email_design import DASHBOARD_URL, email_html, email_text, message_html
from src.notify import send_resend

DOC = {
    "synced_at": "2026-11-20T02:22:13.547109+00:00",
    "leagues": [{
        "name": "CFFL Dynasty",
        "players_checked": 53,
        "lineup": {"state": "submitted", "starters_count": 17},
        "alerts": [
            {"name": "Blake Cashman", "position": "LB", "nfl_team": "MIN",
             "status": "Questionable", "details": "Concussion",
             "lineup_role": "bench", "group": "watch"},
            {"name": "Brandon Jones", "position": "S", "nfl_team": "DEN",
             "status": "Questionable", "details": "Hamstring",
             "lineup_role": "starter", "group": "watch"},
            {"name": "Anthony Hill Jr.", "position": "LB", "nfl_team": "TEN",
             "status": "Out", "details": "Neck",
             "lineup_role": "starter", "group": "action"},
        ],
    }],
}


class EmailDesignTests(unittest.TestCase):
    def test_email_groups_starters_first_and_includes_injury_details(self):
        html = email_html(DOC, "Thursday injury summary")
        text = email_text(DOC, "Thursday injury summary")
        self.assertLess(html.index("Starting lineup"), html.index("Bench"))
        self.assertLess(html.index("Anthony Hill Jr."), html.index("Brandon Jones"))
        self.assertLess(html.index("Brandon Jones"), html.index("Blake Cashman"))
        self.assertLess(text.index("Brandon Jones"), text.index("Blake Cashman"))
        self.assertIn("Concussion", html)
        self.assertIn("Hamstring", html)
        self.assertIn("Neck", html)
        self.assertIn("53 rostered players checked", html)
        self.assertIn(DASHBOARD_URL, html)

    def test_displays_saskatchewan_local_time_not_raw_iso_timestamp(self):
        html = email_html(DOC, "Thursday injury summary")
        self.assertIn("Nov 19, 2026 at 8:22 PM SK", html)
        self.assertNotIn("2026-11-20T02:22", html)

    def test_unknown_lineup_is_not_labeled_bench(self):
        doc = {
            "synced_at": DOC["synced_at"],
            "leagues": [{
                "name": "CFFL Dynasty", "players_checked": 1,
                "lineup": {"state": "unknown"},
                "alerts": [
                    {"name": "Unverified Player", "position": "RB", "nfl_team": "KC",
                     "status": "Questionable", "details": "Ankle",
                     "lineup_role": "unknown", "group": "watch"}
                ],
            }],
        }
        html = email_html(doc, "Sunday injury summary")
        self.assertIn("Lineup position unverified", html)
        self.assertNotIn("Starting lineup</", html)
        self.assertNotIn(">Bench</", html)

    def test_dynamic_text_is_html_escaped(self):
        doc = {
            "synced_at": DOC["synced_at"],
            "leagues": [{"name": "<script>danger</script>", "players_checked": 1,
                        "alerts": [{"name": "A&B <img src=x>", "status": "Questionable",
                                    "position": "LB", "nfl_team": "SEA",
                                    "details": "<img src=x>", "group": "watch"}]}]
        }
        html = email_html(doc, "<Important>")
        self.assertNotIn("<script>danger</script>", html)
        self.assertNotIn("<img src=x>", html)
        self.assertIn("&lt;script&gt;danger&lt;/script&gt;", html)
        self.assertIn("&lt;Important&gt;", html)
        self.assertIn("A&amp;B &lt;img src=x&gt;", html)
        self.assertIn("&lt;img src=x&gt;", message_html("Check", "<img src=x>"))

    def test_no_injuries_has_clear_empty_state(self):
        doc = {
            "synced_at": DOC["synced_at"],
            "leagues": [{"name": "CFFL Dynasty", "players_checked": 53, "alerts": []}],
        }
        self.assertIn("No active injury designations", email_html(doc, "Sunday injury summary"))

    def test_resend_payload_contains_html_and_text_fallback(self):
        class Response:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *args): return None
        html = email_html(DOC, "Thursday injury summary")
        text = email_text(DOC, "Thursday injury summary")
        with patch("src.notify.urllib.request.urlopen", return_value=Response()) as opener:
            ok = send_resend(
                "synthetic-test-token", "sender@example.org", "recipient@example.org",
                "BAWs Fantasy Injury Watch", text, html_body=html
            )
        self.assertTrue(ok)
        payload = json.loads(opener.call_args.args[0].data)
        self.assertEqual(payload["subject"], "BAWs Fantasy Injury Watch")
        self.assertIn("html", payload)
        self.assertIn("text", payload)
        self.assertIn("Starting lineup", payload["html"])
        self.assertIn("INJURED STARTERS", payload["text"])

    def test_original_text_only_calls_are_supported(self):
        class Response:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *args): return None
        with patch("src.notify.urllib.request.urlopen", return_value=Response()) as opener:
            self.assertTrue(send_resend("token", "sender@example.org",
                                        "recipient@example.org", "Test", "Plain body"))
        payload = json.loads(opener.call_args.args[0].data)
        self.assertEqual(payload["text"], "Plain body")
        self.assertNotIn("html", payload)


if __name__ == "__main__":
    unittest.main()
