"""MFL export API, read only. Never log full request URLs (they can contain APIKEY)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class MFLAPIError(RuntimeError):
    pass


def export(year: int, kind: str, league_id: str, api_key: str, client_name: str = "FantasyInjuryWatch") -> dict:
    if kind not in {"rosters", "players", "injuries"}:
        raise ValueError("Unsupported read-only MFL export type")
    params = {"TYPE": kind, "L": league_id, "JSON": "1", "APIKEY": api_key}
    url = f"https://api.myfantasyleague.com/{year}/export?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={
        "User-Agent": client_name,
        "Accept": "application/json",
    }, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if response.status != 200:
                raise MFLAPIError(f"MFL {kind} returned HTTP {response.status}")
            payload = json.loads(response.read(8_000_000))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # urllib exceptions can contain the full URL and therefore the API key.
        raise MFLAPIError(f"MFL {kind} request failed; check API access and network") from None
    if not isinstance(payload, dict):
        raise MFLAPIError(f"MFL {kind} response is not a JSON object")
    if "error" in payload:
        raise MFLAPIError(f"MFL {kind} API reported an error (credentials or privileges may be invalid)")
    if kind not in payload:
        raise MFLAPIError(f"MFL {kind} response missing required '{kind}' section")
    return payload


def fetch_all(year: int, league_id: str, api_key: str, client_name: str) -> dict:
    data = {}
    for index, kind in enumerate(("rosters", "players", "injuries")):
        if index:
            time.sleep(1.1)  # Reasonable pacing; respect MFL usage limits.
        data[kind] = export(year, kind, league_id, api_key, client_name)
    return data
