"""Read-only diagnostic for MFL pregame lineup exports.

Logs only sanitized structural facts. Never prints roster names, player IDs,
league settings values, URLs, response bodies, or API credentials.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

SAFE_TYPES = {"weeklyResults", "playerScores", "league", "nflSchedule"}
SAFE_WEEK = {"11", "12", "AVG"}
URL_BASE = "https://api.myfantasyleague.com"


def _fetch(year, league_id, api_key, client_name, kind, week=None):
    if kind not in SAFE_TYPES or week not in SAFE_WEEK | {None}:
        raise ValueError("Unsupported diagnostic export")
    args = {"TYPE": kind, "L": league_id, "JSON": "1", "APIKEY": api_key}
    if week:
        args["W"] = week
    request = urllib.request.Request(
        f"{URL_BASE}/{year}/export?" + urllib.parse.urlencode(args),
        headers={"User-Agent": client_name, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read(4_000_000))
    except urllib.error.HTTPError as error:
        print(f"PROBE {kind} week={week or 'none'}: HTTP {error.code}")
        return None
    except (ValueError, TimeoutError, urllib.error.URLError, OSError):
        print(f"PROBE {kind} week={week or 'none'}: network_or_json_error")
        return None
    if not isinstance(data, dict):
        print(f"PROBE {kind} week={week or 'none'}: invalid_root_type")
        return None
    if "error" in data:
        print(f"PROBE {kind} week={week or 'none'}: api_error")
        return None
    return data


def _as_list(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def _summarize_lineup(data, franchise_id, week):
    root = data.get("weeklyResults")
    if not isinstance(root, dict):
        print(f"PROBE weeklyResults W={week}: root_missing")
        return
    options = []
    for matchup in _as_list(root.get("matchup")):
        if isinstance(matchup, dict):
            options.extend(x for x in _as_list(matchup.get("franchise")) if isinstance(x, dict))
    options.extend(x for x in _as_list(root.get("franchise")) if isinstance(x, dict))
    matches = [x for x in options
               if str(x.get("id", "")).zfill(4) == franchise_id]
    print(f"PROBE weeklyResults W={week}: franchise_matches={len(matches)} "
          f"root_matchup_present={bool(root.get('matchup'))}")
    if len(matches) != 1:
        return
    f = matches[0]
    starters = f.get("starters")
    if starters is None:
        rows = _as_list(f.get("player"))
        starters_count = sum(str(p.get("status", "")).lower() == "starter"
                             for p in rows if isinstance(p, dict))
        print(f"PROBE weeklyResults W={week}: starters_field=absent "
              f"player_rows={len(rows)} player_starter_rows={starters_count}")
    else:
        starters_count = len([p for p in str(starters).split(",") if p.strip()])
        print(f"PROBE weeklyResults W={week}: starters_field=present "
              f"starter_count={starters_count} nonstarters_field={'nonstarters' in f}")


def _summarize_other(data, kind, week):
    root = data.get(kind)
    if not isinstance(root, dict):
        print(f"PROBE {kind} W={week or 'none'}: root_missing")
        return
    if kind == "playerScores":
        rows = _as_list(root.get("playerScore") or root.get("player"))
        if not rows:
            rows = _as_list(root.get("playerScores"))
        print(f"PROBE {kind} W={week}: score_rows={len(rows)} "
              f"has_scores={any(isinstance(x,dict) and 'score' in x for x in rows)} "
              f"has_players={any(isinstance(x,dict) and 'id' in x for x in rows)}")
    elif kind == "nflSchedule":
        print(f"PROBE {kind} W={week}: "
              f"schedule_rows={len(_as_list(root.get('game') or root.get('matchup')))}")
    elif kind == "league":
        starters = root.get("starters")
        print(f"PROBE league: starter_rules_present={starters is not None} "
              f"roster_size_present={'rosterSize' in root} " 
              f"current_week_present={'currentWeek' in root}")


def run():
    key = os.environ.get("MFL_API_KEY", "")
    league_id = os.environ.get("MFL_LEAGUE_ID", "")
    franchise_id = os.environ.get("MFL_FRANCHISE_ID", "").zfill(4)
    client_name = os.environ.get("MFL_CLIENT_NAME") or "FantasyInjuryWatchBryce"
    season = os.environ.get("MFL_SEASON") or "2026"
    if not key or not league_id.isdigit() or not franchise_id.isdigit() or not season.isdigit():
        raise RuntimeError("Probe missing existing MFL read-only secrets or variables")
    tasks = [("weeklyResults", "12"), ("weeklyResults", "11"),
             ("playerScores", "AVG"), ("league", None),
             ("nflSchedule", "12")]
    for idx, (kind, week) in enumerate(tasks):
        if idx:
            time.sleep(3)
        data = _fetch(int(season), league_id, key, client_name, kind, week)
        if data is None:
            continue
        if kind == "weeklyResults":
            _summarize_lineup(data, franchise_id, week)
        else:
            _summarize_other(data, kind, week)
    print("PROBE COMPLETE: no lineup data, names, tokens or URLs were logged or published.")


if __name__ == "__main__":
    run()
