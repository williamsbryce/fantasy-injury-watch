import copy
import unittest
from datetime import datetime, timezone
from src.mfl_article_headlines import find_headline, enrich_mfl_headlines

PAGE = '''<html><body>
<label>Show all news articles involving <select><option>Jones, Brandon DEN S</option></select></label>
<h3>SEARCH RESULTS - NEWEST ARTICLES LISTED FIRST</h3>
<table>
<tr><th>ARTICLE HEADLINE</th><th>ARTICLE SUMMARY</th><th>PUBLISHED</th></tr>
<tr><td><a href="/2026/story?foo=123">S Brandon Jones: Still working through hamstring issue</a></td>
<td>(RotoWire) Jones was a limited participant in practice.</td><td>17 hours</td></tr>
</table></body></html>'''


class MFLArticleHeadlineTests(unittest.TestCase):
    def test_extracts_article_title_from_user_example(self):
        self.assertEqual(
            find_headline(PAGE, "Brandon Jones"),
            "S Brandon Jones: Still working through hamstring issue"
        )

    def test_requires_exact_player_identity_not_an_incidental_reference(self):
        self.assertIsNone(find_headline(PAGE, "Anthony Hill Jr."))
        self.assertIsNone(find_headline(PAGE, "Brandon Johnson"))
        self.assertIsNone(find_headline("<html><a>Brandon Jones: Not verified</a></html>",
                                        "Brandon Jones"))

    def test_untrusted_script_or_unrelated_anchor_is_ignored(self):
        page = '''<html><body><h3>SEARCH RESULTS - NEWEST ARTICLES LISTED FIRST</h3>
        <script>Brandon Jones: javascript title</script>
        <a>Another Person: Brandon Jones was mentioned</a>
        <a>Brandon Jones: Limited in Wednesday practice</a>
        </body></html>'''
        self.assertEqual(find_headline(page, "Brandon Jones"),
                         "Brandon Jones: Limited in Wednesday practice")

    def test_preserves_older_roster_and_injury_data(self):
        doc = {
            "synced_at": "2026-11-18T00:00:00+00:00",
            "sent_digest_date": "2026-11-18",
            "leagues": [{
                "id": "40298",
                "lineup": {"state": "submitted"},
                "alerts": [{
                    "name": "Brandon Jones", "player_id": "14910",
                    "status": "Questionable",
                    "lineup_role": "starter",
                    "news": [],
                }],
            }],
        }
        old = copy.deepcopy(doc)
        result = enrich_mfl_headlines(
            doc, lambda lid, pid: PAGE,
            datetime(2026, 11, 19, tzinfo=timezone.utc)
        )
        self.assertEqual(result, {"checked": 1, "matched": 1})
        self.assertEqual(doc["leagues"][0]["alerts"][0]["mfl_headline"]["title"],
                         "S Brandon Jones: Still working through hamstring issue")
        self.assertEqual(doc["leagues"][0]["alerts"][0]["status"],
                         old["leagues"][0]["alerts"][0]["status"])
        self.assertEqual(doc["leagues"][0]["alerts"][0]["lineup_role"], "starter")
        self.assertEqual(doc["synced_at"], old["synced_at"])
        self.assertEqual(doc["sent_digest_date"], old["sent_digest_date"])


if __name__ == "__main__":
    unittest.main()
