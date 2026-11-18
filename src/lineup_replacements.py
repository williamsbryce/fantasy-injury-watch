"""Pure, fail-closed recommendations for replacing confirmed Out starters.

Read-only, no network calls. Uses MFL league-scored points-per-game averages.
Only same-position substitutions are proposed until flex/IDP validation is
verified against this league's live starting-position constraints.
"""
from decimal import Decimal, InvalidOperation

from .nfl_week import normalize_team
from .model import as_list, status_group

BLOCKED_ROSTER = {"IR", "INJURED_RESERVE", "INJURED RESERVE",
                  "TAXI", "TAXI_SQUAD", "TAXI SQUAD"}
OUT_DESIGNATIONS = {"out", "inactive", "injured reserve", "ir", "pup",
                    "suspended", "nfi", "non football injury"}


class LineupRecommendationError(ValueError):
    pass


def score_map(avg_export):
    root = avg_export.get("playerScores") if isinstance(avg_export, dict) else None
    if not isinstance(root, dict):
        raise LineupRecommendationError("MFL AVG score feed missing")
    result = {}
    for item in as_list(root.get("playerScore") or root.get("player")):
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        value = str(item.get("score") or "").strip()
        if not pid.isdigit():
            continue
        try:
            score = Decimal(value)
        except (InvalidOperation, ValueError):
            continue
        if score.is_finite():
            result[pid] = score
    if not result:
        raise LineupRecommendationError("No league AVG scores available")
    return result


def teams_with_games(nfl_schedule):
    root = nfl_schedule.get("nflSchedule") if isinstance(nfl_schedule, dict) else None
    if not isinstance(root, dict):
        raise LineupRecommendationError("NFL week schedule unavailable")
    teams = set()
    games = as_list(root.get("game"))
    for game in games:
        if not isinstance(game, dict):
            continue
        for team in as_list(game.get("team")):
            if isinstance(team, dict):
                code = str(team.get("id") or "").upper().strip()
                if code:
                    teams.add(code)
    if not (8 <= len(teams) <= 32):
        raise LineupRecommendationError("NFL week schedule cannot be validated")
    return teams


def propose_out_replacements(selected, selectable, feeds, averages, teams_playing, franchise_id):
    """Return a proposed full lineup, never actually submit it.

    The replacement must be actively rostered, unlocked/selectable in the
    actual MFL owner form, not already starting, without any injury flag,
    and playing an NFL game in the target week.
    """
    selected = list(selected)
    selectable = set(selectable)
    if not selected or len(selected) != len(set(selected)):
        raise LineupRecommendationError("Starting lineup missing or duplicated")
    if not set(selected).issubset(selectable):
        raise LineupRecommendationError("Selected player not available in current form")
    if not isinstance(teams_playing, set) or not teams_playing:
        raise LineupRecommendationError("NFL games or bye weeks not verified")

    rr = feeds.get("rosters", {}).get("rosters", {})
    pr = feeds.get("players", {}).get("players", {})
    ir = feeds.get("injuries", {}).get("injuries", {})
    if not (isinstance(rr, dict) and isinstance(pr, dict) and isinstance(ir, dict)):
        raise LineupRecommendationError("Missing roster, player, or injury feeds")

    target = next((x for x in as_list(rr.get("franchise"))
                   if isinstance(x, dict)
                   and str(x.get("id") or "").zfill(4) == str(franchise_id).zfill(4)), None)
    if target is None:
        raise LineupRecommendationError("Owner franchise not found in roster")

    owned = {str(p["id"]): p for p in as_list(target.get("player"))
             if isinstance(p, dict) and p.get("id") is not None
             and str(p.get("status") or "").upper() not in BLOCKED_ROSTER}
    players = {str(p["id"]): p for p in as_list(pr.get("player"))
               if isinstance(p, dict) and p.get("id") is not None}
    injuries = {str(p["id"]): p for p in as_list(ir.get("injury"))
                if isinstance(p, dict) and p.get("id") is not None}

    if any(pid not in owned or pid not in players for pid in selected):
        raise LineupRecommendationError("Selected lineup cannot be reconciled with active roster")
    proposed = selected.copy()
    used = set(selected)
    changes = []
    unresolved = []
    for i, pid in enumerate(selected):
        status = str(injuries.get(pid, {}).get("status") or "").lower().strip().replace("_", " ")
        if status not in OUT_DESIGNATIONS:
            continue
        position = str(players[pid].get("position") or "").upper().strip()
        if not position:
            unresolved.append(pid)
            continue
        choices = []
        for bench in owned:
            if bench in used or bench not in selectable or bench not in players:
                continue
            p = players[bench]
            if str(p.get("position") or "").upper().strip() != position:
                continue
            nfl_team = normalize_team(p.get("team"))
            if nfl_team not in teams_playing:
                continue
            injury_status = str(injuries.get(bench, {}).get("status") or "")
            if status_group(injury_status) != "clear":
                continue
            if bench not in averages:
                continue
            choices.append((averages[bench], bench))
        if not choices:
            unresolved.append(pid)
            continue
        # Deterministic tie-breaker by player ID; league AVG is the first rule.
        avg, picked = sorted(choices, key=lambda pair: (-pair[0], pair[1]))[0]
        proposed[i] = picked
        used.add(picked)
        changes.append({"out_player_id": pid, "in_player_id": picked,
                        "league_ppg_average": str(avg)})

    if unresolved:
        # Do not submit an incomplete set of replacements.
        return {"status": "needs_review", "out_starters": len(changes) + len(unresolved),
                "unresolved_count": len(unresolved), "changes": [],
                "proposed_lineup": None}
    if not changes:
        return {"status": "no_out_starters", "out_starters": 0, "unresolved_count": 0,
                "changes": [], "proposed_lineup": selected}
    if len(proposed) != len(selected) or len(set(proposed)) != len(proposed):
        raise LineupRecommendationError("Replacement lineup invariants failed")
    changed_indices = [i for i, (before, after) in enumerate(zip(selected, proposed))
                       if before != after]
    if len(changed_indices) != len(changes):
        raise LineupRecommendationError("Unexpected change to existing starter")
    return {"status": "recommendation_ready", "out_starters": len(changes),
            "unresolved_count": 0, "changes": changes,
            "proposed_lineup": proposed}
