"""Reliable scheduled email delivery without depending on live MFL fetch."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from src import digest_delivery as d

SUNDAY = datetime(2026, 11, 22, 18, 45, tzinfo=timezone.utc)  # 12:45 PM SK
DOC = {
    "schema": 2, "synced_at": "2026-11-22T11:33:51+00:00",
    "sent_digest_date": "2026-11-19",
    "leagues": [{
        "name": "CFFL Dynasty", "players_checked": 53,
        "lineup": {"state": "submitted"},
        "alerts": [{
            "name": "Example Player", "position": "RB", "nfl_team": "KC",
            "lineup_role": "starter", "status": "Questionable",
            "details": "Knee", "group": "watch"
        }],
    }],
}
ENV = {
    "EMAIL_ENABLED": "true", "RESEND_API_KEY": "fake-test-secret",
    "ALERT_FROM": "sender@example.com", "ALERT_TO": "recipient@example.com",
    "GITHUB_RUN_ID": "123456789",
}


class DigestWindowTests(unittest.TestCase):
    def test_no_send_early_sunday(self):
        self.assertIsNone(d.digest_window(datetime(2026, 11, 22, 16, 29, tzinfo=timezone.utc)))
        self.assertEqual(d.digest_window(datetime(2026, 11, 22, 16, 30, tzinfo=timezone.utc)),
                         ("2026-11-22", "Sunday"))

    def test_sunday_delayed_and_monday_recovery(self):
        self.assertEqual(d.digest_window(SUNDAY), ("2026-11-22", "Sunday"))
        self.assertEqual(d.digest_window(datetime(2026, 11, 23, 23, 59, tzinfo=timezone.utc)),
                         ("2026-11-22", "Sunday"))
        self.assertIsNone(d.digest_window(datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)))

    def test_thursday_and_friday_recovery(self):
        self.assertIsNone(d.digest_window(datetime(2026, 11, 19, 22, 59, tzinfo=timezone.utc)))
        self.assertEqual(d.digest_window(datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc)),
                         ("2026-11-19", "Thursday"))
        self.assertEqual(d.digest_window(datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)),
                         ("2026-11-19", "Thursday"))


class DigestDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.report = self.root / "report.json"
        self.state = self.root / "state.json"
        self.report.write_text(json.dumps(DOC), encoding="utf-8")
        self.paths = patch.multiple(d, REPORT_PATH=self.report, STATE_PATH=self.state)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.environment = patch.dict("os.environ", ENV)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_prepare_persists_static_message_and_sends_once(self):
        self.assertTrue(d.prepare(SUNDAY))
        state = json.loads(self.state.read_text())
        self.assertEqual(state["pending"]["date"], "2026-11-22")
        self.assertIn("Example Player", state["pending"]["html"])
        # Injury sync is older than 6h: warning appears, not false reassurance.
        self.assertIn("Injury data may be out of date", state["pending"]["html"])
        stable_text = state["pending"]["text"]
        self.report.write_text(json.dumps({**DOC, "synced_at": "2026-11-22T18:40:00Z"}))
        self.assertTrue(d.prepare(SUNDAY))
        self.assertEqual(json.loads(self.state.read_text())["pending"]["text"], stable_text)
        with patch.object(d, "send_resend", return_value=True) as sender:
            self.assertTrue(d.send(SUNDAY))
            self.assertFalse(d.send(SUNDAY))
        sender.assert_called_once()
        self.assertEqual(sender.call_args.kwargs["idempotency_key"], "baw-digest-2026-11-22")
        after = json.loads(self.state.read_text())
        self.assertIn("2026-11-22", after["sent_dates"])
        self.assertIsNone(after["pending"])
        self.assertEqual(after["last_accepted"]["run_id"], ENV["GITHUB_RUN_ID"])

    def test_retry_after_send_failure_uses_same_payload(self):
        d.prepare(SUNDAY)
        before = json.loads(self.state.read_text())["pending"]
        with patch.object(d, "send_resend", side_effect=RuntimeError("Provider unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Provider unavailable"):
                d.send(SUNDAY)
        after = json.loads(self.state.read_text())
        self.assertEqual(before, after["pending"])
        self.assertEqual(after["sent_dates"], [])
        with patch.object(d, "send_resend", return_value=True) as sender:
            self.assertTrue(d.send(SUNDAY))
        self.assertEqual(sender.call_args.args[4], before["text"])

    def test_prior_legacy_summary_suppresses_duplicate(self):
        self.report.write_text(json.dumps({**DOC, "sent_digest_date": "2026-11-22"}))
        self.assertFalse(d.prepare(SUNDAY))
        self.assertFalse(self.state.exists())

    def test_missing_report_never_sends_all_clear(self):
        self.report.unlink()
        with self.assertRaises(FileNotFoundError):
            d.prepare(SUNDAY)

    def test_empty_alerts_still_delivers_a_valid_report(self):
        report = {**DOC, "leagues": [{**DOC["leagues"][0], "alerts": []}]}
        self.report.write_text(json.dumps(report))
        self.assertTrue(d.prepare(SUNDAY))
        self.assertIn("No active injury designations", self.state.read_text())

    def test_wrong_schedule_does_not_send(self):
        before = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
        with patch.object(d, "send_resend") as sender:
            self.assertFalse(d.prepare(before))
            self.assertFalse(d.send(before))
        sender.assert_not_called()

    def test_disabled_email_fails_explicitly_when_due(self):
        with patch.dict("os.environ", {"EMAIL_ENABLED": "false"}):
            with self.assertRaisesRegex(RuntimeError, "EMAIL_ENABLED"):
                d.prepare(SUNDAY)


if __name__ == "__main__":
    unittest.main()
