"""Pure safety tests for proposed, never-submitted MFL lineups."""
import copy
import unittest
from decimal import Decimal

from src.lineup_replacements import (
    propose_out_replacements, score_map, teams_with_games, LineupRecommendationError,
)


def feeds():
    return {
        "rosters": {"rosters": {"franchise": [{"id": "0001", "player": [
            {"id": "101", "status": "ROSTER"},
            {"id": "201", "status": "ROSTER"},
            {"id": "202", "status": "ROSTER"},
            {"id": "203", "status": "ROSTER"},
            {"id": "204", "status": "ROSTER"},
            {"id": "205", "status": "INJURED_RESERVE"},
            {"id": "301", "status": "ROSTER"},
        ]}]}},
        "players": {"players": {"player": [
            {"id": "101", "name": "Smith, Starter", "position": "WR", "team": "ARI"},
            {"id": "201", "name": "A, Highest", "position": "WR", "team": "DAL"},
            {"id": "202", "name": "B, Bye", "position": "WR", "team": "NYJ"},
            {"id": "203", "name": "C, Injured", "position": "WR", "team": "BUF"},
            {"id": "204", "name": "D, Healthy", "position": "WR", "team": "BUF"},
            {"id": "205", "name": "E, IR", "position": "WR", "team": "BUF"},
            {"id": "301", "name": "Run, RB", "position": "RB", "team": "BUF"},
        ]}},
        "injuries": {"injuries": {"injury": [
            {"id": "101", "status": "Out"},
            {"id": "203", "status": "Questionable"},
        ]}},
    }


class TestReplacementPlanner(unittest.TestCase):
    def test_one_out_starter_replaced_and_other_preserved(self):
        result = propose_out_replacements(
            ["101", "301"], ["101", "201", "202", "203", "204", "301"],
            feeds(), {"201": Decimal("18.2"), "202": Decimal("29.7"),
                      "203": Decimal("23.1"), "204": Decimal("12.1")},
            {"ARI", "DAL", "BUF"}, "0001")
        self.assertEqual(result["status"], "recommendation_ready")
        self.assertEqual(result["proposed_lineup"], ["201", "301"])
        self.assertEqual(result["changes"][0]["league_ppg_average"], "18.2")

    def test_candidate_not_selectable_is_excluded(self):
        result = propose_out_replacements(
            ["101", "301"], ["101", "204", "301"], feeds(),
            {"201": Decimal("18.2"), "204": Decimal("12.1")},
            {"ARI", "DAL", "BUF"}, "0001")
        self.assertEqual(result["proposed_lineup"], ["204", "301"])

    def test_no_candidate_no_partial_lineup(self):
        result = propose_out_replacements(
            ["101", "301"], ["101", "301"], feeds(),
            {"201": Decimal("18.2")}, {"ARI", "DAL", "BUF"}, "0001")
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(result["proposed_lineup"])

    def test_not_out_does_not_change_healthy_starter(self):
        d = feeds()
        d["injuries"]["injuries"]["injury"] = [{"id": "101", "status": "Questionable"}]
        result = propose_out_replacements(
            ["101", "301"], ["101", "201", "301"], d,
            {"201": Decimal("18.2")}, {"ARI", "DAL", "BUF"}, "0001")
        self.assertEqual(result["status"], "no_out_starters")
        self.assertEqual(result["proposed_lineup"], ["101", "301"])

    def test_roster_mismatch_fails_closed(self):
        with self.assertRaises(LineupRecommendationError):
            propose_out_replacements(
                ["999"], ["999"], feeds(), {}, {"ARI", "DAL"}, "0001")

    def test_schedule_unavailable_fails_closed(self):
        with self.assertRaises(LineupRecommendationError):
            propose_out_replacements(
                ["101"], ["101"], feeds(), {}, set(), "0001")

    def test_average_export_sorted_by_actual_scoring_average(self):
        avg = score_map({"playerScores":{"playerScore":[
            {"id":"201","score":"18.20"},
            {"id":"204","score":"12.10"},
            {"id":"202","score":"NaN"},
        ]}})
        self.assertEqual(avg["201"], Decimal("18.20"))
        self.assertNotIn("202", avg)

    def test_schedule_only_active_teams(self):
        teams = teams_with_games({"nflSchedule":{"game":[
            {"team":[{"id": "ARI"}, {"id": "DAL"}]},
            {"team":[{"id": "BUF"},{"id": "MIA"}]},
            {"team":[{"id": "NYG"},{"id": "WAS"}]},
            {"team":[{"id": "PHI"},{"id": "SEA"}]},
        ]}})
        self.assertEqual(len(teams), 8)
        self.assertNotIn("NYJ", teams)


if __name__ == "__main__":
    unittest.main()
