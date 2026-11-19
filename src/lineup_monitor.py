"""Optional, read-only current-week lineup monitor for the public dashboard.

Unknown stays unknown. Never infer starters from the roster export and never
submit lineup changes. Network problems do not invalidate injury statuses.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

REGINA = ZoneInfo("America/Regina")
EXPECTED_STARTERS = 17
ALIASES = {
    "ARZ": "ARI", "GBP": "GB", "KCC": "KC", "NEP": "NE",
    "NOS": "NO", "SFO": "SF", "TBB": "TB", "JAC": "JAX",
    "WAS": "WSH", "LVR": "LV", "RAM": "LAR",
}
OFF_ROSTER = {"IR", "INJURED_RESERVE", "INJURED RESERVE",
              "TAXI", "TAXI_SQUAD", "TAXI SQUAD"}


def _get_json(url, *, headers=None, timeout=15):
    request = urllib.request.Request(
        url, method="GET",
        headers={"Accept": "application/json",
                 "User-Agent": "FantasyInjuryWatch/1.0", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(3_000_000))


def current_week_context(year, now=None):
    """Read ESPN's current regular season week and its scheduled games."""
    now = now or datetime.now(timezone.utc)
    try:
        current = _get_json(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?limit=100"
        )
        year_found = int((current.get("season") or {}).get("year"))
        week = int((current.get("week") or {}).get("number"))
        kind = int((current.get("season") or {}).get("type"))
        if year_found != int(year) or kind != 2 or not 1 <= week <= 18:
            return None
        params = urllib.parse.urlencode(
            {"dates": year_found, "seasontype": 2, "week": week, "limit": 100}
        )
        weekly = _get_json(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?"
            + params
        )
        if str((weekly.get("week") or {}).get("number")) != str(week):
            return None
        games = []
        for event in weekly.get("events") or []:
            start = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                return None
            competition = event["competitions"][0]["competitors"]
            teams = [str(row["team"]["abbreviation"]).upper() for row in competition]
            if len(teams) != 2:
                return None
            games.append({"kickoff": start.astimezone(timezone.utc), "teams": teams})
        if len(games) < 12 or len(games) > 16:
            return None
        return {"week": week, "games": games}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError,
            urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
        return None


def _list(node):
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def submitted_starter_ids(payload, franchise_id):
    """Distinguish explicit blank MFL lineup from missing/unreadable results.

    Returns None when the current-week export does not establish submission.
    Returns [] only if MFL explicitly supplies an empty starters field.
    """
    root = payload.get("weeklyResults")
    if not isinstance(root, dict):
        return None
    rows = []
    for matchup in _list(root.get("matchup")):
        if isinstance(matchup, dict):
            rows.extend(_list(matchup.get("franchise")))
    rows.extend(_list(root.get("franchise")))
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("id", "")).zfill(4) == str(franchise_id).zfill(4)]
    if len(matches) != 1:
        return None
    record = matches[0]
    if "starters" in record and record["starters"] is not None:
        raw = record["starters"]
        if isinstance(raw, str):
            values = raw.split(",")
        elif isinstance(raw, list):
            values = raw
        else:
            return None
    else:
        # Player rows are only reliable when statuses explicitly identify starters.
        players = [p for p in _list(record.get("player")) if isinstance(p, dict)]
        if not players or not any("status" in p for p in players):
            return None
        values = [p.get("id") for p in players
                  if str(p.get("status", "")).lower() == "starter"]
    ids = [str(pid).strip() for pid in values if str(pid).strip()]
    if any(not pid.isdigit() for pid in ids) or len(ids) != len(set(ids)):
        return None
    return ids


def fetch_weekly_lineup(year, league_id, api_key, week):
    """One bounded API read. No cookie and no HTML, POST, or retries."""
    query = urllib.parse.urlencode(
        {"TYPE": "weeklyResults", "L": league_id, "W": int(week),
         "JSON": "1", "APIKEY": api_key})
    url = f"https://api.myfantasyleague.com/{int(year)}/export?{query}"
    try:
        doc = _get_json(url)
        return doc if isinstance(doc, dict) and "error" not in doc else None
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError,
            ValueError, TypeError):
        return None


