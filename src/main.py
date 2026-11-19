"""GitHub Actions entrypoint: read-only MFL sync => public report + optional email."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .crypto import decrypt
from .mfl import fetch_all
from .news import enrich_reports, fetch_recent_news
from .model import parse_report
from .lineup_monitor import current_week_context, enrich_lineup
from .notify import digest_key, email_text, send_resend, urgent_new_alerts
from .audit_log import record_event, AuditError

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "site" / "data" / "report.json"
LEGACY_PATH = ROOT / "site" / "data" / "report.enc.json"


def log_accepted_email(key, title, detail):
    """Resend accepted a message; inbox delivery is not verified."""
    try:
        record_event("email", "success", title, detail, key=key)
        print("AUDIT: provider-accepted email event saved")
    except AuditError as error:
        # Never turn an accepted email into a second send because audit failed.
        print("AUDIT: email accepted but history update failed:", str(error))


def run():
    key = os.environ.get("MFL_API_KEY", "")
    passphrase = os.environ.get("REPORT_PASSPHRASE", "")
    if not key:
        raise RuntimeError("Required MFL_API_KEY secret is not configured")
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
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    elif LEGACY_PATH.exists():
        # Preserve notification deduplication during the one-time public migration.
        if not passphrase:
            raise RuntimeError("Legacy migration requires existing report passphrase secret")
        previous = decrypt(json.loads(LEGACY_PATH.read_text(encoding="utf-8")), passphrase)
    now = datetime.now(timezone.utc)
    # Optional, read-only context. Missing ESPN/MFL lineup data must not
    # suppress injury monitoring or be interpreted as a valid submission.
    week_context = current_week_context(leagues_config[0]["season"], now)
    leagues = []
    for league in leagues_config:
        if league["platform"] != "mfl":
            raise RuntimeError("Only MFL read-only integration has been implemented")
        feeds = fetch_all(int(league["season"]), league["id"], key,
                          (os.environ.get("MFL_CLIENT_NAME", "").strip() or "FantasyInjuryWatch"))
        result = parse_report(feeds, league, now)
        enrich_lineup(result, feeds, league, week_context, key, now)
        previously = {a.get("key"): a for old in previous.get("leagues", [])
                      if isinstance(old, dict) for a in old.get("alerts", [])
                      if isinstance(a, dict)}
        for alert in result["alerts"]:
            before = previously.get(alert["key"])
            if before is None:
                alert["status_change"] = {"kind": "new"}
            elif str(before.get("status", "")).lower() != str(alert["status"]).lower():
                alert["status_change"] = {"kind": "changed",
                                          "previous": str(before.get("status", ""))[:35]}
        leagues.append(result)
    # News is optional and must never suppress official MFL injury designations.
    enrich_reports(leagues, fetch_recent_news(), checked_at=now)
    document = {"schema": 2, "synced_at": now.isoformat(), "leagues": leagues,
                "sent_digest_date": previous.get("sent_digest_date", ""),
                "sent_lineup_warning_key": previous.get("sent_lineup_warning_key", "")}
    # Email first. If delivery fails, the action fails and does not mark the alert as sent.
    email_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("ALERT_FROM", "")
    to_addr = os.environ.get("ALERT_TO", "")
    test_email = os.environ.get("SEND_TEST_EMAIL", "").strip().lower() in {"true", "1", "yes"}
    email_enabled = os.environ.get("EMAIL_ENABLED", "").strip().lower() in {"true", "1", "yes"}
    lineup_warnings = [
        (league, info) for league in leagues
        for info in [league.get("lineup") or {}] if info.get("warning")
    ]
    lineup_key = ("week-" + str(week_context["week"])) if week_context else ""
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
        log_accepted_email("test-email", "Test email accepted",
                           "Resend accepted the Injury Watch test email. Inbox delivery is not verified.")
    elif email_enabled:
        if not all((email_key, from_addr, to_addr)):
            raise RuntimeError("EMAIL_ENABLED is set, but email configuration is missing")
        due = digest_key(now)
        if due and due != previous.get("sent_digest_date"):
            if send_resend(email_key, from_addr, to_addr,
                           "Fantasy Injury Watch | Thursday" if now.astimezone(__import__('zoneinfo').ZoneInfo('America/Regina')).weekday() == 3 else "Fantasy Injury Watch | Sunday",
                           email_text(document, "Your fantasy injury summary")):
                document["sent_digest_date"] = due
                if lineup_warnings:
                    document["sent_lineup_warning_key"] = lineup_key
                day = now.astimezone(__import__('zoneinfo').ZoneInfo('America/Regina')).weekday()
                log_accepted_email(
                    "scheduled-digest", "Scheduled injury summary accepted",
                    ("Thursday" if day == 3 else "Sunday") +
                    " summary accepted by Resend. Inbox delivery is not verified.")
        else:
            # A single extra warning per NFL week, only when MFL explicitly
            # reports no/incomplete lineup before a relevant kickoff.
            if (lineup_warnings and lineup_key and
                    lineup_key != previous.get("sent_lineup_warning_key")):
                summary = "\n".join(info["warning"] for _, info in lineup_warnings)
                if send_resend(
                        email_key, from_addr, to_addr,
                        "Fantasy Injury Watch | Starting lineup requires attention",
                        summary + "\n\nMFL has not confirmed a complete 17-player lineup. "
                        "Please review your starting lineup before kickoff.\n"
                        f"https://www46.myfantasyleague.com/{leagues_config[0]['season']}/lineup?"
                        f"L={league_id}&FRANCHISE={franchise_id}"):
                    document["sent_lineup_warning_key"] = lineup_key
                    log_accepted_email(
                        "missing-lineup-warning", "Incomplete weekly lineup warning accepted",
                        "Resend accepted a pregame warning that MFL had not confirmed a complete lineup.")
            new_urgent = urgent_new_alerts(document, previous)
            if new_urgent:
                names = ", ".join(a["name"] for a in new_urgent[:4])
                if send_resend(email_key, from_addr, to_addr,
                               f"Fantasy Injury Watch | New urgent status: {names}",
                               email_text(document, "New urgent injury status")):
                    log_accepted_email(
                        "urgent-email", "Urgent injury email accepted",
                        f"Resend accepted an alert for {len(new_urgent)} new urgent injury status(es). Inbox delivery is not verified.")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Read-only MFL sync successful. Leagues: {len(leagues)}. Total injury items: {sum(len(l['alerts']) for l in leagues)}.")
    print("Public injury report written by user request. No API credentials were logged or published.")


if __name__ == "__main__":
    run()
