"""Offline regression tests for extracting real pregame MFL starting IDs."""
import unittest

from src.submitted_lineup import (
    extract_submitted_lineup, report_counts, LineupParseError,
)


def form(inputs, action="/2026/lineup?L=40298&FRANCHISE=0001"):
    return (
        '<html><form method="POST" action="' + action + '">'
        + inputs + '<input type="submit" value="Submit Lineup"></form></html>'
    )


class TestSubmittedLineupParser(unittest.TestCase):
    def test_only_checked_player_values_are_starters(self):
        html = form(
            '<input type="checkbox" name="STARTERS" value="1234" checked>'
            '<input type="checkbox" name="STARTERS" value="0532" checked="">'
            '<input type="checkbox" name="STARTERS" value="7890">'
            '<input type="hidden" name="WEEK" value="12">'
            '<input type="checkbox" name="SHOW_DETAIL" value="on">'
        )
        result = extract_submitted_lineup(html, expected_starters=2)
        self.assertEqual(result["starters"], ["1234", "0532"])
        self.assertEqual(result["all_selectable"], ["1234", "0532", "7890"])
        self.assertEqual(result["form_action_route"], "lineup")
        self.assertEqual(report_counts(result)["starter_count"], 2)
        self.assertNotIn("1234", str(report_counts(result)))
        self.assertEqual(result["unrecognized_checkbox_count"], 1)

    def test_password_or_player_id_not_exposed_in_count_summary(self):
        result = extract_submitted_lineup(form(
            '<input type=checkbox value="12345678" checked name="P">'
        ))
        self.assertNotIn("12345678", str(report_counts(result)))
        self.assertEqual(result["starters"], ["12345678"])

    def test_missing_post_form_fails_closed(self):
        with self.assertRaisesRegex(LineupParseError, "POST form"):
            extract_submitted_lineup('<form><input type="checkbox" value="555" checked></form>')

    def test_blank_lineup_not_reported_as_safe(self):
        with self.assertRaisesRegex(LineupParseError, "No submitted"):
            extract_submitted_lineup(form('<input type="checkbox" value="789">'))

    def test_unrecognized_checked_control_fails_closed(self):
        with self.assertRaisesRegex(LineupParseError, "non-player"):
            extract_submitted_lineup(form(
                '<input type="checkbox" value="123" checked>'
                '<input type="checkbox" value="yes" checked>'
            ))

    def test_duplicate_selected_fails_closed(self):
        with self.assertRaisesRegex(LineupParseError, "Duplicate selectable"):
            extract_submitted_lineup(form(
                '<input type="checkbox" value="123" checked>'
                '<input type="checkbox" value="123" checked>'
            ))

    def test_wrong_starter_count_fails_closed(self):
        with self.assertRaisesRegex(LineupParseError, "Starter count"):
            extract_submitted_lineup(form(
                '<input type="checkbox" value="123" checked>'
            ),expected_starters=17)

    def test_unrecognized_form_action_fails_closed(self):
        with self.assertRaisesRegex(LineupParseError, "unrecognized"):
            extract_submitted_lineup(form(
                '<input type="checkbox" value="123" checked>', action="https://evil.example/change"
            ))

    def test_no_post_to_mfl(self):
        # Parser is pure and cannot send network requests.
        out = extract_submitted_lineup(form('<input type="checkbox" value="123" checked>'))
        self.assertEqual(out["starters"], ["123"])


if __name__ == "__main__":
    unittest.main()
