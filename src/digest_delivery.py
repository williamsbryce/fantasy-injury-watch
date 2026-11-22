"""Independent, restartable Thursday/Sunday injury digest delivery.

The digest uses the last VERIFIED MFL report, never a guessed healthy roster.
Two-stage durable preparation saves the identical email body before calling
Resend with a stable idempotency key. This job never changes an MFL lineup.

Usage in GitHub Actions:
  python -m src.digest_delivery prepare
  git commit/push site/data/digest-delivery.json
  python -m src.digest_delivery send
  git commit/push site/data/digest-delivery.json
  python -m src.digest_delivery audit
"""
import copy
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .email_design import email_html, email_text
from .notify import send_resend
from .audit_log import record_event, AuditError

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "site/data/report.json"
STATE_PATH = ROOT / "site/data/digest-delivery.json"
TZ = ZoneInfo("America/Regina")


def digest_window(now):
    """Return the nominal summary date and label, with next-day recovery.

    A missed GitHub 10:30 Sunday cron does not cancel the Sunday delivery.
    Before the due time, the job never sends early.
    """
    local = now.astimezone(TZ)
    day = local.weekday()  # Thursday=3, Sunday=6
    clock = local.time()
    if day == 3 and clock >= time(17, 0):
        return local.date().isoformat(), "Thursday"
    if day == 4 and clock <= time(18, 0):
        return (local.date() - timedelta(days=1)).isoformat(), "Thursday"
    if day == 6 and clock >= time(10, 30):
        return local.date().isoformat(), "Sunday"
    if day == 0 and clock <= time(18, 0):
        return (local.date() - timedelta(days=1)).isoformat(), "Sunday"
    return None


def _state():
    if not STATE_PATH.exists():
        return {"schema": 1, "sent_dates": [], "pending": None}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state.get("schema") != 1 or not isinstance(state.get("sent_dates"), list):
        raise RuntimeError("Digest delivery ledger invalid")
    if state.get("pending") is not None and not isinstance(state["pending"], dict):
        raise RuntimeError("Digest prepared snapshot invalid")
    return state


def _save(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _verified_report():
    doc = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("leagues"), list) or not doc["leagues"]:
        raise RuntimeError("Missing verified MFL injury report: do not send an all-clear")
    parsed = datetime.fromisoformat(str(doc.get("synced_at", "")).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeError("Verified report sync time missing timezone")
    for league in doc["leagues"]:
        if not isinstance(league.get("alerts"), list) or not isinstance(league.get("players_checked"), int):
            raise RuntimeError("Verified MFL report missing roster/alerts")
    return doc, parsed.astimezone(timezone.utc)


def _configured():
    if os.environ.get("EMAIL_ENABLED", "").lower() not in ("true", "yes", "1"):
        raise RuntimeError("Scheduled digest cannot run because EMAIL_ENABLED is not true")
    if not all(os.environ.get(x) for x in ("RESEND_API_KEY", "ALERT_FROM", "ALERT_TO")):
        raise RuntimeError("Scheduled digest email credentials/configuration are missing")


def prepare(now=None):
    now = now or datetime.now(timezone.utc)
    due = digest_window(now)
    if not due:
        print("DIGEST: outside Thursday/Sunday delivery and recovery windows; no email due")
        return False
    _configured()
    date, label = due
    state = _state()
    doc, synced_at = _verified_report()
    # Recognize legacy digests sent before the dedicated workflow was installed.
    if date in state["sent_dates"] or doc.get("sent_digest_date") == date:
        print("DIGEST: scheduled date already accepted by provider; no duplicate")
        return False
    pending = state.get("pending")
    if pending and pending.get("date") == date:
        print("DIGEST: existing prepared email snapshot will be retried unchanged")
        return True
    if pending and pending.get("date") != date:
        raise RuntimeError("Previous digest has an unresolved prepared email; review before proceeding")
    title = label + " injury summary"
    age = now - synced_at
    if age < timedelta(0):
        raise RuntimeError("Verified MFL report has a future timestamp")
    snapshot = copy.deepcopy(doc)
    if age > timedelta(hours=6):
        local_sync = synced_at.astimezone(TZ)
        snapshot["delivery_warning"] = (
            "Last verified refresh: "
            + local_sync.strftime("%b %d at %I:%M %p")
            + " Saskatchewan time. Review the dashboard before relying on these statuses."
        )
    state["pending"] = {
        "date": date, "label": label,
        "subject": "BAWs Fantasy Injury Watch",
        "text": email_text(snapshot, title),
        "html": email_html(snapshot, title),
        "prepared_at": now.astimezone(timezone.utc).isoformat(),
    }
    _save(state)
    print("DIGEST: prepared and saved", label, date,
          "from last verified injury report; no email has been sent yet")
    return True


def send(now=None):
    now = now or datetime.now(timezone.utc)
    due = digest_window(now)
    if not due:
        print("DIGEST: outside recovery window; no email sent")
        return False
    _configured()
    date, label = due
    state = _state()
    if date in state["sent_dates"]:
        print("DIGEST: already accepted; no duplicate")
        return False
    pending = state.get("pending")
    if not pending or pending.get("date") != date:
        # This happens when the nominal scheduled email was sent by legacy code.
        doc, _ = _verified_report()
        if doc.get("sent_digest_date") == date:
            print("DIGEST: legacy delivery already accepted; no duplicate")
            return False
        raise RuntimeError("Digest is due but has no durable prepared snapshot")
    # The prepared payload is kept constant across runs, so Resend's 24-hour
    # idempotency replay cannot reject a different email body on retry.
    key = "baw-digest-" + date
    accepted = send_resend(
        os.environ["RESEND_API_KEY"], os.environ["ALERT_FROM"],
        os.environ["ALERT_TO"], pending["subject"], pending["text"],
        html_body=pending["html"], idempotency_key=key,
    )
    if not accepted:
        raise RuntimeError("Digest was not accepted by the email provider")
    state["sent_dates"] = (state["sent_dates"] + [date])[-40:]
    state["last_accepted"] = {"date": date, "label": label,
                              "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                              "at": now.astimezone(timezone.utc).isoformat()}
    state["pending"] = None
    _save(state)
    print("DIGEST: Resend accepted", label, date,
          "; state saved for commit, actual inbox delivery not verified")
    return True


def audit(now=None):
    due = digest_window(now or datetime.now(timezone.utc))
    if not due:
        return
    state = _state()
    date, label = due
    last = state.get("last_accepted") or {}
    if (last.get("date") != date or
            not os.environ.get("GITHUB_RUN_ID") or
            last.get("run_id") != os.environ.get("GITHUB_RUN_ID")):
        return
    try:
        record_event(
            "email", "success", "Scheduled injury summary accepted",
            label + " injury summary accepted by Resend; inbox delivery not verified.",
            key="digest-" + date.replace("-", ""),
        )
        print("DIGEST: accepted-email event logged")
    except AuditError as error:
        # The delivered email must not be resent because logging failed.
        print("DIGEST: email accepted; event logging unavailable:", str(error))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("prepare", "send", "audit"):
        raise SystemExit("Usage: python -m src.digest_delivery prepare|send|audit")
    {"prepare": prepare, "send": send, "audit": audit}[sys.argv[1]]()


if __name__ == "__main__":
    main()
