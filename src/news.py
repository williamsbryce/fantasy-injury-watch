"""Optional public RSS injury/practice headlines matched to MFL roster players.

MFL's own article page is available as a link, but its content requires a
logged-in MFL session for this league. Never invent a news headline.
"""
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlsplit

FEED_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"
NEWS_TERMS = re.compile(
    r"\b(?:practice|practiced|practicing|limited|dnp|questionable|doubtful|"
    r"injury|injured|injuries|hamstring|ankle|knee|concussion|shoulder|"
    r"illness|sidelined|sits|sitting|misses|missed|ruled out|"
    r"game.time decision|returning to action|not expected to play|"
    r"won.t play|out for week|inactive|cleared)\b",
    re.I,
)
SUFFIX = re.compile(r"\s+(?:jr\.?|sr\.?|ii|iii|iv)$", re.I)


def _plain(value):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def _safe_link(value):
    parts = urlsplit((value or "").strip())
    if parts.scheme != "https" or (parts.hostname or "").lower() not in {
        "www.rotowire.com", "rotowire.com",
    } or parts.username or parts.password:
        return ""
    return parts.geturl()


def fetch_recent_news():
    """Return latest headline metadata, or None if the optional feed is unavailable."""
    req = urllib.request.Request(FEED_URL, method="GET", headers={
        "User-Agent": "FantasyInjuryWatchBryce/1.0",
        "Accept": "application/rss+xml, application/xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            xml = response.read(500_000)
        root = ET.fromstring(xml)
        items = root.findall(".//item")
        if not items:
            raise ValueError("Feed contained no items")
    except (urllib.error.URLError, OSError, ValueError, ET.ParseError):
        print("Optional RotoWire public RSS feed unavailable; injury designations unaffected.")
        return None
    result = []
    for item in items[:60]:
        title = _plain(item.findtext("title"))[:180]
        link = _safe_link(item.findtext("link"))
        description = _plain(item.findtext("description"))[:550]
        if not (title and link and NEWS_TERMS.search(title + " " + description)):
            continue
        result.append({
            "title": title,
            "description": description,
            "published": _plain(item.findtext("pubDate"))[:80],
            "url": link,
            "source": "RotoWire RSS",
        })
    return result


def _matches_player(title, name):
    # Headlines are generally "Player Name: ..." so this match excludes
    # other players appearing only as incidental mentions in descriptions.
    name = SUFFIX.sub("", (name or "").strip()).casefold()
    title = (title or "").casefold()
    return bool(name and (title.startswith(name + ":") or title.startswith(name + " —")
                          or title.startswith(name + " -")))


def enrich_reports(leagues, news_items=None, checked_at=None):
    """Attach at most one latest relevant article to each injury card."""
    checked_at = checked_at or datetime.now(timezone.utc)
    for league in leagues:
        league["news_source"] = "RotoWire RSS" if news_items is not None else "unavailable"
        league["news_checked_at"] = checked_at.isoformat()
        for alert in league.get("alerts", []):
            alert["news"] = []
            if news_items is None:
                continue
            matching = [n for n in news_items if _matches_player(n["title"], alert["name"])]
            if matching:
                # RSS is newest first; avoid clutter. Headlines link to publisher.
                alert["news"] = [{k: matching[0][k] for k in (
                    "title", "published", "url", "source"
                )}]
    return leagues
