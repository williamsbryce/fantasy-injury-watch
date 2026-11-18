"""Independent NFL week schedule and bye / kickoff eligibility, read-only.

ESPN's scoreboard lists the NFL scheduled game start times. Only complete,
validated week-wide results are used to make fantasy substitution decisions.
Never guess that a team is playing when schedule validation fails.
"""
from datetime import datetime, timedelta, timezone
import json
import urllib.error
import urllib.parse
import urllib.request

# Common MyFantasyLeague team codes; ESPN uses standard NFL abbreviations.
MFL_ALIASES = {
    "ARZ":"ARI", "GBP":"GB", "KCC":"KC", "NEP":"NE", "NOS":"NO",
    "NOR":"NO", "SFO":"SF", "TBB":"TB", "JAC":"JAX", "WAS":"WSH",
    "WDC":"WSH", "LVR":"LV", "OAK":"LV", "RAM":"LAR",
    "SDC":"LAC", "LA":"LAR", "JAX":"JAX",
}
KNOWN_TEAMS = {
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
    "DET","GB","HOU","IND","JAX","KC","LV","LAC","LAR","MIA",
    "MIN","NE","NO","NYG","NYJ","PHI","PIT","SF","SEA","TB",
    "TEN","WSH",
}


class NFLScheduleError(ValueError):
    pass


def normalize_team(code):
    value = str(code or "").strip().upper()
    return MFL_ALIASES.get(value, value)


def parse_week_schedule(document, year, week):
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        raise NFLScheduleError("Invalid NFL schedule feed")
    league = (document.get("leagues") or [{}])[0]
    season = document.get("season") or {}
    check_year = season.get("year") or league.get("calendarStartDate", "")[:4]
    if check_year and str(check_year) != str(year):
        raise NFLScheduleError("NFL schedule year mismatch")
    raw_week = (document.get("week") or {}).get("number")
    if raw_week is not None and str(raw_week) != str(week):
        raise NFLScheduleError("NFL schedule week mismatch")
    teams = {}
    event_count = 0
    for event in document["events"]:
        if not isinstance(event, dict):
            continue
        try:
            start = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
            competitors = event["competitions"][0]["competitors"]
            codes = [normalize_team(c["team"]["abbreviation"]) for c in competitors]
        except (ValueError, IndexError, KeyError, TypeError):
            raise NFLScheduleError("NFL event is missing date or teams") from None
        if start.tzinfo is None or len(codes) != 2 or codes[0] == codes[1]:
            raise NFLScheduleError("NFL schedule event malformed")
        if not all(code in KNOWN_TEAMS for code in codes):
            raise NFLScheduleError("NFL schedule contains unknown team")
        if any(code in teams for code in codes):
            raise NFLScheduleError("NFL schedule duplicates a team's game")
        teams.update({code: start.astimezone(timezone.utc) for code in codes})
        event_count += 1
    if not (12 <= event_count <= 16) or len(teams) != 2 * event_count:
        raise NFLScheduleError("Incomplete NFL week schedule")
    return teams


def fetch_espn_week(year, week):
    if not (2000 <= int(year) <= 2100 and 1 <= int(week) <= 18):
        raise NFLScheduleError("Invalid NFL season or week")
    query = urllib.parse.urlencode({
        "dates":str(int(year)), "seasontype":"2", "week":str(int(week)), "limit":"100",
    })
    request = urllib.request.Request(
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?"
        + query,
        headers={"User-Agent":"FantasyInjuryWatchBryce/1.0",
                 "Accept":"application/json"},method="GET",
    )
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            doc=json.loads(response.read(5_000_000))
    except (urllib.error.HTTPError,urllib.error.URLError,OSError,ValueError):
        raise NFLScheduleError("Independent NFL weekly schedule unavailable") from None
    return parse_week_schedule(doc,year,week)


def eligible_teams(schedule, now=None, cushion_minutes=5):
    """Teams still eligible for MFL lineup change, conservatively before lock."""
    if not isinstance(schedule,dict) or not schedule:
        raise NFLScheduleError("NFL weekly schedule missing")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise NFLScheduleError("Current time is not timezone-aware")
    cutoff=now+timedelta(minutes=cushion_minutes)
    return {code for code, kickoff in schedule.items() if kickoff > cutoff}
