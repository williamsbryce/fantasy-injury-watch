"""Recent CFFL-scored fantasy points, from completed MFL weekly playerScores.

Ranking uses last three available completed WEEKLY score records, not season
AVG or NFL yardage. Missing records are NOT fabricated as zero.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from .model import as_list


class RecentScoresError(ValueError):
    pass


def _valid_score(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def parse_week_scores(data):
    root = data.get("playerScores") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        raise RecentScoresError("MFL weekly playerScores root missing")
    items = as_list(root.get("playerScore") or root.get("player"))
    if not items:
        raise RecentScoresError("MFL weekly playerScores has no player records")
    out = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        player_id = str(row.get("id") or "")
        value = _valid_score(row.get("score"))
        if player_id.isdigit() and value is not None:
            out[player_id] = value
    if not out:
        raise RecentScoresError("MFL weekly playerScores has no valid scores")
    return out


def rank_recent_weekly(weekly, candidate_ids, *, max_games=3):
    """Average up to 3 most recent recorded weeks for each candidate.

    Weekly is ordered most recent to oldest. A player must have at least
    one numeric completed scoring record; unknown scoring -> ineligible.
    """
    if max_games != 3 or not (1 <= len(weekly) <= 6):
        raise RecentScoresError("Invalid recent scoring window")
    if any(not isinstance(w, dict) for w in weekly):
        raise RecentScoresError("Incomplete weekly scoring exports")
    ranks = {}
    for pid in candidate_ids:
        pid = str(pid)
        values = []
        for scores in weekly:
            if pid in scores:
                score = scores[pid]
                if not isinstance(score, Decimal) or not score.is_finite():
                    raise RecentScoresError("Invalid candidate weekly score")
                values.append(score)
                if len(values) == max_games:
                    break
        if values:
            ranks[pid] = {
                "average": sum(values, Decimal("0")) / Decimal(len(values)),
                "games": len(values),
                "scores": tuple(values),
            }
    return ranks


def fetch_week_scores(year, league, key, week, client="FantasyInjuryWatch"):
    if not (year == 2026 and league == "40298" and 1 <= int(week) <= 18 and key):
        raise RecentScoresError("Unsupported scoring request")
    params = urllib.parse.urlencode({
        "TYPE": "playerScores", "L": league, "W": str(week),
        "JSON": "1", "APIKEY": key,
    })
    request = urllib.request.Request(
        f"https://api.myfantasyleague.com/{year}/export?{params}",
        headers={"Accept": "application/json", "User-Agent": client},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read(5_000_000))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError, OSError):
        raise RecentScoresError("MFL weekly scoring feed unavailable") from None
    if isinstance(payload, dict) and "error" in payload:
        raise RecentScoresError("MFL weekly scoring API denied or unavailable")
    return parse_week_scores(payload)


def recent_scores_for_week(year, league, key, current_week, client="FantasyInjuryWatch"):
    if int(current_week) <= 1:
        return {}
    start = int(current_week) - 1
    # Six past completed weeks accommodate most bye gaps.
    weeks = range(start, max(0, start - 6), -1)
    results = []
    for index, week in enumerate(weeks):
        results.append(fetch_week_scores(year, league, key, week, client))
        if index < 5:
            time.sleep(1)
    return results
