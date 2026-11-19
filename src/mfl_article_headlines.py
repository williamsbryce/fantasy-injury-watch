"""Read-only authenticated MFL news headline lookup for existing injured players.

MFL's own player-news pages can contain articles not present in the limited
public RotoWire feed. Publish only the first explicitly player-matched title,
never story bodies, account cookies, session identifiers, or credentials.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

REPORT_PATH = Path(__file__).resolve().parent.parent / "site" / "data" / "report.json"
LEAGUE_HOST = "www46.myfantasyleague.com"


class MFLNewsError(ValueError):
    pass


class _ArticleLinks(HTMLParser):
    """Collect anchor *titles only*, ignoring tables, source summaries and scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchor = None
        self.suppressed = 0
        self.all_text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        if tag == "a" and not self.suppressed:
            self.anchor = []
    def handle_data(self, data):
        if self.suppressed:
            return
        if self.anchor is not None:
            self.anchor.append(data)
        if len(self.all_text) < 2400:
            self.all_text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            title = " ".join(" ".join(self.anchor).split())
            if title:
                self.links.append(title)
            self.anchor = None
        if tag in ("script", "style") and self.suppressed:
            self.suppressed -= 1


def find_headline(html, player_name):
    """Return exactly one player-matched MFL headline, or None.

    MFL articles in the selected-player page are newest first. A position
    abbreviation such as 'S' may precede the player's name, e.g.
    'S Brandon Jones: Still working through hamstring issue'.
    """
    if not isinstance(html, str) or not isinstance(player_name, str):
        return None
    parser = _ArticleLinks()
    parser.feed(html[:1_000_000])
    page = " ".join(parser.all_text).lower()
    if "search results" not in page or "article" not in page:
        return None
    name = re.escape(player_name.strip())
    if not name:
        return None
    # Exact player identity before the colon avoids false matches when a
    # player is merely mentioned in someone else's story or summary.
    pattern = re.compile(r"^(?:(?:[A-Z]{1,3}|D/ST)\\s+)?" + name +
                         r"\\s*:\\s*(.{8,160})$", re.I)
    for title in parser.links[:100]:
        m = pattern.fullmatch(title)
        if m and not re.search(r"[<>\\r\\n]", m.group(1)):
            return title[:190]
    return None


