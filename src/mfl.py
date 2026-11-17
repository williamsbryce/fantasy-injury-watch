"""MFL read-only export client with bounded retries. Never log API keys or URLs."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class MFLAPIError(RuntimeError):
    pass


RETRIABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay(attempt):
    # A few retries for temporary throttling/availability, not endless polling.
    return (10, 30)[attempt - 1]


def _error_message(payload):
    error = payload.get("error", "")
    if isinstance(error, dict):
        return str(error.get("$t", error.get("message", ""))).lower()
    return str(error).lower()


def _error_category(message):
    """Return a safe category without copying potentially sensitive API text."""
    value = str(message or "").lower()
    if any(x in value for x in (
        "requires logged in", "invalid api", "invalid key", "invalid cookie",
        "not authorized", "access denied", "permission denied",
        "commissioner access", "unauthorized")):
        return "authorization"
    if any(x in value for x in (
        "too many", "rate limit", "throttl", "exceeded", "max requests",
        "request limit", "limit reached")):
        return "rate_limit"
    if any(x in value for x in ("temporarily unavailable", "try again", "server error")):
        return "temporary"
    return "unclassified"


def export(year: int, kind: str, league_id: str, api_key: str,
           client_name: str = "FantasyInjuryWatch") -> dict:
    if kind not in {"rosters", "players", "injuries"}:
        raise ValueError("Unsupported read-only MFL export type")
    params = {"TYPE": kind, "L": league_id, "JSON": "1", "APIKEY": api_key}
    url = f"https://api.myfantasyleague.com/{year}/export?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={
        "User-Agent": client_name,
        "Accept": "application/json",
    }, method="GET")
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read(8_000_000))
        except urllib.error.HTTPError as exc:
            if exc.code in RETRIABLE_HTTP and attempt < 3:
                print(f"MFL {kind}: temporary HTTP {exc.code}; retry {attempt}/2")
                time.sleep(_retry_delay(attempt))
                continue
            raise MFLAPIError(f"MFL {kind} failed with HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            # The original exception may contain the full URL with the secret.
            if attempt < 3:
                print(f"MFL {kind}: temporary connection/response problem; retry {attempt}/2")
                time.sleep(_retry_delay(attempt))
                continue
            raise MFLAPIError(f"MFL {kind} failed after 3 network/response attempts") from None
        if not isinstance(payload, dict):
            raise MFLAPIError(f"MFL {kind} returned a non-object response")
        if "error" in payload:
            message = _error_message(payload)
            category = _error_category(message)
            if category == "authorization":
                raise MFLAPIError(f"MFL {kind} access denied; verify the existing secret and league permissions")
            if attempt < 3:
                print(f"MFL {kind}: API error category={category}; retry {attempt}/2")
                time.sleep(_retry_delay(attempt))
                continue
            raise MFLAPIError(f"MFL {kind} API error category={category} persisted after 3 attempts")
        if kind not in payload:
            raise MFLAPIError(f"MFL {kind} response missing '{kind}' section; refusing all-clear")
        return payload
    raise MFLAPIError(f"MFL {kind} feed unavailable")


def fetch_all(year: int, league_id: str, api_key: str, client_name: str) -> dict:
    data = {}
    for index, kind in enumerate(("rosters", "players", "injuries")):
        if index:
            time.sleep(2)  # Avoid requests in a tight burst.
        data[kind] = export(year, kind, league_id, api_key, client_name)
    return data
