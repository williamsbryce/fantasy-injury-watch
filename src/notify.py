"""Consolidated Resend email alerts: read-only, deduplicated, no credentials in output."""
import json
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Regina")


def urgent_new_alerts(current, previous):
    old = {a["key"]: a for l in previous.get("leagues", []) for a in l.get("alerts", [])}
    return [a for l in current.get("leagues", []) for a in l.get("alerts", [])
            if a["group"] == "action" and
            (a["key"] not in old or old[a["key"]].get("status") != a["status"])]


def digest_key(now):
    local = now.astimezone(TZ)
    if local.weekday() in (3, 6) and local.hour >= 9:
        return local.strftime("%Y-%m-%d")
    return None


def email_text(document, title):
    lines = [title, "", "Injury statuses from MFL, not verified NFL official inactive lists.",
             f"Last successful sync: {document['synced_at']} UTC", ""]
    total = 0
    for league in document.get("leagues", []):
        lines.append(f"{league['name']} ({league['players_checked']} rostered players checked)")
        alerts = league.get("alerts", [])
        if not alerts:
            lines.append("  No current injuries reported by MFL.")
        for a in alerts:
            total += 1
            label = "ACTION" if a["group"] == "action" else "WATCH"
            detail = f" - {a['details']}" if a["details"] else ""
            lines.append(f"  [{label}] {a['name']} ({a['position']}, {a['nfl_team']}): {a['status']}{detail}")
        lines.append("")
    lines.append(f"{total} reported injury item(s). Report may lag official NFL team updates.")
    return "\n".join(lines)


def send_resend(api_key, from_addr, to_addr, subject, body):
    if not all((api_key, from_addr, to_addr)):
        return False
    payload = json.dumps({"from": from_addr, "to": [to_addr], "subject": subject, "text": body}).encode()
    request = urllib.request.Request("https://api.resend.com/emails", data=payload, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in (200, 201, 202):
                raise RuntimeError("Email provider did not accept the message")
    except urllib.error.HTTPError as exc:
        # Classify the error locally. No response body, URL, credentials, recipient
        # or headers are ever printed into public GitHub Actions logs.
        status = exc.code if isinstance(exc.code, int) else 0
        try:
            raw = exc.read(8192).decode("utf-8", "replace")
        except (OSError, UnicodeError):
            raw = ""
        data = None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            pass
        error = data if isinstance(data, dict) else {}
        if isinstance(error.get("error"), dict):
            error = error["error"]
        name = str(error.get("name") or error.get("code") or "").lower()
        message = str(error.get("message") or "").lower()
        if isinstance(data, dict):
            response_type = "json"
        elif "<html" in raw.lower() or "<!doctype html" in raw.lower():
            response_type = "html"
        elif raw:
            response_type = "text"
        else:
            response_type = "empty"

        # The reason is an allowlisted classification, never a raw provider
        # message, which could contain addresses or request details.
        if "only send testing emails" in message or (
                "testing emails" in message and "own email" in message):
            reason = "test_recipient_restriction"
        elif "domain is not verified" in message or (
                "domain" in message and "not verified" in message):
            reason = "sender_domain_unverified"
        elif "api key is not active" in message:
            reason = "api_key_inactive"
        elif "api key is suspended" in message or name == "suspended_api_key":
            reason = "api_key_suspended"
        elif "missing required scopes" in message or name == "invalid_permission":
            reason = "permission_denied"
        elif "api key is invalid" in message:
            reason = "api_key_invalid"
        elif name in {
            "validation_error", "restricted_api_key", "missing_api_key",
            "invalid_permission", "suspended_api_key", "email_above_quota",
        }:
            reason = name
        else:
            reason = "unclassified"
        raise RuntimeError(
            f"Resend rejected email: HTTP {status}, reason={reason}, response={response_type}. "
            "No sensitive response content logged."
        ) from None
    except (urllib.error.URLError, OSError):
        # Never leak bearer token in exception output.
        raise RuntimeError("Resend connection error; API request did not complete") from None
    return True
