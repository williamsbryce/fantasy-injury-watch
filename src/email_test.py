"""Manually triggered email-only test. No MFL API calls or roster data."""
import os
from datetime import datetime, timezone

from .notify import send_resend


def main():
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("ALERT_FROM", "").strip()
    recipient = os.environ.get("ALERT_TO", "").strip()
    missing = [
        name for name, value in [
            ("RESEND_API_KEY", api_key), ("ALERT_FROM", sender), ("ALERT_TO", recipient)
        ] if not value
    ]
    if missing:
        raise RuntimeError("Email test configuration missing: " + ", ".join(missing))

    send_resend(
        api_key, sender, recipient,
        "Fantasy Injury Watch | Email delivery test",
        "Fantasy Injury Watch email delivery test.\n"
        "No fantasy roster information is included.\n"
        "No MFL requests or lineup changes were made.\n"
        f"UTC time: {datetime.now(timezone.utc).isoformat()}\n",
    )
    print("Resend accepted one email. Confirm receipt in the recipient inbox.")


if __name__ == "__main__":
    main()
