"""Read-only checks for injured players in a submitted MFL weekly lineup.

This module never sends lineup changes. It intentionally fails closed when
MFL has not returned a submitted lineup and does not guess FLEX eligibility.
"""
from .model import as_list, friendly_name, status_group

OFF_ROSTER = {"IR", "INJURED_RESERVE", "INJURED RESERVE",
              "TAXI", "TAXI_SQUAD", "TAXI SQUAD"}
UNAVAILABLE = {"out", "inactive", "injured reserve", "ir", "pup",
               "suspended", "non football injury", "nfi"}


def _ids(value):
    """Keep MFL IDs as strings, preserving leading zeroes for team defenses."""
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError("MFL starters field has an unexpected format")
    ids = [str(v).strip() for v in values if str(v).strip()]
    if any(not v.isdigit() for v in ids) or len(set(ids)) != len(ids):
        raise ValueError("MFL starters contain invalid or duplicate player IDs")
    return ids


def read_submitted_starters(weekly_results, franchise_id):
    """Return IDs of a submitted lineup, or None when MFL shows no submission.

    Supports MFL weeklyResults matchups with nested franchises and a flat
    franchise collection. The weeklyResults export is distinct from rosters.
    """
    root = weekly_results.get("weeklyResults")
    if not isinstance(root, dict):
        raise ValueError("MFL weeklyResults feed is missing")
    found = []
    for matchup in as_list(root.get("matchup")):
        if isinstance(matchup, dict):
            found.extend(f for f in as_list(matchup.get("franchise")) if isinstance(f, dict))
    found.extend(f for f in as_list(root.get("franchise")) if isinstance(f, dict))
    matches = [f for f in found
               if str(f.get("id", "")).zfill(4) == str(franchise_id).zfill(4)]
    if len(matches) != 1:
        raise ValueError("Could not uniquely identify franchise in weeklyResults")
    franchise = matches[0]
    if "starters" in franchise and franchise["starters"] is not None:
        parsed = _ids(franchise["starters"])
    else:
        # Some MFL responses include individual player rows instead.
        rows = as_list(franchise.get("player"))
        if not rows:
            return None
        if not any(isinstance(row, dict) and "status" in row for row in rows):
            return None
        parsed = [str(p["id"]) for p in rows
                  if isinstance(p, dict) and str(p.get("status", "")).lower() == "starter"
                  and p.get("id") is not None]
        parsed = _ids(parsed)
    return parsed or None


def find_unavailable_starters(weekly_results, feeds, franchise_id):
    """Identify Out/Inactive starters and preliminary same-position bench options.

    These are NOT legal-lineup or game-lock validations, and no replacement is
    selected. Never interpret an unreadable lineup as an all-clear.
    """
    starters = read_submitted_starters(weekly_results, franchise_id)
    if not starters:
        return {"lineup_submitted": False, "starter_ids": [],
                "unavailable_starters": [], "requires_review": True}
    roster_root = feeds.get("rosters", {}).get("rosters", {})
    player_root = feeds.get("players", {}).get("players", {})
    injury_root = feeds.get("injuries", {}).get("injuries", {})
    if not all(isinstance(v, dict) for v in (roster_root, player_root, injury_root)):
        raise ValueError("Incomplete MFL roster, player, or injury feed")
    franchise = next((f for f in as_list(roster_root.get("franchise"))
                      if isinstance(f, dict)
                      and str(f.get("id", "")).zfill(4) == str(franchise_id).zfill(4)), None)
    if franchise is None:
        raise ValueError("Franchise missing from MFL roster")
    players = {str(p["id"]): p for p in as_list(player_root.get("player"))
               if isinstance(p, dict) and p.get("id") is not None}
    injuries = {str(i["id"]): i for i in as_list(injury_root.get("injury"))
                if isinstance(i, dict) and i.get("id") is not None}
    roster = {str(p["id"]): p for p in as_list(franchise.get("player"))
              if isinstance(p, dict) and p.get("id") is not None
              and str(p.get("status", "")).upper().strip() not in OFF_ROSTER}
    # If the requested lineup cannot be reconciled, don't recommend a change.
    if any(pid not in roster or pid not in players for pid in starters):
        raise ValueError("MFL weekly starters cannot be reconciled with active roster")
    issues = []
    for pid in starters:
        injury = injuries.get(pid, {})
        designation = str(injury.get("status", "")).lower().strip().replace("_", " ")
        if designation not in UNAVAILABLE:
            continue
        player = players[pid]
        pos = str(player.get("position", "")).upper()
        candidates = []
        for bench_id, bench_row in roster.items():
            if bench_id in starters or bench_id not in players:
                continue
            candidate = players[bench_id]
            if str(candidate.get("position", "")).upper() != pos:
                continue
            bench_injury = injuries.get(bench_id, {})
            bench_status = str(bench_injury.get("status", "")).strip()
            if status_group(bench_status) == "action":
                continue
            candidates.append({
                "player_id": bench_id, "name": friendly_name(candidate.get("name")),
                "position": pos, "injury_status": bench_status or None,
            })
        candidates.sort(key=lambda p: (bool(p["injury_status"]), p["name"]))
        issues.append({
            "player_id": pid, "name": friendly_name(player.get("name")),
            "position": pos, "injury_status": str(injury.get("status", "")),
            "preliminary_same_position_bench": candidates,
        })
    return {"lineup_submitted": True, "starter_ids": starters,
            "unavailable_starters": issues, "requires_review": bool(issues)}
