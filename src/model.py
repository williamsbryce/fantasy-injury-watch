"""Merge MFL roster, player identities and injury feed by MFL player ID."""
from datetime import datetime, timezone


ACTION = {"out", "inactive", "injured reserve", "ir", "pup", "suspended", "non football injury", "nfi"}
WATCH = {"questionable", "doubtful", "limited", "dnp", "did not practice", "day to day", "day-to-day", "probable"}
CLEAR = {"", "healthy", "active", "cleared", "full", "no injury"}


def as_list(node):
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def friendly_name(name):
    name = str(name or "Unknown player").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return name


def status_group(value):
    normalized = str(value or "").strip().lower().replace("_", " ")
    if normalized in CLEAR:
        return "clear"
    if normalized in ACTION or "inactive" in normalized or "out" == normalized:
        return "action"
    # An unfamiliar designation must not silently be reported as healthy.
    return "watch"


def parse_report(mfl: dict, league: dict, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    roster_data = mfl["rosters"].get("rosters", {})
    player_data = mfl["players"].get("players", {})
    injury_data = mfl["injuries"].get("injuries", {})
    if not all(isinstance(v, dict) for v in (roster_data, player_data, injury_data)):
        raise ValueError("Malformed MFL feed sections")
    if "franchise" not in roster_data or "player" not in player_data or "injury" not in injury_data:
        raise ValueError("Incomplete MFL feed, refusing to present an all-clear")
    franchises = as_list(roster_data["franchise"])
    selected = next((f for f in franchises if str(f.get("id", "")).zfill(4) == league["franchise_id"]), None)
    if selected is None:
        raise ValueError("Your franchise was not found in the roster response")
    roster = as_list(selected.get("player"))
    if not roster:
        raise ValueError("Your franchise roster is empty or not accessible")
    known_players = {str(p["id"]): p for p in as_list(player_data["player"]) if isinstance(p, dict) and p.get("id")}
    known_injuries = {str(i["id"]): i for i in as_list(injury_data["injury"]) if isinstance(i, dict) and i.get("id")}
    alerts = []
    unresolved_names = 0
    monitored = 0
    for roster_player in roster:
        roster_status = str(roster_player.get("status", "")).upper().strip()
        # IR and taxi players are not actionable lineup injury alerts.
        if roster_status in {"INJURED_RESERVE", "INJURED RESERVE", "IR", "TAXI_SQUAD", "TAXI SQUAD", "TAXI"}:
            continue
        monitored += 1
        pid = str(roster_player.get("id", ""))
        player = known_players.get(pid)
        if not player:
            unresolved_names += 1
            continue
        injury = known_injuries.get(pid)
        if not injury:
            continue
        status = str(injury.get("status", "Unknown")).strip()
        group = status_group(status)
        if group == "clear":
            continue
        details = str(injury.get("details", "") or "").strip()[:280]
        # exp_return is an estimate from the feed, not a confirmed return date.
        alerts.append({
            "key": f"{league['id']}:{pid}", "player_id": pid,
            "name": friendly_name(player.get("name")),
            "position": str(player.get("position", "")),
            "nfl_team": str(player.get("team", "")),
            "league": league["name"], "league_id": league["id"],
            "roster_status": str(roster_player.get("status", "")),
            "status": status, "group": group, "details": details,
            "expected_return": str(injury.get("exp_return", "") or "")[:100],
            "source": "MyFantasyLeague injury feed",
            "source_timestamp": str(injury_data.get("timestamp", "") or ""),
            "mfl_news_url": f"https://www.myfantasyleague.com/{int(league['season'])}/news_articles?L={league['id']}&PLAYERS={pid}",
        })
    # If identity mapping fails, fail closed. Otherwise a missing player could be reported as healthy.
    if unresolved_names:
        raise ValueError(f"Player identity mapping incomplete ({unresolved_names} roster records)")
    alerts.sort(key=lambda a: (0 if a["group"] == "action" else 1, a["name"]))
    return {
        "id": league["id"], "name": league["name"],
        "platform": "MyFantasyLeague", "franchise_id": league["franchise_id"],
        "players_checked": monitored, "full_roster_count": len(roster), "feed_timestamp": str(injury_data.get("timestamp", "") or ""),
        "synced_at": now.isoformat(), "alerts": alerts,
    }
