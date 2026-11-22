"""Consolidated Resend email alerts: read-only, deduplicated, no credentials in output."""
import json
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from .email_design import email_text, email_html, message_html

TZ = ZoneInfo("America/Regina")


def urgent_new_alerts(current, previous):
    old = {a["key"]: a for l in previous.get("leagues", []) for a in l.get("alerts", [])}
    return [a for l in current.get("leagues", []) for a in l.get("alerts", [])
            if a["group"] == "action" and
            (a["key"] not in old or old[a["key"]].get("status") != a["status"])]


def digest_key(now):
    local = now.astimezone(TZ)
    # Saskatchewan stays at UTC-6 year-round. Summaries are due only
    # after their requested local start time; the workflow may run late.
    if ((local.weekday() == 3 and (local.hour, local.minute) >= (17, 0)) or
            (local.weekday() == 6 and (local.hour, local.minute) >= (10, 30))):
        return local.strftime("%Y-%m-%d")
    return None


def send_resend(api_key, from_addr, to_addr, subject, body, html_body=None, idempotency_key=None):
    if not all((api_key, from_addr, to_addr)):
        return False
    message = {"from": from_addr, "to": [to_addr], "subject": subject, "text": body}
    if html_body is not None:
        message["html"] = html_body
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        "User-Agent": "FantasyInjuryWatch/1.0", "Accept": "application/json",
    }
    if idempotency_key is not None:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", idempotency_key):
            raise ValueError("Invalid email idempotency key")
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request("https://api.resend.com/emails", data=payload,
                                     method="POST", headers=headers)
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
        elif name == "restricted_to_address":
            reason = "restricted_to_address"
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
