"""GitHub Actions entrypoint: MFL read-only sync => encrypted Pages report + optional email."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .crypto import decrypt, encrypt
from .mfl import fetch_all
from .model import parse_report
from .notify import digest_key, email_text, send_resend, urgent_new_alerts

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "site" / "data" / "report.enc.json"


def run():
    key = os.environ.get("MFL_API_KEY", "")
    passphrase = os.environ.get("REPORT_PASSPHRASE", "")
    if not key or not passphrase:
        raise RuntimeError("Required MFL_API_KEY or REPORT_PASSPHRASE secret is not configured")
    if len(passphrase) < 16:
        raise RuntimeError("REPORT_PASSPHRASE must be at least 16 characters")
    league_id = os.environ.get("MFL_LEAGUE_ID", "").strip()
    franchise_id = os.environ.get("MFL_FRANCHISE_ID", "").strip()
    if not league_id.isdigit() or not (len(franchise_id) == 4 and franchise_id.isdigit()):
        raise RuntimeError("MFL_LEAGUE_ID and four-digit MFL_FRANCHISE_ID variables must be configured")
    leagues_config = [{
        "platform": "mfl", "id": league_id,
        "franchise_id": franchise_id,
        "name": os.environ.get("MFL_LEAGUE_NAME", "MFL League"),
        "season": int(os.environ.get("MFL_SEASON", "2026")),
    }]
    previous = {}
    if REPORT_PATH.exists():
        # An incorrect/mismatched password fails rather than erasing the previous state.
        previous = decrypt(json.loads(REPORT_PATH.read_text(encoding="utf-8")), passphrase)
    now = datetime.now(timezone.utc)
    leagues = []
    for league in leagues_config:
        if league["platform"] != "mfl":
            raise RuntimeError("Only MFL read-only integration has been implemented")
        feeds = fetch_all(int(league["season"]), league["id"], key,
                          (os.environ.get("MFL_CLIENT_NAME", "").strip() or "FantasyInjuryWatch"))
        leagues.append(parse_report(feeds, league, now))
    document = {"schema": 1, "synced_at": now.isoformat(), "leagues": leagues,
                "sent_digest_date": previous.get("sent_digest_date", "")}
    # Email first. If delivery fails, the action fails and does not mark the alert as sent.
    email_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("ALERT_FROM", "")
    to_addr = os.environ.get("ALERT_TO", "")
    test_email = os.environ.get("SEND_TEST_EMAIL", "").strip().lower() in {"true", "1", "yes"}
    email_enabled = os.environ.get("EMAIL_ENABLED", "").strip().lower() in {"true", "1", "yes"}
    if test_email:
        if not all((email_key, from_addr, to_addr)):
            raise RuntimeError("Test email requested but RESEND_API_KEY, ALERT_FROM or ALERT_TO is missing")
        count = sum(len(l["alerts"]) for l in leagues)
        send_resend(email_key, from_addr, to_addr,
                    "Fantasy Injury Watch | Test email",
                    "This is a test notification from Fantasy Injury Watch.\n"
                    f"Latest CFFL Dynasty sync: {now.isoformat()}\n"
                    f"Current MFL injury items: {count}\n"
                    "No lineup changes are enabled.\n"
                    "The test does not count as a Thursday or Sunday summary.")
        print("A single email test request was accepted by the provider. Inbox receipt not verified.")
    elif email_enabled:
        if not all((email_key, from_addr, to_addr)):
            raise RuntimeError("EMAIL_ENABLED is set, but email configuration is missing")
        due = digest_key(now)
        if due and due != previous.get("sent_digest_date"):
            if send_resend(email_key, from_addr, to_addr,
                           "Fantasy Injury Watch | Thursday" if now.astimezone(__import__('zoneinfo').ZoneInfo('America/Regina')).weekday() == 3 else "Fantasy Injury Watch | Sunday",
                           email_text(document, "Your fantasy injury summary")):
                document["sent_digest_date"] = due
        else:
            new_urgent = urgent_new_alerts(document, previous)
            if new_urgent:
                names = ", ".join(a["name"] for a in new_urgent[:4])
                send_resend(email_key, from_addr, to_addr,
                            f"Fantasy Injury Watch | New urgent status: {names}",
                            email_text(document, "New urgent injury status"))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(encrypt(document, passphrase), indent=2) + "\n", encoding="utf-8")
    print(f"Read-only MFL sync successful. Leagues: {len(leagues)}. Total injury items: {sum(len(l['alerts']) for l in leagues)}.")
    print("Encrypted site report written. No roster names or credentials were logged.")


if __name__ == "__main__":
    run()
