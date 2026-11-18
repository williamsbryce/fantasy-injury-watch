"""Game-day schedule gate: one early-game Thursday/Sunday check, Regina time."""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .nfl_week import fetch_espn_week, NFLScheduleError

REGINA = ZoneInfo("America/Regina")


def discover_current_nfl_week(year=2026):
    request = urllib.request.Request(
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?limit=100",
        headers={"Accept": "application/json", "User-Agent": "FantasyInjuryWatch/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            doc = json.loads(response.read(3_000_000))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, TimeoutError):
        raise NFLScheduleError("Current NFL scoreboard unavailable") from None
    if not isinstance(doc, dict):
        raise NFLScheduleError("Unexpected current scoreboard format")
    season = doc.get("season") or {}
    week = doc.get("week") or {}
    try:
        current_year = int(season.get("year"))
        current_week = int(week.get("number"))
        season_type = int(season.get("type", 2))
    except (ValueError, TypeError, AttributeError):
        raise NFLScheduleError("Cannot identify current regular-season NFL week") from None
    if current_year != int(year) or season_type != 2 or not 1 <= current_week <= 18:
        raise NFLScheduleError("NFL scoreboard outside configured regular season")
    return current_week


def check_due(schedule, now, *, force_dry_run=False):
    """Check only on Thursday or Sunday, about an hour before first game.

    Hourly cron combined with a half-open window of [35,95) minutes before kickoff
    yields one nominal check on a game day, including London/holiday games.
    """
    if not isinstance(schedule, dict) or now.tzinfo is None:
        raise NFLScheduleError("Validated schedule and timezone-aware now required")
    if force_dry_run:
        return {"due": True, "reason": "manual_read_only", "first_kickoff": None}
    local = now.astimezone(REGINA)
    if local.weekday() not in (3, 6):
        return {"due": False, "reason": "not_thursday_or_sunday",
                "first_kickoff": None}
    games_today = sorted({kickoff for kickoff in schedule.values()
                          if kickoff.astimezone(REGINA).date() == local.date()})
    if not games_today:
        return {"due": False, "reason": "no_games_today", "first_kickoff": None}
    first = games_today[0]
    minutes_to_first = (first - now).total_seconds() / 60
    return {"due": 35 <= minutes_to_first < 95,
            "reason": "pregame_window" if 35 <= minutes_to_first <= 95 else "not_pregame_window",
            "first_kickoff": first,
            "minutes_to_first": minutes_to_first}
