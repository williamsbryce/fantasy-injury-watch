"""Independent official NFL game-day active/inactive checker.

Official NFL.com inactive lists are compared with the MFL *roster*, not
the MFL injury feed. A confirmed team list may establish a player was
eligible to suit up, never that the player actually played a snap.

The workflow persists a fixed notification batch before contacting Resend.
Do not use this module to POST an MFL lineup.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from .lineup_monitor import (
    current_week_context, fetch_weekly_lineup, submitted_starter_ids, _list,
    ALIASES, EXPECTED_STARTERS,
)
from .mfl import export, MFLAPIError
from .model import friendly_name
from .notify import send_resend
from .audit_log import record_event, AuditError

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "site/data/report.json"
GAME_DAY_PATH = ROOT / "site/data/game-day.json"
REGINA = ZoneInfo("America/Regina")
TEAM_NAMES = {
    "ARI": "CARDINALS", "ATL": "FALCONS", "BAL": "RAVENS",
    "BUF": "BILLS", "CAR": "PANTHERS", "CHI": "BEARS",
    "CIN": "BENGALS", "CLE": "BROWNS", "DAL": "COWBOYS",
    "DEN": "BRONCOS", "DET": "LIONS", "GB": "PACKERS",
    "HOU": "TEXANS", "IND": "COLTS", "JAX": "JAGUARS",
    "KC": "CHIEFS", "LAC": "CHARGERS", "LAR": "RAMS",
    "LV": "RAIDERS", "MIA": "DOLPHINS", "MIN": "VIKINGS",
    "NE": "PATRIOTS", "NO": "SAINTS", "NYG": "GIANTS",
    "NYJ": "JETS", "PHI": "EAGLES", "PIT": "STEELERS",
    "SEA": "SEAHAWKS", "SF": "49ERS", "TB": "BUCCANEERS",
    "TEN": "TITANS", "WSH": "COMMANDERS",
}
NAME_TO_ABBR = {v: k for k, v in TEAM_NAMES.items()}
SKIP_PREFIX = re.compile(r"^(?:QB|RB|WR|TE|OL|OT|T|G|C|DL|DE|DT|LB|MLB|OLB|CB|DB|S|FS|SS|K|P|LS)\s+", re.I)
NORMALIZE = re.compile(r"[^a-z0-9 ]")
SUFFIX = re.compile(r"\s+(?:jr|sr|ii|iii|iv)$", re.I)


def _name(value):
    value = SKIP_PREFIX.sub("", str(value or "").split("(")[0].strip())
    value = NORMALIZE.sub("", value.lower().replace("’", "'").replace("-", " "))
    value = re.sub(r"\s+", " ", value).strip()
    return SUFFIX.sub("", value)


class _InactivesHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.block = None
        self.buffer = []
        self.current_team = None
        self.lists = {abbr: [] for abbr in TEAM_NAMES}
        self.header = ""
        self.page_text = []
        self.stopped = False

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "li"):
            if self.block is None:
                self.block = tag
                self.buffer = []

    def handle_data(self, data):
        if not self.stopped and self.block is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if self.stopped or tag != self.block:
            return
        text = " ".join(" ".join(self.buffer).split()).strip()
        self.buffer = []
        self.block = None
        if tag == "h1":
            self.header = text
        elif tag == "h2" and ("related content" in text.lower() or
                                "latest news" in text.lower()):
            self.current_team = None
            self.stopped = True
        elif tag == "h3":
            upper = text.upper().strip()
            self.current_team = NAME_TO_ABBR.get(upper)
        elif tag == "li" and self.current_team and text:
            text = re.sub(r"\s*\(emergency third qb\)\s*", "", text, flags=re.I)
            cleaned = SKIP_PREFIX.sub("", text).strip()
            if 2 <= len(cleaned) <= 65 and _name(cleaned):
                self.lists[self.current_team].append(cleaned)


def parse_nfl_inactives(html, season, week):
    """Strictly require the correct official week and complete team lists.

    A missing/incomplete team list is unknown, never a green active status.
    """
    if not isinstance(html, str) or len(html) < 1000:
        return {}
    parser = _InactivesHTML()
    parser.feed(html[:4_000_000])
    head = parser.header.lower()
    if not re.search(r"week\s+" + re.escape(str(week)) + r"\b", head):
        return {}
    if "inactive" not in head:
        return {}
    # The article slug/year is independently validated by the caller.
    valid = {}
    for team, names in parser.lists.items():
        unique = set(_name(n) for n in names)
        if 4 <= len(unique) <= 9:
            valid[team] = names
    return valid


def official_sunday_url(season, week):
    return (
        f"https://www.nfl.com/news/nfl-week-{int(week)}-inactives-"
        f"players-ruled-out-sunday-{int(season)}-season"
    )


def fetch_official_lists(season, week):
    """Read one NFL.com URL, without scraping unverified search snippets."""
    url = official_sunday_url(season, week)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BAWInjuryWatch/1.0)",
        "Accept": "text/html",
    }, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            if response.geturl().split("?")[0].rstrip("/") != url:
                return {}, url
            page = response.read(4_000_000).decode("utf-8", "replace")
        return parse_nfl_inactives(page, season, week), url
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            OSError, ValueError, UnicodeError):
        return {}, url


def roster_from_mfl(year, league_id, franchise_id, api_key, week):
    """Read current active roster and verify all 17 starters, without injuries."""
    feeds = {}
    try:
        feeds["rosters"] = export(year, "rosters", league_id, api_key)
        feeds["players"] = export(year, "players", league_id, api_key)
    except MFLAPIError:
        return None
    f = _list((feeds["rosters"].get("rosters") or {}).get("franchise"))
    franchise = [x for x in f if isinstance(x, dict) and
                 str(x.get("id", "")).zfill(4) == str(franchise_id).zfill(4)]
    if len(franchise) != 1:
        return None
    active = [
        p for p in _list(franchise[0].get("player"))
        if isinstance(p, dict) and
        str(p.get("status", "")).upper() not in {
            "IR", "INJURED_RESERVE", "TAXI", "TAXI_SQUAD",
        }
    ]
    lookup = {
        str(p["id"]): p for p in _list((feeds["players"].get("players") or {}).get("player"))
        if isinstance(p, dict) and p.get("id") is not None
    }
    if not active or any(str(p.get("id")) not in lookup for p in active):
        return None
    current = fetch_weekly_lineup(year, league_id, api_key, week)
    selected = submitted_starter_ids(current or {}, franchise_id)
    roster_ids = {str(p["id"]) for p in active}
    confirmed = (
        selected is not None and len(selected) == EXPECTED_STARTERS
        and set(selected).issubset(roster_ids)
    )
    starter_set = set(selected) if confirmed else set()
    players = []
    for entry in active:
        pid = str(entry["id"])
        details = lookup[pid]
        raw_team = str(details.get("team", "")).upper()
        team = ALIASES.get(raw_team, raw_team)
        if team not in TEAM_NAMES:
            continue
        players.append({
            "player_id": pid, "name": friendly_name(details.get("name", "")),
            "position": str(details.get("position", "")),
            "nfl_team": team,
            "lineup_role": (
                "starter" if pid in starter_set else "bench"
            ) if confirmed else "unknown",
        })
    return players if len(players) >= 15 else None


def cached_players(doc, year, week):
    """Conservative fallback: only alert players from the verified MFL injury report."""
    out = []
    for league in doc.get("leagues", []):
        lineup = league.get("lineup") or {}
        confirmed = lineup.get("state") == "submitted" and lineup.get("week") == week
        for a in league.get("alerts", []):
            raw_team = str(a.get("nfl_team", "")).upper()
            team = ALIASES.get(raw_team, raw_team)
            if team not in TEAM_NAMES:
                continue
            out.append({
                "player_id": str(a.get("player_id")),
                "name": str(a.get("name")),
                "position": str(a.get("position", "")),
                "nfl_team": team,
                "lineup_role": (a.get("lineup_role") or "unknown") if confirmed else "unknown",
            })
    return out


def classify_player(player, today_games, inactive_lists):
    team = player["nfl_team"]
    games = [g for g in today_games if team in g["teams"]]
    if len(games) != 1:
        return {"state": "no_game", "kickoff": None}
    game = games[0]
    kickoff = game["kickoff"]
    if team not in inactive_lists:
        return {"state": "pending", "kickoff": kickoff.isoformat()}
    normalized = _name(player["name"])
    matches = [n for n in inactive_lists[team] if _name(n) == normalized]
    return {"state": "inactive" if matches else "eligible",
            "kickoff": kickoff.isoformat()}


def prepare(now=None, *, context=None, official=None, roster=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise RuntimeError("Game-day check requires a timezone")
    season = int(os.environ.get("MFL_SEASON", "2026"))
    league_id = str(os.environ.get("MFL_LEAGUE_ID", "")).strip()
    franchise_id = str(os.environ.get("MFL_FRANCHISE_ID", "")).strip()
    if not league_id.isdigit() or not franchise_id.isdigit():
        raise RuntimeError("Game-day league configuration missing")
    doc = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if not doc.get("leagues"):
        raise RuntimeError("Verified roster report not available")
    context = context if context is not None else current_week_context(season, now)
    if not context or not isinstance(context.get("week"), int):
        raise RuntimeError("NFL game schedule/season could not be verified")
    week = context["week"]
    date = now.astimezone(REGINA).date().isoformat()
    today_games = [g for g in context["games"]
                   if g["kickoff"].astimezone(REGINA).date().isoformat() == date
                   and g["kickoff"].astimezone(REGINA).weekday() == 6]
    if not today_games:
        print("GAME DAY: no Sunday NFL games scheduled today")
        return False
    official, url = official if official is not None else fetch_official_lists(season, week)
    current = roster
    if current is None and os.environ.get("MFL_API_KEY"):
        current = roster_from_mfl(season, league_id, franchise_id,
                                  os.environ["MFL_API_KEY"], week)
    if current is None:
        current = cached_players(doc, season, week)
        print("GAME DAY: full MFL roster unavailable; only cached injury players checked")
    if not current:
        raise RuntimeError("No trustworthy roster identities available for NFL check")
    injured = {
        str(a.get("player_id")) for league in doc["leagues"]
        for a in league.get("alerts", [])
    }
    player_rows = []
    for player in current:
        if player["nfl_team"] not in TEAM_NAMES:
            continue
        status = classify_player(player, today_games, official)
        if status["state"] == "no_game":
            continue
        player_rows.append({
            **player, **status,
            "injury_watch": player["player_id"] in injured
        })
    previous = {}
    if GAME_DAY_PATH.exists():
        previous = json.loads(GAME_DAY_PATH.read_text(encoding="utf-8"))
    if previous and (previous.get("date") != date or previous.get("week") != week):
        previous = {}
    previous_roles = {
        a["player_id"]: a for a in previous.get("players", [])
        if isinstance(a, dict) and a.get("player_id")
    }
    notified = previous.get("notified_keys", [])
    queue = []
    for p in player_rows:
        if p["state"] not in ("inactive", "eligible"):
            continue
        relevant = p["lineup_role"] == "starter" or p["injury_watch"]
        if not relevant:
            continue
        key = f"{date}-{p['player_id']}-{p['state']}"
        if key not in notified and previous_roles.get(p["player_id"], {}).get("state") != p["state"]:
            queue.append({
                "key": key, "name": p["name"], "position": p["position"],
                "nfl_team": p["nfl_team"], "state": p["state"],
                "lineup_role": p["lineup_role"], "kickoff": p["kickoff"],
            })
    pending = previous.get("pending_batch")
    if pending:
        # Never mutate an outgoing batch while a Resend retry is unresolved.
        queue = list(pending.get("items", [])) + [
            p for p in queue if p["key"] not in {i["key"] for i in pending["items"]}
        ]
        pending = previous["pending_batch"]
    elif queue:
        items = sorted(queue, key=lambda p: (p["lineup_role"] != "starter", p["name"]))
        summary = []
        for p in items:
            flag = "INACTIVE" if p["state"] == "inactive" else "ELIGIBLE (NOT INACTIVE)"
            role = p["lineup_role"].upper()
            summary.append(f"{p['name']} ({p['position']}, {p['nfl_team']}) - {flag} | {role}")
        body = (
            f"Official NFL Sunday game-day availability | {date}\n\n"
            + "\n".join(summary)
            + "\n\nEligible means not named on the confirmed NFL inactive list. "
              "It does NOT prove the player took a snap.\n"
              f"Official NFL inactives: {url}\n"
              "Injury Watch: https://williamsbryce.github.io/fantasy-injury-watch/"
        )
        html = (
            '<!doctype html><html><body style="font-family:Arial,sans-serif;'
            'color:#182435;line-height:1.5;max-width:600px;padding:16px">'
            '<h2 style="background:#182435;color:white;padding:17px">'
            "BAWs Fantasy Injury Watch · Game day</h2>"
            '<p>New official NFL player availability confirmations:</p>'
            '<ul>' + "".join(
                '<li style="margin:10px 0"><strong>' +
                __import__("html").escape(p["name"]) + '</strong> · ' +
                ('Inactive' if p["state"] == "inactive" else 'Eligible to play') +
                ' · ' + __import__("html").escape(p["lineup_role"].title())
                + '</li>' for p in items
            ) + '</ul>'
            '<p>Eligible means not listed as inactive, not proof of playing snaps.</p>'
            f'<p><a href="{url}">Official NFL inactive list</a> · '
            '<a href="https://williamsbryce.github.io/fantasy-injury-watch/">'
            'Open Injury Watch</a></p></body></html>'
        )
        fingerprint = hashlib.sha256(
            "|".join(p["key"] for p in items).encode("utf-8")
        ).hexdigest()[:24]
        pending = {"items": items, "text": body, "html": html,
                   "idempotency_key": "baw-gameday-" + fingerprint}
    state = {
        "schema": 1, "season": season, "week": week, "date": date,
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "source": url, "confirmed_teams": sorted(official.keys()),
        "players": player_rows,
        "pending_batch": pending, "notified_keys": notified[-200:],
        "last_accepted": previous.get("last_accepted"),
    }
    GAME_DAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    GAME_DAY_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("GAME DAY: official teams confirmed", len(official),
          "roster players", len(player_rows),
          "eligible", sum(p["state"] == "eligible" for p in player_rows),
          "inactive", sum(p["state"] == "inactive" for p in player_rows),
          "pending", sum(p["state"] == "pending" for p in player_rows),
          "email batch prepared", bool(pending))
    return True


def send():
    if not GAME_DAY_PATH.exists():
        return False
    state = json.loads(GAME_DAY_PATH.read_text(encoding="utf-8"))
    batch = state.get("pending_batch")
    if not batch:
        print("GAME DAY: no new official statuses to email")
        return False
    for variable in ("RESEND_API_KEY", "ALERT_FROM", "ALERT_TO"):
        if not os.environ.get(variable):
            raise RuntimeError("Game-day email configuration unavailable")
    if not send_resend(
        os.environ["RESEND_API_KEY"], os.environ["ALERT_FROM"],
        os.environ["ALERT_TO"], "BAWs Fantasy Injury Watch | Game-day status",
        batch["text"], html_body=batch["html"],
        idempotency_key=batch["idempotency_key"],
    ):
        raise RuntimeError("Game-day status email not accepted")
    state["notified_keys"] = (
        state.get("notified_keys", []) + [x["key"] for x in batch["items"]]
    )[-200:]
    state["last_accepted"] = {
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "count": len(batch["items"]),
        "date": state["date"],
    }
    state["pending_batch"] = None
    GAME_DAY_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("GAME DAY: Resend accepted update for", len(batch["items"]),
          "players; inbox delivery not independently verified")
    return True


def audit():
    state = json.loads(GAME_DAY_PATH.read_text(encoding="utf-8"))
    last = state.get("last_accepted") or {}
    if last.get("run_id") != os.environ.get("GITHUB_RUN_ID", "") or not last.get("count"):
        return
    try:
        record_event(
            "email", "success", "NFL game-day status email accepted",
            f"Resend accepted official NFL game-day updates for {last['count']} players.",
            key="nfl-gameday",
        )
    except AuditError as exc:
        print("GAME DAY: accepted email; event log failed:", str(exc))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "send", "audit"}:
        raise SystemExit("Usage: python -m src.nfl_game_day prepare|send|audit")
    {"prepare": prepare, "send": send, "audit": audit}[sys.argv[1]]()


if __name__ == "__main__":
    main()
