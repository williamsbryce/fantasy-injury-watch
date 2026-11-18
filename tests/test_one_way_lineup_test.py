"""No-network safeguards for user-authorized one-way MFL lineup update."""
import unittest
from src.one_way_lineup_test import verify_environment, check_readback, APPROVAL
from src.manual_lineup_test import ManualSwapError


class OneWayLineupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "williamsbryce/fantasy-injury-watch",
            "GITHUB_ACTOR": "williamsbryce",
            "ONE_WAY_LINEUP_APPROVAL": APPROVAL,
        }
        self.original = [str(i) for i in range(100, 117)]
        self.proposal = self.original[:]
        self.proposal[5] = "999"

    def test_approved_one_way_run_is_allowed(self):
        verify_environment(self.env)

    def test_second_attempt_or_other_trigger_rejected(self):
        cases = [
            ("GITHUB_EVENT_NAME", "schedule"),
            ("GITHUB_EVENT_NAME", "workflow_dispatch"),
            ("GITHUB_REF", "refs/heads/feature/out-starter-guard"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_REPOSITORY", "other/repo"),
            ("GITHUB_ACTOR", "other"),
            ("ONE_WAY_LINEUP_APPROVAL", ""),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                env = dict(self.env)
                env[key] = value
                with self.assertRaises(ManualSwapError):
                    verify_environment(env)

    def test_one_way_readback_preserves_all_other_16(self):
        self.assertEqual(check_readback(self.proposal, self.original, self.proposal),
                         "APPLIED")
        self.assertEqual(check_readback(self.original, self.original, self.proposal),
                         "UNCHANGED")
        corrupt = self.proposal[:]
        corrupt[7] = "998"
        self.assertEqual(check_readback(corrupt, self.original, self.proposal),
                         "UNEXPECTED")
        self.assertEqual(check_readback(self.proposal[:-1], self.original, self.proposal),
                         "UNEXPECTED")


if __name__ == "__main__":
    unittest.main()
