"""Cached injury reports can gain current lineup roles without injury API calls."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from src.lineup_snapshot import apply_lineup_snapshot

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
STARTERS = ["111"] + [str(n) for n in range(1000, 1016)]
CONTEXT = {"week": 12, "games": []}


def report(age=timedelta(hours=2)):
    return {"schema": 2, "synced_at": (NOW - age).isoformat(),
            "sent_digest_date": "2026-11-15",
            "leagues": [{
                "id": "40298", "franchise_id": "0001",
                "lineup": {"state": "unknown"},
                "alerts": [
                    {"player_id": "111", "name": "Starter Example", "status": "Questionable"},
                    {"player_id": "222", "name": "Bench Example", "status": "Out"},
                ],
            }]}


def selected(ids):
    return {"weeklyResults": {"franchise": {
        "id": "0001", "starters": ",".join(ids)
    }}}


class SnapshotTests(unittest.TestCase):
    def test_complete_lineup_tags_starters_and_bench_and_retains_injuries(self):
        doc = report()
        original = copy.deepcopy(doc)
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, selected(STARTERS), NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "submitted")
        self.assertEqual([a["lineup_role"] for a in doc["leagues"][0]["alerts"]],
                         ["starter", "bench"])
        self.assertEqual([a["status"] for a in doc["leagues"][0]["alerts"]],
                         [a["status"] for a in original["leagues"][0]["alerts"]])
        self.assertEqual(doc["synced_at"], original["synced_at"])
        self.assertEqual(doc["sent_digest_date"], original["sent_digest_date"])

    def test_no_lineup_stays_unknown_if_export_missing(self):
        doc = report()
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, None, NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "unknown")
        self.assertEqual([a["lineup_role"] for a in doc["leagues"][0]["alerts"]],
                         ["unknown", "unknown"])

    def test_unsubmitted_lineup_does_not_invent_bench(self):
        doc = report()
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, selected([]), NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "not_submitted")
        self.assertEqual([a["lineup_role"] for a in doc["leagues"][0]["alerts"]],
                         ["unknown", "unknown"])

    def test_partial_lineup_does_not_guess_bench(self):
        doc = report()
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, selected(["111"]), NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "incomplete")
        self.assertEqual([a["lineup_role"] for a in doc["leagues"][0]["alerts"]],
                         ["unknown", "unknown"])

    def test_old_injury_roster_does_not_mislabel_dropped_players(self):
        doc = report(age=timedelta(days=4))
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, selected(STARTERS), NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "unknown")
        self.assertEqual([a["lineup_role"] for a in doc["leagues"][0]["alerts"]],
                         ["unknown", "unknown"])

    def test_week_missing_does_not_reuse_prior_lineup(self):
        doc = report()
        apply_lineup_snapshot(doc, "40298", "0001", None, selected(STARTERS), NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "unknown")

    def test_wrong_franchise_does_not_classify_players(self):
        doc = report()
        payload = {"weeklyResults": {"franchise": {"id": "0002",
                                                    "starters": ",".join(STARTERS)}}}
        apply_lineup_snapshot(doc, "40298", "0001", CONTEXT, payload, NOW)
        self.assertEqual(doc["leagues"][0]["lineup"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