class _RestrictRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in
                {"api.myfantasyleague.com", LEAGUE_HOST}):
            raise MFLNewsError("MFL news redirected to an unexpected host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _session(opener, year, league_id, username, password):
    form = urllib.parse.urlencode({
        "USERNAME": username, "PASSWORD": password,
        "LEAGUE_ID": league_id, "XML": "1",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.myfantasyleague.com/{year}/login",
        data=form, method="POST",
        headers={"Accept": "application/xml,text/xml",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "FantasyInjuryWatch/1.0"},
    )
    with opener.open(req, timeout=20) as resp:
        xml = resp.read(128_000)
        cookie_headers = resp.headers.get_all("Set-Cookie") or []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise MFLNewsError("MFL owner authentication response unreadable") from None
    if root.tag.lower() != "status":
        raise MFLNewsError("MFL owner authentication was not accepted")
    cookies = {}
    for header in cookie_headers:
        jar = SimpleCookie()
        try:
            jar.load(header)
        except Exception:
            continue
        for key in ("MFL_USER_ID", "MFL_PW_SEQ"):
            if key in jar:
                cookies[key] = jar[key].value
    for key in ("MFL_USER_ID", "MFL_PW_SEQ"):
        if key not in cookies and root.get(key):
            cookies[key] = root.get(key)
    if not cookies.get("MFL_USER_ID"):
        raise MFLNewsError("MFL owner session cookie missing")
    if any(re.search(r"[;\\r\\n\\s]", v) for v in cookies.values()):
        raise MFLNewsError("Unexpected MFL cookie format")
    return "; ".join(k + "=" + cookies[k] for k in ("MFL_USER_ID", "MFL_PW_SEQ")
                     if k in cookies)


def _player_html(opener, cookie, year, league_id, player_id):
    query = urllib.parse.urlencode({"L": league_id, "PLAYERS": player_id})
    url = f"https://{LEAGUE_HOST}/{year}/news_articles?{query}"
    request = urllib.request.Request(
        url, method="GET",
        headers={"Cookie": cookie, "Accept": "text/html",
                 "User-Agent": "FantasyInjuryWatch/1.0"},
    )
    with opener.open(request, timeout=20) as response:
        parsed = urlsplit(response.url)
        if (parsed.scheme != "https" or parsed.hostname != LEAGUE_HOST
                or not parsed.path.endswith("/news_articles")):
            raise MFLNewsError("MFL article page redirected unexpectedly")
        return response.read(850_000).decode("utf-8", "replace")


def enrich_mfl_headlines(document, fetch_html, checked_at=None):
    """Enrich cached alerts with verified titles; never change injury timestamps."""
    checked_at = checked_at or datetime.now(timezone.utc)
    attached = 0
    checked = 0
    for league in document.get("leagues", []):
        league_id = str(league.get("id", ""))
        for alert in league.get("alerts", [])[:25]:
            pid = str(alert.get("player_id", ""))
            if not (league_id.isdigit() and pid.isdigit()):
                continue
            checked += 1
            try:
                html = fetch_html(league_id, pid)
                headline = find_headline(html, alert.get("name", ""))
            except (MFLNewsError, ValueError, TypeError, urllib.error.URLError,
                    urllib.error.HTTPError, OSError, TimeoutError):
                continue
            if headline:
                alert["mfl_headline"] = {
                    "title": headline,
                    "source": "MFL player news",
                    "checked_at": checked_at.isoformat(),
                }
                attached += 1
            else:
                alert.pop("mfl_headline", None)
    return {"checked": checked, "matched": attached}


def run():
    username = os.environ.get("MFL_OWNER_USERNAME", "")
    password = os.environ.get("MFL_OWNER_PASSWORD", "")
    league_id = os.environ.get("MFL_LEAGUE_ID", "")
    franchise_id = os.environ.get("MFL_FRANCHISE_ID", "")
    year = int(os.environ.get("MFL_SEASON", "2026"))
    if not all((username, password, league_id, franchise_id)):
        print("MFL ARTICLE HEADLINES: owner session unavailable; current news links unchanged.")
        return
    if (not league_id.isdigit() or not franchise_id.isdigit() or
            not 2020 <= year <= 2100):
        raise MFLNewsError("Unexpected MFL article lookup configuration")
    if not REPORT_PATH.exists():
        raise MFLNewsError("No verified public report to enrich")
    document = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if not any(str(l.get("id")) == league_id and
               str(l.get("franchise_id", "")).zfill(4) == franchise_id.zfill(4)
               for l in document.get("leagues", []) if isinstance(l, dict)):
        raise MFLNewsError("Cached report league identity mismatch")
    try:
        opener = urllib.request.build_opener(_RestrictRedirects())
        cookie = _session(opener, year, league_id, username, password)
    except (MFLNewsError, urllib.error.HTTPError, urllib.error.URLError,
            OSError, TimeoutError, ValueError):
        print("MFL ARTICLE HEADLINES: login unavailable; existing news links preserved.")
        return
    def get_html(lid, pid):
        if lid != league_id:
            raise MFLNewsError("Unexpected player league")
        time.sleep(.3)
        return _player_html(opener, cookie, year, lid, pid)
    result = enrich_mfl_headlines(document, get_html)
    cookie = ""
    REPORT_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("MFL ARTICLE HEADLINES: articles checked=", result["checked"],
          "player headlines matched=", result["matched"],
          "; no summary bodies, passwords, cookies, lineup changes or emails saved.")


if __name__ == "__main__":
    run()
