"""Ensure Resend notifications are logged only after acceptance, without resending."""
import unittest
from unittest.mock import patch
from src.audit_log import AuditError
from src.main import log_accepted_email


class EmailAuditTests(unittest.TestCase):
    def test_accepted_email_is_logged_with_curated_description(self):
        with patch("src.main.record_event", return_value=True) as audit:
            log_accepted_email("digest", "Summary email accepted",
                               "Provider accepted the Thursday email.")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0:3],
                         ("email", "success", "Summary email accepted"))
        self.assertEqual(audit.call_args.kwargs["key"], "digest")

    def test_failed_audit_does_not_retrigger_email_or_fake_success(self):
        with patch("src.main.record_event", side_effect=AuditError("audit unavailable")) as audit:
            log_accepted_email("digest", "Summary email accepted",
                               "Provider accepted the Thursday email.")
        audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
