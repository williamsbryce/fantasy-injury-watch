"""Synthetic-only tests for browser-equivalent native MFL lineup submission."""
import unittest
from urllib.parse import parse_qsl
from src.mfl_native_lineup import prepare_post
from src.one_way_native_swap import authorized
from src.manual_lineup_test import ManualSwapError


def sample_html(action="https://www46.myfantasyleague.com/2026/lineup", week="11",
                incoming_name="LB0001", checked_count=17):
    # 17 checked out of 53 selectable controls with the first 17 starters.
    rows = []
    for idx in range(53):
        n = 100 + idx
        name = "LB0001" if idx in (4, 50) else "QB0001"
        if idx == 50:
            name = incoming_name
        checked = " checked" if idx < checked_count else ""
        rows.append(f'<input type="checkbox" name="{name}" value="{n}"{checked}>')
    return f'''<form method="POST" action="{action}">
    <input type="hidden" name="LEAGUE_ID" value="40298">
    <input type="hidden" name="FRANCHISE" value="0001">
    <input type="hidden" name="WEEK" value="{week}">
    <input type="hidden" name="FORM" value="some-private-preserved-token">
    <input type="hidden" name="lineup_expires" value="1760000000">
    {''.join(rows)}
    <select name="PROJSRC"><option value="A" selected>Alpha</option><option value="B">Beta</option></select>
    <textarea name="MESSAGE0001">Existing note</textarea>
    <input type="submit" name="SUBMIT" value="Submit Lineup">
    </form>'''


class NativeFormTests(unittest.TestCase):
    def setUp(self):
        self.original = [str(i) for i in range(100, 117)]
        self.proposal = list(self.original)
        self.proposal[4] = "150"

    def test_native_form_preserves_16_and_hidden_fields(self):
        url, body = prepare_post(
            sample_html(), originals=self.original,
            proposed=self.proposal, outgoing="104", incoming="150")
        self.assertEqual(url, "https://www46.myfantasyleague.com/2026/lineup")
        pairs = parse_qsl(body.decode("utf-8"))
        fields = dict(pairs)
        self.assertEqual(fields["LEAGUE_ID"], "40298")
        self.assertEqual(fields["FRANCHISE"], "0001")
        self.assertEqual(fields["WEEK"], "11")
        self.assertEqual(fields["FORM"], "some-private-preserved-token")
        self.assertEqual(fields["PROJSRC"], "A")
        self.assertEqual(fields["MESSAGE0001"], "Existing note")
        self.assertEqual(fields["SUBMIT"], "Submit Lineup")
        selected = [val for name, val in pairs if name in ("LB0001", "QB0001")]
        self.assertEqual(set(selected), set(self.proposal))
        self.assertEqual(len(selected), 17)
        self.assertNotIn("104", selected)
        self.assertIn("150", selected)

    def test_refuses_wrong_week_or_host(self):
        for html in (
            sample_html(week="12"),
            sample_html(action="https://attacker.example/2026/lineup"),
            sample_html(action="https://www46.myfantasyleague.com/2026/import"),
            sample_html(action="http://www46.myfantasyleague.com/2026/lineup"),
        ):
            with self.subTest(html=html[:100]):
                with self.assertRaises(ManualSwapError):
                    prepare_post(html, originals=self.original,
                                 proposed=self.proposal, outgoing="104", incoming="150")

    def test_refuses_wrong_position_checkbox_name(self):
        with self.assertRaisesRegex(ManualSwapError, "different position"):
            prepare_post(sample_html(incoming_name="RB0001"),
                         originals=self.original, proposed=self.proposal,
                         outgoing="104", incoming="150")

    def test_refuses_changed_saved_starter_count(self):
        with self.assertRaises(ManualSwapError):
            prepare_post(sample_html(checked_count=16),
                         originals=self.original, proposed=self.proposal,
                         outgoing="104", incoming="150")

    def test_one_time_authorization(self):
        env = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "williamsbryce/fantasy-injury-watch",
            "GITHUB_ACTOR": "williamsbryce",
            "NATIVE_LINEUP_APPROVAL": "APPROVED_ONE_WAY_NATIVE_CEDRIC_GRAY_TO_ANTHONY_HILL_W11",
        }
        authorized(env)
        for k, val in (
            ("GITHUB_EVENT_NAME", "workflow_dispatch"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_ACTOR", "someoneelse"),
            ("NATIVE_LINEUP_APPROVAL", "no"),
        ):
            wrong = dict(env)
            wrong[k] = val
            with self.assertRaises(ManualSwapError):
                authorized(wrong)


if __name__ == "__main__":
    unittest.main()
