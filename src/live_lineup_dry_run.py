"""One-shot read-only MFL lineup analysis. Never commits or sends player data.

Owner login and GET-only read APIs are used; there is no MFL import call.
All console output is aggregated status. This is not a scheduled or active
lineup substitution service.
"""
import os
import re
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from .mfl_owner_auth import owner_login, _make_opener, OwnerAuthError
from .mfl import export, MFLAPIError
from .probe_mfl_lineups import _fetch
from .submitted_lineup import extract_submitted_lineup, LineupParseError
from .lineup_replacements import (
    score_map, teams_with_games, propose_out_replacements, LineupRecommendationError,
)


def fetch_authenticated_lineup(year, league, franchise, opener, cookie):
    if not (str(year).isdigit() and str(league).isdigit() and str(franchise).isdigit()):
        raise ValueError("Invalid MFL lineup identifier")
    address = (
        f"https://www46.myfantasyleague.com/{year}/lineup?"
        + urllib.parse.urlencode({"L": league, "FRANCHISE": franchise})
    )
    req = urllib.request.Request(address, headers={
        "User-Agent": "FantasyInjuryWatchBryce/1.0",
        "Cookie": cookie, "Accept": "text/html",
    }, method="GET")
    try:
        with opener.open(req, timeout=30) as response:
            if not re.fullmatch(
                r"www\d+\.myfantasyleague\.com", urlsplit(response.url).hostname or "",
            ):
                raise OwnerAuthError("MFL lineup fetch redirected away from expected host")
            return response.read(1_000_000).decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
        raise OwnerAuthError("MFL lineup HTML unavailable") from None



def read_public_injuries(year, league, client):
    """Public MFL injury export without a league API key; validate before use."""
    params = urllib.parse.urlencode({"TYPE": "injuries", "L": league, "JSON": "1"})
    req = urllib.request.Request(
        f"https://api.myfantasyleague.com/{int(year)}/export?{params}",
        headers={"User-Agent": client, "Accept": "application/json"}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            doc = json.loads(response.read(4_000_000))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        raise LineupRecommendationError("Public injury data is unavailable") from None
    root = doc.get("injuries") if isinstance(doc, dict) else None
    if not isinstance(root, dict) or "injury" not in root:
        raise LineupRecommendationError("Public injury report missing expected records")
    return doc


def run():
    username = os.environ.get("MFL_OWNER_USERNAME", "")
    password = os.environ.get("MFL_OWNER_PASSWORD", "")
    key = os.environ.get("MFL_API_KEY", "")
    league = os.environ.get("MFL_LEAGUE_ID", "")
    franchise = os.environ.get("MFL_FRANCHISE_ID", "")
    year = os.environ.get("MFL_SEASON", "2026")
    week = os.environ.get("MFL_LINEUP_WEEK", "12")
    client = os.environ.get("MFL_CLIENT_NAME") or "FantasyInjuryWatchBryce"
    if not all((username, password, key, league, franchise, year, week)):
        print("LINEUP DRY RUN: credentials or league configuration missing.")
        return
    if not all(x.isdigit() for x in (league, franchise, year, week)):
        print("LINEUP DRY RUN: invalid season, franchise or week configuration.")
        return

    opener = _make_opener()
    try:
        cookie = owner_login(opener, year, username, password, league)
        page = fetch_authenticated_lineup(year, league, franchise, opener, cookie)
        selection = extract_submitted_lineup(page, expected_starters=17)
        print("LINEUP DRY RUN: verified submitted starter count:", len(selection["starters"]))
        print("LINEUP DRY RUN: available player checkbox count:", len(selection["all_selectable"]))
        del page
        cookie = ""
        feeds = {}
        feeds["rosters"] = export(int(year), "rosters", league, key, client)
        time.sleep(2)
        feeds["players"] = export(int(year), "players", league, key, client)
        time.sleep(2)
        # Injury reports are public at MFL. Prefer a fresh public export to
        # avoid transient league-key errors. Missing/invalid data aborts.
        try:
            feeds["injuries"] = read_public_injuries(year, league, client)
            print("LINEUP DRY RUN: public MFL injuries export validated.")
        except LineupRecommendationError:
            feeds["injuries"] = export(int(year), "injuries", league, key, client)
            print("LINEUP DRY RUN: authenticated MFL injuries export validated.")
        averages_doc = _fetch(int(year), league, key, client, "playerScores", "AVG")
        schedule_doc = _fetch(int(year), league, key, client, "nflSchedule", week)
        averages = score_map(averages_doc)
        teams = teams_with_games(schedule_doc)
        result = propose_out_replacements(
            selection["starters"], selection["all_selectable"], feeds,
            averages, teams, franchise,
        )
    except (OwnerAuthError, MFLAPIError, LineupParseError,
            LineupRecommendationError, ValueError) as error:
        # Only allowlisted exception types from our own internal validation.
        print("LINEUP DRY RUN: analysis unavailable; no lineup submission attempted.")
        print("LINEUP DRY RUN: failure_category=", type(error).__name__)
        return
    finally:
        cookie = ""
    print("LINEUP DRY RUN: status=", result["status"])
    print("LINEUP DRY RUN: unavailable_starter_count=", result["out_starters"])
    print("LINEUP DRY RUN: safe_replacement_count=", len(result["changes"]))
    print("LINEUP DRY RUN: unresolved_count=", result["unresolved_count"])
    print("LINEUP DRY RUN: no changes sent; unchanged selections preserved.")


if __name__ == "__main__":
    run()
