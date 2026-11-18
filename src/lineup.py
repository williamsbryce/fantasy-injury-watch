"""Safe lineup inspection and same-position swap planning for MyFantasyLeague."""
from .model import as_list, friendly_name


class LineupError(ValueError):
    pass


def player_ids(csv):
    if not isinstance(csv, str):
        raise LineupError("Expected a comma-separated list of player IDs")
    ids = [x.strip() for x in csv.split(",") if x.strip()]
    if any(not x.isdigit() for x in ids) or len(ids) != len(set(ids)):
        raise LineupError("Invalid or duplicated player IDs in MFL lineup")
    return ids


def _franchise_nodes(value):
    """MFL wraps franchises under matchups; accept either singleton or arrays."""
    if isinstance(value, dict):
        if "starters" in value and "id" in value:
            yield value
        for child in value.values():
            yield from _franchise_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _franchise_nodes(child)


def inspect_lineup(weekly_feed, roster_feed, player_feed, franchise_id):
    weekly = weekly_feed.get("weeklyResults")
    if not isinstance(weekly, dict):
        raise LineupError("MFL weeklyResults is unavailable; no lineup can be inferred")
    franchises = [f for f in _franchise_nodes(weekly)
                  if str(f.get("id", "")).zfill(4) == franchise_id]
    if len(franchises) != 1:
        raise LineupError("Cannot uniquely identify submitted franchise lineup")
    starters = player_ids(franchises[0].get("starters", ""))
    if not starters:
        raise LineupError("No submitted starters found for this week")
    rosters = roster_feed.get("rosters", {})
    if not isinstance(rosters, dict):
        raise LineupError("Malformed roster feed")
    roster = next((f for f in as_list(rosters.get("franchise"))
                   if str(f.get("id", "")).zfill(4) == franchise_id), None)
    if roster is None:
        raise LineupError("Franchise not found in roster feed")
    roster_entries = {str(p.get("id")): p for p in as_list(roster.get("player"))
                      if isinstance(p, dict) and p.get("id")}
    player_root = player_feed.get("players", {})
    if not isinstance(player_root, dict):
        raise LineupError("Malformed player feed")
    players = {str(p.get("id")): p for p in as_list(player_root.get("player"))
               if isinstance(p, dict) and p.get("id")}
    if not set(starters).issubset(roster_entries) or not set(starters).issubset(players):
        raise LineupError("Submitted starters do not match the current roster/player feed")
    eligible = {}
    for pid, entry in roster_entries.items():
        if str(entry.get("status", "")).upper().replace(" ", "_") in {
                "IR", "INJURED_RESERVE", "TAXI", "TAXI_SQUAD"}:
            continue
        if pid not in players:
            continue
        p = players[pid]
        eligible[pid] = {
            "id": pid, "name": friendly_name(p.get("name")),
            "position": str(p.get("position", "")).upper(),
            "team": str(p.get("team", "")),
        }
    if not set(starters).issubset(eligible):
        raise LineupError("Submitted lineup includes unavailable/ineligible roster players")
    return {
        "franchise_id": franchise_id,
        "starters": [eligible[pid] for pid in starters],
        "bench": [p for pid, p in eligible.items() if pid not in starters],
        "starter_ids": starters,
    }


def prepare_swap(lineup, remove_id, add_id):
    """Preserve all other starters; same-position swaps only in the initial release."""
    starter_ids = list(lineup["starter_ids"])
    starters = {p["id"]: p for p in lineup["starters"]}
    bench = {p["id"]: p for p in lineup["bench"]}
    if remove_id not in starters:
        raise LineupError("Outgoing player is not in the submitted starting lineup")
    if add_id not in bench:
        raise LineupError("Incoming player is not on the eligible bench")
    if starters[remove_id]["position"] != bench[add_id]["position"]:
        raise LineupError("Initial release permits same-position swaps only")
    result = [add_id if pid == remove_id else pid for pid in starter_ids]
    if len(result) != len(starter_ids) or len(result) != len(set(result)):
        raise LineupError("Swap would invalidate lineup")
    return result


def verify_swap(original_ids, new_ids, outgoing, incoming):
    original, new = set(original_ids), set(new_ids)
    return (
        len(original_ids) == len(new_ids)
        and len(new_ids) == len(new)
        and original - new == {outgoing}
        and new - original == {incoming}
    )
