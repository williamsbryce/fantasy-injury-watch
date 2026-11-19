"""Read-only lineup status and missing-submission warnings fail closed."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from src.lineup_monitor import (
    submitted_starter_ids, enrich_lineup, current_week_context, EXPECTED_STARTERS,
)
from tests.test_core import FIXTURE, LEAGUE
from src.model import parse_report


def fixture():
    feeds = copy.deepcopy(FIXTURE)
    # First 17 synthetic rostered players support a complete weekly selection.
    our = feeds["rosters"]["rosters"]["franchise"][0]
    players = feeds["players"]["players"]["player"]
    for i in range(1000, 1016):
        pid = str(i)
        our["player"].append({"id": pid, "status": "ROSTER"})
        players.append({"id": pid, "name": "Synthetic " + pid,
                        "position": "WR", "team": "KC"})
    return feeds


def results(starters):
    return {"weeklyResults": {
        "franchise": {"id": "0001", "starters": starters}
    }}


class LineupMonitorTests(unittest.TestCase):
    def test_explicit_current_week_lineup_can_be_classified(self):
        feeds = fixture()
        now = datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)
        context = {"week": 12, "games": []}
        report = parse_report(feeds, LEAGUE, now)
        starter_ids = ["111"] + [str(i) for i in range(1000, 1016)]
        enrich_lineup(report, feeds, LEAGUE, context, "secret", now,
                      fetcher=lambda *args: results(",".join(starter_ids)))
        self.assertEqual(report["lineup"]["state"], "submitted")
        self.assertEqual(report["alerts"][0]["lineup_role"], "starter")
        self.assertEqual(report["lineup"]["starters_count"], EXPECTED_STARTERS)

    def test_unknown_when_export_lacks_franchise_or_returns_invalid_ids(self):
        feeds = fixture()
        context = {"week": 12, "games": []}
        report = parse_report(feeds, LEAGUE)
        enrich_lineup(report, feeds, LEAGUE, context, "secret",
                      fetcher=lambda *args: {"weeklyResults": {"franchise": {"id": "0022"}}})
        self.assertEqual(report["lineup"]["state"], "unknown")
        self.assertEqual(report["alerts"][0]["lineup_role"], "unknown")
        self.assertIsNone(submitted_starter_ids(results("222,111"), "0001")
                          if False else submitted_starter_ids(
                              {"weeklyResults": {"franchise": {"id": "9999"}}}, "0001"))
        self.assertIsNone(submitted_starter_ids(results("111,111"), "0001"))

    def test_empty_lineup_warns_only_near_relevant_thursday_kickoff(self):
        feeds = fixture()
        now = datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)  # 3 PM SK
        context = {"week": 12, "games": [
            {"kickoff": now + timedelta(hours=2), "teams": ["KC", "BUF"]}
        ]}
        report = parse_report(feeds, LEAGUE, now)
        enrich_lineup(report, feeds, LEAGUE, context, "secret", now,
                      fetcher=lambda *args: results(""))
        self.assertEqual(report["lineup"]["state"], "not_submitted")
        self.assertIn("no submitted", report["lineup"]["warning"])

        other = parse_report(feeds, LEAGUE, now)
        irrelevant = {"week": 12, "games": [
            {"kickoff": now + timedelta(hours=2), "teams": ["ARI", "ATL"]}
        ]}
        enrich_lineup(other, feeds, LEAGUE, irrelevant, "secret", now,
                      fetcher=lambda *args: results(""))
        self.assertIsNone(other["lineup"]["warning"])

    def test_failed_lineup_export_does_not_remove_injury_alert(self):
        feeds = fixture()
        report = parse_report(feeds, LEAGUE)
        enrich_lineup(report, feeds, LEAGUE, {"week": 12, "games": []}, "secret",
                      fetcher=lambda *args: None)
        self.assertEqual(report["lineup"]["state"], "unknown")
        self.assertEqual(len(report["alerts"]), 1)


if __name__ == "__main__":
    unittest.main()
