"""Pure policy for automated replacement of confirmed OUT/INACTIVE starters.

Only same-position healthy bench players with unstarted NFL games are eligible.
Partial substitutions are allowed when another Out starter has no option.
"""
from .model import as_list, friendly_name, status_group
from .nfl_week import normalize_team
from .lineup_replacements import OUT_DESIGNATIONS, BLOCKED_ROSTER


class AutoLineupError(ValueError):
    pass


def _records(feeds, franchise):
    rr = feeds.get("rosters", {}).get("rosters")
    pr = feeds.get("players", {}).get("players")
    ir = feeds.get("injuries", {}).get("injuries")
    if not all(isinstance(x, dict) for x in (rr, pr, ir)):
        raise AutoLineupError("Missing current MFL roster, player or injury export")
    if "injury" not in ir or "player" not in pr or "franchise" not in rr:
        raise AutoLineupError("Incomplete MFL export; cannot safely classify health")
    team = next((r for r in as_list(rr["franchise"]) if isinstance(r, dict)
                 and str(r.get("id") or "").zfill(4) == str(franchise).zfill(4)), None)
    if team is None:
        raise AutoLineupError("Franchise does not match MFL roster")
    active = {str(p["id"]): p for p in as_list(team.get("player"))
              if isinstance(p, dict) and p.get("id") is not None
              and str(p.get("status") or "").upper().strip().replace(" ", "_")
              not in {x.replace(" ", "_") for x in BLOCKED_ROSTER}}
    players = {str(p["id"]): p for p in as_list(pr["player"])
               if isinstance(p, dict) and p.get("id") is not None}
    injuries = {str(p["id"]): p for p in as_list(ir["injury"])
                if isinstance(p, dict) and p.get("id") is not None}
    return active, players, injuries


def select_replacements(starters, selectable, feeds, recent, kickoff_eligible_teams,
                        franchise="0001"):
    """Return proposed complete lineup plus changed and unresolved player identities.

    No writes, network or notifications. Locked/started game players never move.
    An otherwise eligible bench candidate must have at least one verified past
    weekly MFL fantasy score and no current Questionable/Doubtful/etc flag.
    """
    starters = list(starters)
    selectable = set(selectable)
    if len(starters) != 17 or len(set(starters)) != 17:
        raise AutoLineupError("Expected exactly 17 unique existing starters")
    if not set(starters).issubset(selectable):
        raise AutoLineupError("Saved starters not all visible in the editable form")
    if not isinstance(kickoff_eligible_teams, set) or not kickoff_eligible_teams:
        raise AutoLineupError("Valid unstarted NFL games required")
    active, players, injuries = _records(feeds, franchise)
    if any(pid not in active or pid not in players for pid in starters):
        raise AutoLineupError("Cannot reconcile existing starters with MFL active roster")

    proposed = starters.copy()
    used = set(starters)
    changes = []
    unresolved = []
    for idx, pid in enumerate(starters):
        status = str(injuries.get(pid, {}).get("status") or "").strip().lower().replace("_", " ")
        if status not in OUT_DESIGNATIONS:
            continue
        p = players[pid]
        name = friendly_name(p.get("name"))
        position = str(p.get("position") or "").upper().strip()
        team_code = normalize_team(p.get("team"))
        if team_code not in kickoff_eligible_teams:
            unresolved.append({"player_id": pid, "name": name,
                               "reason": "starter_game_already_locked_or_not_scheduled"})
            continue
        if not position:
            unresolved.append({"player_id": pid, "name": name,
                               "reason": "position_not_known"})
            continue

        candidates = []
        for bench, b in active.items():
            if bench in used or bench not in selectable or bench not in players:
                continue
            bp = players[bench]
            if str(bp.get("position") or "").upper().strip() != position:
                continue
            if normalize_team(bp.get("team")) not in kickoff_eligible_teams:
                continue
            if status_group(injuries.get(bench, {}).get("status") or "") != "clear":
                # Excludes Questionable, Doubtful, Out and unfamiliar statuses.
                continue
            ranking = recent.get(bench)
            if not ranking or ranking.get("games", 0) < 1:
                continue
            candidates.append((ranking["average"], ranking["games"], bench))

        if not candidates:
            unresolved.append({"player_id": pid, "name": name,
                               "reason": "no_healthy_same_position_bench_option_with_recent_scores"})
            continue
        score, games, pick = sorted(candidates, key=lambda x: (-x[0], -x[1], x[2]))[0]
        proposed[idx] = pick
        used.add(pick)
        changes.append({
            "out_player_id": pid, "out_name": name,
            "in_player_id": pick, "in_name": friendly_name(players[pick].get("name")),
            "position": position, "recent_average": str(score), "recent_games": games,
        })

    if len(proposed) != 17 or len(set(proposed)) != 17:
        raise AutoLineupError("Proposed lineup is not exactly 17 unique starters")
    if set(proposed).difference(starters) != {c["in_player_id"] for c in changes}:
        raise AutoLineupError("Unexpected additions in replacement plan")
    if set(starters).difference(proposed) != {c["out_player_id"] for c in changes}:
        raise AutoLineupError("Unexpected removals in replacement plan")
    if changes and unresolved:
        status = "partial"
    elif changes:
        status = "ready"
    elif unresolved:
        status = "unresolved"
    else:
        status = "healthy"
    return {"status": status, "proposed_lineup": proposed, "changes": changes,
            "unresolved": unresolved}