def _roster_ids_and_teams(feeds, franchise_id):
    franchises = _list((feeds.get("rosters") or {}).get("rosters", {}).get("franchise"))
    matched = [f for f in franchises if isinstance(f, dict) and
               str(f.get("id", "")).zfill(4) == str(franchise_id).zfill(4)]
    if len(matched) != 1:
        return None, None
    roster = [p for p in _list(matched[0].get("player")) if isinstance(p, dict)
              and str(p.get("status", "")).upper().strip() not in OFF_ROSTER]
    ids = {str(p["id"]) for p in roster if p.get("id") is not None}
    all_players = _list((feeds.get("players") or {}).get("players", {}).get("player"))
    teams = {str(p["id"]): ALIASES.get(str(p.get("team", "")).upper(),
                                    str(p.get("team", "")).upper())
             for p in all_players if isinstance(p, dict) and p.get("id") is not None}
    return ids, teams


def enrich_lineup(report, feeds, league, context, api_key, now=None,
                  fetcher=fetch_weekly_lineup):
    """Attach trustworthy lineup context; leave injuries usable on read failures."""
    now = now or datetime.now(timezone.utc)
    info = {"week": context["week"] if context else None, "state": "unknown",
            "checked_at": now.isoformat(), "warning": None,
            "kickoff": None, "starters_count": None}
    report["lineup"] = info
    for alert in report.get("alerts", []):
        alert["lineup_role"] = "unknown"
    if context is None:
        return report
    ids, teams = _roster_ids_and_teams(feeds, league["franchise_id"])
    if not ids or teams is None:
        return report
    payload = fetcher(league["season"], league["id"], api_key, context["week"])
    if payload is None:
        return report
    submitted = submitted_starter_ids(payload, league["franchise_id"])
    if submitted is None or any(pid not in ids for pid in submitted):
        return report
    info["starters_count"] = len(submitted)
    if not submitted:
        info["state"] = "not_submitted"
    elif len(submitted) != EXPECTED_STARTERS:
        info["state"] = "incomplete"
    else:
        info["state"] = "submitted"
    if submitted:
        starter_set = set(submitted)
        for alert in report["alerts"]:
            pid = str(alert.get("player_id"))
            # In an incomplete lineup, selected starters are known but
            # every unselected player may still be an intended starter.
            alert["lineup_role"] = (
                "starter" if pid in starter_set else
                "bench" if info["state"] == "submitted" else "unknown")
    # A pregame warning is valid only when MFL explicitly reported a missing
    # or incomplete current-week lineup, the kickoff is near, and the affected
    # Thursday game includes at least one active roster player.
    if info["state"] not in {"not_submitted", "incomplete"}:
        return report
    local_day = now.astimezone(REGINA).weekday()
    if local_day not in (3, 6):
        return report
    upcoming = sorted(
        (g for g in context["games"]
         if g["kickoff"].astimezone(REGINA).date() ==
            now.astimezone(REGINA).date()
         and timedelta(0) < g["kickoff"] - now <= timedelta(hours=4)),
        key=lambda g: g["kickoff"]
    )
    if local_day == 3:
        player_teams = {teams.get(pid) for pid in ids}
        upcoming = [game for game in upcoming
                    if any(team in player_teams for team in game["teams"])]
    if not upcoming:
        return report
    info["kickoff"] = upcoming[0]["kickoff"].isoformat()
    info["warning"] = (
        f"Week {context['week']} has no submitted starting lineup in MFL."
        if info["state"] == "not_submitted" else
        f"Week {context['week']} has only {len(submitted)} of "
        f"{EXPECTED_STARTERS} expected starters in MFL."
    )
    return report
