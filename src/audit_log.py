"""Persist a small, public and privacy-sanitized operational event history.

GitHub Contents API uses optimistic concurrency. Each event is stored only
after the underlying action is observed. A provider-accepted email is NOT
proof of inbox delivery. Never store email addresses, API secrets, private
MFL HTML or cookies in the public history.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = "williamsbryce/fantasy-injury-watch"
PATH = "site/data/events.json"
URL = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
VALID_KINDS = {"email", "lineup", "check", "system"}
VALID_STATUSES = {"success", "attention", "info", "pending"}
MAX_EVENTS = 200


class AuditError(RuntimeError):
    pass


def _event(kind, status, title, detail, key, env, now):
    if kind not in VALID_KINDS or status not in VALID_STATUSES:
        raise AuditError("Invalid audit event classification")
    if not re.fullmatch(r"[a-z0-9_-]{1,48}", str(key)):
        raise AuditError("Invalid audit event key")
    run = str(env.get("GITHUB_RUN_ID") or "")
    if not run.isdigit() or not 1 <= len(run) <= 20:
        raise AuditError("GitHub workflow run ID is missing")
    if env.get("GITHUB_REPOSITORY") != REPO or env.get("GITHUB_REF") != "refs/heads/main":
        raise AuditError("Event logger is restricted to the primary repository branch")
    # Details must be curated status descriptions, never raw remote error text.
    for value, limit in ((title, 110), (detail, 360)):
        if not isinstance(value, str) or len(value) > limit or not value.strip():
            raise AuditError("Invalid event description")
        if "@" in value or "://" in value or "\r" in value or "\n" in value:
            raise AuditError("Event description could expose private content")
    timestamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": f"{run}-{key}", "timestamp": timestamp,
        "kind": kind, "status": status,
        "title": title, "detail": detail,
        "run_url": f"https://github.com/{REPO}/actions/runs/{run}",
    }


def _request(url, token, method="GET", data=None):
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FantasyInjuryWatchAudit/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as result:
        return json.loads(result.read(250_000))


def _read(token):
    try:
        current = _request(URL + "?ref=main", token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None, []
        raise AuditError("Event log read rejected HTTP " + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise AuditError("Event log read network or JSON failure") from None
    try:
        blob = base64.b64decode(current["content"].replace("\n", ""), validate=True)
        history = json.loads(blob.decode("utf-8"))
        if history["schema"] != 1 or not isinstance(history["events"], list):
            raise ValueError("Invalid schema")
        return current["sha"], history["events"]
    except (TypeError, KeyError, ValueError, UnicodeError):
        raise AuditError("Existing public event log is invalid") from None


def _write(token, sha, history, event):
    all_events = {row["id"]: row for row in history if isinstance(row, dict)
                  and isinstance(row.get("id"), str)}
    if event["id"] in all_events:
        return False  # A retried job must not append an email or submission twice.
    all_events[event["id"]] = event
    sorted_events = sorted(all_events.values(), key=lambda row: (
        str(row.get("timestamp") or ""), str(row["id"])), reverse=True)[:MAX_EVENTS]
    output = {
        "schema": 1,
        "updated_at": event["timestamp"],
        "events": sorted_events,
    }
    payload = {
        "message": "Record Injury Watch operational event [skip ci]",
        "content": base64.b64encode(
            (json.dumps(output, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        ).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    _request(URL, token, method="PUT", data=json.dumps(payload).encode("utf-8"))
    return True


def record_event(kind, status, title, detail, *, key, env=None, now=None):
    """Append only an allowlisted, curated event from a GitHub Actions run.

    When no token is supplied, fail rather than pretend the event is saved.
    GitHub conflicts are retried with a fresh read, and duplicate IDs are
    idempotent across reruns of the same run.
    """
    env = os.environ if env is None else env
    token = env.get("AUDIT_GITHUB_TOKEN") or ""
    if not token:
        raise AuditError("Event audit permission missing")
    event = _event(kind, status, title, detail, key, env,
                   now or datetime.now(timezone.utc))
    for attempt in range(5):
        sha, old = _read(token)
        try:
            created = _write(token, sha, old, event)
            return created
        except urllib.error.HTTPError as error:
            if error.code in (409, 422) and attempt < 4:
                time.sleep(1 + attempt)
                continue
            raise AuditError("Event log write rejected HTTP " + str(error.code)) from None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            raise AuditError("Event log write network failure") from None
    raise AuditError("Event log update could not resolve concurrent changes")
