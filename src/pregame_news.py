"""Independent Sunday pregame news signals for verified fantasy starters.

Only a recent, explicit player-specific OUT statement qualifies. A RotoWire
report is visibly attributed, never mislabeled as an official NFL inactive
transaction. NFL.com official weekly inactive lists retain precedence.
"""
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import news as rotowire
from .lineup_monitor import ALIASES

SK = ZoneInfo("America/Regina")
MONTH_FORMAT = "%B %d, %Y"
OUT = re.compile(
    r"\b(?:ruled out|inactive|won['’]?t play|will not play|"
    r"not playing(?: on)? sunday|won['’]?t suit up|not suiting up|"
    r"out for sunday|out for week\s*\d+|out for the (?:game|contest)|"
    r"will miss (?:sunday|week\s*\d+)|set to miss (?:sunday|week\s*\d+))\b",
    re.I,
)
# "not expected to play" and "unlikely to suit up" are predictions, not
# confirmed decisions. Avoid alerts on those phrases.
FALSE_POSITIVE = re.compile(
    r"\b(?:not ruled out|questionable to return|"
    r"out for the remainder|out for rest of|could be ruled out|"
    r"if ruled out|was ruled out|previously ruled out)\b", re.I,
)
MAX_AGE_DAYS = 2
NEWS_WINDOW = timedelta(hours=5)


def explicit_out(text):
    return bool(OUT.search(str(text or "")) and
                not FALSE_POSITIVE.search(str(text or "")))


def article_date(value):
    value = str(value or "").strip()
    for fmt in (MONTH_FORMAT, "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.date() if dt.tzinfo is None else dt.astimezone(SK).date()
        except ValueError:
            pass
    return None


def fresh_on_sunday(value, now):
    pub = article_date(value)
    if pub is None:
        return False
    days = (now.astimezone(SK).date() - pub).days
    return 0 <= days <= MAX_AGE_DAYS


def candidates(players, now):
    """Only verified MFL starters with imminent, not-yet-resolved games."""
    out = []
    for p in players:
        if p.get("lineup_role") != "starter" or p.get("state") != "pending":
            continue
        try:
            kickoff = datetime.fromisoformat(str(p["kickoff"]))
        except (ValueError, KeyError, TypeError):
            continue
        if kickoff.tzinfo and timedelta(minutes=10) < kickoff - now <= NEWS_WINDOW:
            out.append(p)
    return out


class NFLPregameParser(HTMLParser):
    """Collect just article title and bullet text, not unrelated website links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.head = ""
        self.heading = False
        self.bullet = 0
        self.parts = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.heading = True
        if tag == "li":
            self.bullet += 1
            if self.bullet == 1:
                self.parts = []

    def handle_data(self, data):
        if self.heading:
            self.head += data
        if self.bullet:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.heading = False
        if tag == "li" and self.bullet:
            self.bullet -= 1
            if self.bullet == 0:
                self.items.append(" ".join(" ".join(self.parts).split()))
                self.parts = []


def nfl_pregame_url(season, week):
    return (f"https://www.nfl.com/news/week-{int(week)}-injuries-"
            f"sunday-pregame-{int(season)}-nfl-season")


def _match_nfl_bullet(text, name):
    # Require the player name, not an incidentally mentioned surname.
    stripped = re.sub(r"\s+(?:Jr\.?|Sr\.?|II|III|IV)$", "", name.strip(), flags=re.I)
    expression = r"(?<![A-Za-z])" + re.escape(stripped) + r"(?![A-Za-z])"
    return bool(re.search(expression, text, re.I))


def parse_nfl_pregame(html, week, players):
    parser = NFLPregameParser()
    parser.feed(html[:3_000_000])
    title = " ".join(parser.head.lower().split())
    if not re.search(r"\bweek\s+" + re.escape(str(week)) + r"\b", title):
        return {}
    if "injur" not in title or "sunday" not in title:
        return {}
    result = {}
    for p in players:
        for item in parser.items:
            if _match_nfl_bullet(item, p["name"]) and explicit_out(item):
                result[str(p["player_id"])] = {
                    "source": "NFL.com pregame report",
                    "headline": item[:190],
                    "url": "",  # filled with validated known URL by caller
                    "published": "",
                }
                break
    return result


def fetch_nfl_pregame(season, week, players):
    url = nfl_pregame_url(season, week)
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": "Mozilla/5.0 (compatible; BAWInjuryWatch/1.0)",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.geturl().rstrip("/") != url:
                return {}
            page = response.read(3_000_000).decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError, TimeoutError):
        return {}
    found = parse_nfl_pregame(page, week, players)
    for item in found.values():
        item["url"] = url
    return found


def _rotowire_out_for_team(team, players, now):
    page = rotowire.PAGE_URL + "?team=" + team
    updates = rotowire._fetch_news_page(page)
    found = {}
    for p in players:
        # Team pages are newest first. The most recent player headline
        # supersedes a prior "out" headline, including an active/cleared update.
        matching = [entry for entry in updates
                    if rotowire._matches_player(entry.get("title", ""), p["name"])]
        if not matching:
            continue
        newest = matching[0]
        if not fresh_on_sunday(newest.get("published"), now):
            continue
        title = newest.get("title", "").split(":", 1)[-1]
        if not explicit_out(title):
            continue
        url = newest.get("url", "")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in {"www.rotowire.com", "rotowire.com"}:
            continue
        found[str(p["player_id"])] = {
            "source": "RotoWire",
            "headline": newest["title"][:180],
            "published": newest.get("published", ""),
            "url": url,
        }
    return found


def fetch_pregame_reports(players, season, week, now):
    """Compare independent NFL and RotoWire sources for current starters."""
    pool = candidates(players, now)
    if not pool:
        return {}
    # NFL pregame roundup is checked first. RotoWire also covers IDP and
    # team-specific news that the roundup may omit.
    found = fetch_nfl_pregame(season, week, pool)
    teams = {}
    for p in pool:
        if str(p["player_id"]) in found:
            continue
        team = ALIASES.get(p["nfl_team"], p["nfl_team"])
        if re.fullmatch(r"[A-Z]{2,3}", team):
            teams.setdefault(team, []).append(p)
    for team, grouped in list(teams.items())[:16]:
        for pid, report in _rotowire_out_for_team(team, grouped, now).items():
            found.setdefault(pid, report)
    return found
