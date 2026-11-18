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
        numeric_score_count = sum(
            isinstance(x, dict) and str(x.get("score", "")).replace(".", "", 1).replace("-", "", 1).isdigit()
            for x in rows
        )
        print(f"PROBE playerScores AVG: numeric_score_count={numeric_score_count} "
              f"first_row_fields_present="
              f"{','.join(k for k in ('id','score','isAvailable','status') if rows and isinstance(rows[0], dict) and k in rows[0])}")
        print(f"PROBE {kind} W={week}: score_rows={len(rows)} "
              f"has_scores={any(isinstance(x,dict) and 'score' in x for x in rows)} "
              f"has_players={any(isinstance(x,dict) and 'id' in x for x in rows)}")
    elif kind == "nflSchedule":
        games = _as_list(root.get("game") or root.get("matchup"))
        first = games[0] if games and isinstance(games[0], dict) else {}
        teams = _as_list(first.get("team"))
        print(f"PROBE nflSchedule: game_fields={','.join(k for k in ('kickoff','team','id','date','time') if k in first)} "
              f"team_fields={','.join(k for k in ('id','isHome','score') if teams and isinstance(teams[0], dict) and k in teams[0])} "
              f"team_count={len(teams)}")
        print(f"PROBE {kind} W={week}: schedule_rows={len(games)}")
    elif kind == "league":
        starters = root.get("starters")
        print(f"PROBE league: starters_type={type(starters).__name__} "
              f"starter_fields={','.join(k for k in ('position','count','minimum','maximum','min','max','value') if isinstance(starters,dict) and k in starters)}")
        if isinstance(starters, dict):
            pos = _as_list(starters.get("position") or starters.get("starter"))
            first_pos = pos[0] if pos and isinstance(pos[0],dict) else {}
            print(f"PROBE league: position_rows={len(pos)} "
                  f"position_field_names={','.join(k for k in ('name','id','min','max','minimum','maximum','value') if k in first_pos)}")
        print(f"PROBE league: starter_rules_present={starters is not None} "
              f"roster_size_present={'rosterSize' in root} " 
              f"current_week_present={'currentWeek' in root}")



def _probe_starting_lineups_site(year, league_id):
    """Inspect public MFL report navigation and HTML without logging names/IDs."""
    import re
    from html import unescape
    from urllib.parse import urlsplit, parse_qs
    base = f"https://www.myfantasyleague.com/{year}"
    pages = (
        ("home", f"{base}/home/{league_id}"),
        ("submit", f"{base}/options?L={league_id}&O=02&W=12"),
        ("report05", f"{base}/options?L={league_id}&O=05&W=12"),
        ("report06", f"{base}/options?L={league_id}&O=06&W=12"),
    )
    for name,url in pages:
        req = urllib.request.Request(url,headers={
            "User-Agent":"Mozilla/5.0 (compatible; FantasyInjuryWatchBryce/1.0)",
            "Accept":"text/html",
        })
        try:
            with urllib.request.urlopen(req,timeout=18) as response:
                page=response.read(800_000).decode("utf-8","replace")
                print(f"WEB {name}: HTTP={response.status} final_host={urlsplit(response.url).hostname} "
                      f"html_size={len(page)}")
        except urllib.error.HTTPError as e:
            print(f"WEB {name}: HTTP={e.code}")
            continue
        except (OSError, urllib.error.URLError, TimeoutError):
            print(f"WEB {name}: network_error")
            continue
        normalized=re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.I|re.S)
        normalized=re.sub(r"<style\b[^>]*>.*?</style>", " ", normalized, flags=re.I|re.S)
        login=bool(re.search(r"please log ?in|login required|log ?in to",normalized,re.I))
        markers = {
            "starting_lineups":bool(re.search(r"Starting Lineups",normalized,re.I)),
            "submit_lineups":bool(re.search(r"Submit Lineup",normalized,re.I)),
            "franchise":bool(re.search(r"franchise",normalized,re.I)),
            "week12":bool(re.search(r"Week 12",normalized,re.I)),
            "login_required":login,
        }
        print(f"WEB {name}: markers={markers}")
        links=[]
        for match in re.finditer(r'<a\b[^>]*href\s*=\s*(["\'])(.*?)\1[^>]*>(.*?)</a>',
                                 normalized,re.I|re.S):
            label=re.sub(r'<[^>]*>', ' ', match.group(3))
            if not re.search(r'starting lineups|submit lineups|weekly results',unescape(label),re.I):
                continue
            parsed=urlsplit(unescape(match.group(2)))
            query=parse_qs(parsed.query)
            opts={k: query[k][0] for k in ("O","R") if k in query}
            links.append((unescape(label).strip()[:36],parsed.path.split("/")[-1],opts))
            if len(links)>=10:
                break
        print(f"WEB {name}: report_link_formats={links}")

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
    _probe_starting_lineups_site(int(season), league_id)
    print("PROBE COMPLETE: no lineup data, names, tokens or URLs were logged or published.")


if __name__ == "__main__":
    run()
