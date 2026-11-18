"""Offline event-history audit tests; never access GitHub or email systems."""
import base64
import json
import unittest
import urllib.error
from unittest.mock import patch
from datetime import datetime, timezone

from src.audit_log import (
    _event, _write, AuditError, record_event, REPO, MAX_EVENTS
)


class AuditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "AUDIT_GITHUB_TOKEN": "mock",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ID": "123456",
        }
        self.now = datetime(2026, 11, 18, 22, 40, tzinfo=timezone.utc)

    def test_event_has_stable_key_and_public_run_link(self):
        event = _event(
            "email", "success", "Email accepted",
            "Provider accepted message; inbox unconfirmed.",
            "summary", self.env, self.now
        )
        self.assertEqual(event["id"], "123456-summary")
        self.assertEqual(event["timestamp"], "2026-11-18T22:40:00+00:00")
        self.assertTrue(event["run_url"].endswith("/actions/runs/123456"))
        self.assertNotIn("mock", str(event))

    def test_rejects_private_addresses_or_remote_error_content(self):
        for detail in ("Mail to user@example.com", "https://private.example",
                       "Secret\rPassword"):
            with self.subTest(detail=detail):
                with self.assertRaises(AuditError):
                    _event("email", "success", "Test", detail, "summary", self.env, self.now)
        with self.assertRaises(AuditError):
            _event("invalid", "success", "Test", "Message", "summary", self.env, self.now)

    def test_write_serializes_only_curated_event(self):
        event = _event("lineup", "success", "Save confirmed", "17 starters confirmed.",
                       "saved", self.env, self.now)
        with patch("src.audit_log._request", return_value={} ) as req:
            created = _write("token", "sha123", [], event)
        self.assertTrue(created)
        args, kwargs = req.call_args
        payload = json.loads(kwargs["data"])
        self.assertEqual(payload["sha"], "sha123")
        rows = json.loads(base64.b64decode(payload["content"]))
        self.assertEqual(rows["schema"], 1)
        self.assertEqual(rows["events"], [event])

    def test_identical_event_id_is_not_duplicated(self):
        event = _event("email", "success", "Email accepted", "Accepted by provider.",
                       "summary", self.env, self.now)
        with patch("src.audit_log._request") as req:
            created = _write("token", "sha123", [event], event)
        self.assertFalse(created)
        req.assert_not_called()

    def test_conflict_retry_reads_fresh_sha(self):
        conflict = urllib.error.HTTPError(
            "https://api.github.com", 409, "Conflict", None, None)
        with patch("src.audit_log._read", side_effect=[("old", []), ("new", [])]) as rd, \
             patch("src.audit_log._write", side_effect=[conflict, True]) as wr, \
             patch("src.audit_log.time.sleep") as sleeper:
            created = record_event(
                "email", "success", "Summary email accepted", "Inbox unverified.",
                key="summary", env=self.env, now=self.now
            )
        self.assertTrue(created)
        self.assertEqual(rd.call_count, 2)
        self.assertEqual(wr.call_count, 2)
        sleeper.assert_called_once()

    def test_missing_token_not_reported_as_saved(self):
        env = dict(self.env)
        del env["AUDIT_GITHUB_TOKEN"]
        with self.assertRaisesRegex(AuditError, "permission"):
            record_event("email", "success", "Email accepted", "Inbox unverified.",
                         key="summary", env=env, now=self.now)


if __name__ == "__main__":
    unittest.main()
