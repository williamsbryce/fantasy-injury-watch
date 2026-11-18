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

from .nfl_week import fetch_espn_week, eligible_teams, NFLScheduleError
from .mfl_owner_auth import owner_login, _make_opener, OwnerAuthError, SafeFormShape
from .mfl import export, MFLAPIError
from .probe_mfl_lineups import _fetch
from .submitted_lineup import extract_submitted_lineup, LineupParseError
from .lineup_replacements import (
    score_map, teams_with_games, propose_out_replacements, LineupRecommendationError,
)


def fetch_authenticated_lineup(year, league, franchise, opener, cookie, week=None, week_param=None):
    if not (str(year).isdigit() and str(league).isdigit() and str(franchise).isdigit()):
        raise ValueError("Invalid MFL lineup identifier")
    params = {"L": league, "FRANCHISE": franchise}
    if week_param in ("WEEK", "W"):
        params[week_param] = str(week)
    address = (
        f"https://www46.myfantasyleague.com/{year}/lineup?"
        + urllib.parse.urlencode(params)
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



def read_public_schedule(year, league, week, client):
    """NFL schedule is public; bypass intermittent league-key export failures."""
    params = urllib.parse.urlencode({
        "TYPE": "nflSchedule", "L": league, "W": week, "JSON": "1",
    })
    req = urllib.request.Request(
        f"https://api.myfantasyleague.com/{int(year)}/export?{params}",
        headers={"User-Agent": client, "Accept": "application/json"}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            doc = json.loads(response.read(4_000_000))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        raise LineupRecommendationError("Public NFL schedule data is unavailable") from None
    root = doc.get("nflSchedule") if isinstance(doc, dict) else None
    if not isinstance(root, dict) or "game" not in root:
        raise LineupRecommendationError("Public NFL schedule has no expected games")
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
        selection = None
        for parameter in (None, "WEEK", "W"):
            page = fetch_authenticated_lineup(
                year, league, franchise, opener, cookie, week=week, week_param=parameter,
            )
            basic = SafeFormShape()
            basic.feed(page)
            print("LINEUP DRY RUN: variant=", parameter or "none",
                  "hidden_weeks=", basic.safe_hidden_weeks,
                  "checked_inputs=", basic.inputs_checked,
                  "selected_options=", basic.options_selected,
                  "form_count=", basic.form_count)
            try:
                possible = extract_submitted_lineup(page, expected_starters=17)
            except LineupParseError:
                continue
            print("LINEUP DRY RUN: page variant=", parameter or "none",
                  "form_week_values=", possible["form_week_values"],
                  "starter_count=", len(possible["starters"]))
            if possible["form_week_values"] == [int(week)]:
                selection = possible
                print("LINEUP DRY RUN: requested week matched saved selections.")
                break
        if selection is None:
            raise LineupParseError("No page variant identified the requested NFL week")
        print("LINEUP DRY RUN: verified submitted starter count:", len(selection["starters"]))
        print("LINEUP DRY RUN: available player checkbox count:", len(selection["all_selectable"]))
        print("LINEUP DRY RUN: form week fields:", selection["form_week_values"])
        print("LINEUP DRY RUN: hidden field categories:", selection["hidden_field_categories"])
        # One signed-in session, both owner-targeted and default views.
        # Compare only safe aggregate metadata. This avoids parallel logins.
        from .diagnose_owner_franchise import read_default, inspect_page
        try:
            owner_default = read_default(opener, cookie)
            meta, owner_ids = inspect_page(owner_default, "default_owner")
            print("LINEUP OWNER DEFAULT:", meta)
            print("LINEUP OWNER DEFAULT: matches_explicit_0001=",
                  bool(owner_ids and set(owner_ids) == set(selection["starters"])))
        except (OwnerAuthError, urllib.error.HTTPError, urllib.error.URLError,
                OSError, TimeoutError, ValueError):
            print("LINEUP OWNER DEFAULT: unavailable; ownership unverified")
        del page
        cookie = ""
        feeds = {}
        feeds["rosters"] = export(int(year), "rosters", league, key, client)
        time.sleep(2)
        feeds["players"] = export(int(year), "players", league, key, client)
        # Owners can compare the authenticated submitted lineup to MFL's
        # displayed starters without confusing this with the full roster.
        from .model import as_list, friendly_name
        player_root = feeds["players"].get("players", {})
        known = {str(p.get("id")): p for p in as_list(player_root.get("player"))
                 if isinstance(p, dict) and p.get("id") is not None}
        if any(pid not in known for pid in selection["starters"]):
            raise LineupParseError("Submitted starter IDs could not be resolved")
        print("WEEK " + str(week) + " VERIFIED STARTERS (no lineup write):")
        for p_id in selection["starters"]:
            p = known[p_id]
            print("  " + friendly_name(p.get("name")) + " | "
                  + str(p.get("position") or "") + " | " + str(p.get("team") or ""))
        # One-off engineering probe: expose selectable bench identities so that
        # a reversible test can target an actual same-position replacement.
        roster_root = feeds["rosters"].get("rosters", {})
        franchise_row = next((f for f in as_list(roster_root.get("franchise"))
                              if str(f.get("id") or "").zfill(4) == franchise.zfill(4)), None)
        if franchise_row is None:
            raise LineupParseError("Franchise roster not found")
        active = {str(p["id"]): p for p in as_list(franchise_row.get("player"))
                  if isinstance(p, dict) and p.get("id") is not None and
                  str(p.get("status") or "").upper().replace(" ", "_") not in
                  {"IR", "INJURED_RESERVE", "TAXI", "TAXI_SQUAD"}}
        bench = sorted(set(selection["all_selectable"]) - set(selection["starters"]))
        print("WEEK " + str(week) + " AVAILABLE BENCH (read only):")
        for p_id in bench:
            if p_id not in known or p_id not in active:
                continue
            p = known[p_id]
            print("  " + str(p_id) + " | " + friendly_name(p.get("name")) + " | "
                  + str(p.get("position") or "") + " | " + str(p.get("team") or ""))
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
        averages = score_map(averages_doc)
        nfl_schedule = fetch_espn_week(int(year), int(week))
        teams = eligible_teams(nfl_schedule)
        print("LINEUP DRY RUN: independent NFL schedule has", len(nfl_schedule) // 2, "games.")
        print("LINEUP DRY RUN: teams still eligible before kickoff:", len(teams))
        result = propose_out_replacements(
            selection["starters"], selection["all_selectable"], feeds,
            averages, teams, franchise,
        )
    except (OwnerAuthError, MFLAPIError, LineupParseError,
            LineupRecommendationError, NFLScheduleError, ValueError) as error:
        # Only allowlisted exception types from our own internal validation.
        print("LINEUP DRY RUN: analysis unavailable; no lineup submission attempted.")
        print("LINEUP DRY RUN: failure_category=", type(error).__name__)
        print("LINEUP DRY RUN: safe_failure_detail=", str(error))
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
