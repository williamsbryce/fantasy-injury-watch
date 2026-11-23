"""Only send injury alerts that can still affect a verified fantasy starter.

A late MFL injury feed is useful to the dashboard but not an urgent
email. No NFL schedule or unverified starter identity means no urgent email.
"""
from datetime import datetime, timedelta, timezone

from .lineup_monitor import ALIASES

MIN_TIME_TO_KICKOFF = timedelta(minutes=15)
MAX_TIME_TO_KICKOFF = timedelta(hours=72)


def _kickoff(player, context):
    if not isinstance(context, dict) or not isinstance(context.get("games"), list):
        return None
    team = str(player.get("nfl_team") or "").upper().strip()
    team = ALIASES.get(team, team)
    matches = [
        g.get("kickoff") for g in context["games"]
        if isinstance(g, dict) and team in (g.get("teams") or [])
    ]
    if len(matches) != 1 or not isinstance(matches[0], datetime):
        return None
    kickoff = matches[0]
    return kickoff.astimezone(timezone.utc) if kickoff.tzinfo else None


def actionable_urgent_starters(current, previous, context, now,
                               *, detect_new):
    """Return only newly Out/Inactive *confirmed starters* before kickoff.

    Avoid after-game emails, alerts about bench players, and messages based on
    an incomplete current-week lineup. A missing schedule fails closed.
    """
    if now.tzinfo is None:
        raise ValueError("Notification clock must be timezone aware")
    if not context or context.get("week") is None:
        return []
    new = detect_new(current, previous)
    result = []
    for league in current.get("leagues", []):
        lineup = league.get("lineup") or {}
        if lineup.get("state") != "submitted" or lineup.get("week") != context["week"]:
            continue
        valid_keys = {
            str(a.get("key")) for a in league.get("alerts", [])
            if a.get("lineup_role") == "starter" and a.get("key") is not None
        }
        for a in new:
            if str(a.get("key")) not in valid_keys:
                continue
            kickoff = _kickoff(a, context)
            if kickoff is None:
                continue
            until = kickoff - now
            if MIN_TIME_TO_KICKOFF < until <= MAX_TIME_TO_KICKOFF:
                result.append(a)
    return list({str(a["key"]): a for a in result}.values())
