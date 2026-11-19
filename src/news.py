"""Optional public injury/practice headlines matched to MFL roster players.

MFL's own article page is available as a link, but its content requires a
logged-in MFL session for this league. Never invent a news headline.
"""
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlsplit, urljoin

FEED_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"
PAGE_URL = "https://www.rotowire.com/football/news.php"
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


def _extract_anchor(fragment, class_name):
    match = re.search(
        r'<a\b[^>]*\bclass\s*=\s*"[^"]*\b' +
        re.escape(class_name) +
        r'\b[^"]*"[^>]*>.*?</a>',
        fragment, re.I | re.S,
    )
    if not match:
        return "", ""
    tag = match.group(0)
    href_match = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', tag, re.I | re.S)
    href = unescape(href_match.group(2)) if href_match else ""
    label = _plain(tag[tag.find(">") + 1:tag.lower().rfind("</a>")])
    return label, _safe_link(urljoin(PAGE_URL, href))


def _parse_news_page(html):
    """Parse the publicly visible RotoWire updates; return headline metadata only."""
    starts = list(re.finditer(
        r'<div\s+class\s*=\s*"news-update(?:\s+[^"]*)?"[^>]*>',
        html, re.I,
    ))
    articles = []
    for i, start in enumerate(starts[:100]):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(html)
        block = html[start.end():end]
        name, _ = _extract_anchor(block, "news-update__player-link")
        headline, link = _extract_anchor(block, "news-update__headline")
        if not (name and headline and link):
            continue
        # RotoWire marks updates about injured players explicitly.
        is_injured = "is-injured" in start.group(0).lower()
        if not is_injured and not NEWS_TERMS.search(headline):
            continue
        date = re.search(
            r'<div\s+class\s*=\s*"news-update__timestamp"[^>]*>(.*?)</div>',
            block, re.I | re.S,
        )
        articles.append({
            "title": f"{name}: {headline}"[:180],
            "published": _plain(date.group(1))[:80] if date else "",
            "url": link,
            "source": "RotoWire",
        })
    return articles


def _fetch_news_page(url=PAGE_URL):
    """The public page lists more player updates than the five-item RSS feed."""
    request = urllib.request.Request(url, method="GET", headers={
        "User-Agent": "Mozilla/5.0 (compatible; FantasyInjuryWatchBryce/1.0)",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            html = response.read(1_000_000).decode("utf-8", "replace")
        return _parse_news_page(html)
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _fetch_rss():
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
        print("Optional public player news feed unavailable; MFL injury designations unaffected.")
        return None
    result = []
    for item in items[:60]:
        title = _plain(item.findtext("title"))[:180]
        link = _safe_link(item.findtext("link"))
        description = _plain(item.findtext("description"))[:550]
        if not (title and link and NEWS_TERMS.search(title + " " + description)):
            continue
        if not NEWS_TERMS.search(title) and re.search(
                r"\bno (?:injury|injuries|health concern)\b", description, re.I):
            continue
        result.append({
            "title": title,
            "published": _plain(item.findtext("pubDate"))[:80],
            "url": link,
            "source": "RotoWire RSS",
        })
    return result


TEAM_ALIASES = {
    "ARZ": "ARI", "GBP": "GB", "KCC": "KC", "NEP": "NE",
    "NOS": "NO", "SFO": "SF", "TBB": "TB", "JAC": "JAX",
    "WAS": "WSH", "LVR": "LV", "RAM": "LAR",
}


def fetch_recent_news(alerts=None):
    """Use public league-wide news plus targeted team pages for missed players.

    The generic page is newest-first but only contains a subset of the NFL.
    MFL often republishes RotoWire titles from deeper team-specific pages.
    Never guess a title from the injured player's designation.
    """
    global_items = _fetch_news_page()
    if not global_items:
        global_items = _fetch_rss() or []
    items = list(global_items)
    if not alerts:
        return items or None
    missing = [a for a in alerts if isinstance(a, dict) and
               not any(_matches_player(n["title"], a.get("name", ""))
                       for n in items)]
    teams = []
    for alert in missing:
        raw = str(alert.get("nfl_team") or "").upper().strip()
        team = TEAM_ALIASES.get(raw, raw)
        if re.fullmatch(r"[A-Z]{2,3}", team) and team not in teams:
            teams.append(team)
    for team in teams[:10]:
        page = _fetch_news_page(PAGE_URL + "?team=" + team)
        for article in page:
            if not any(article["title"] == n["title"] for n in items):
                items.append(article)
    return items or None


def _matches_player(title, name):
    # Never match a name mentioned only as an incidental reference in another
    # player's article. Both HTML and RSS title formats start "Player: ...".
    title_name = (title or "").split(":", 1)[0].strip()
    normalized_name = SUFFIX.sub("", (name or "").strip()).casefold()
    normalized_title = SUFFIX.sub("", title_name).casefold()
    return bool(":" in (title or "") and normalized_name and
                normalized_name == normalized_title)


def enrich_reports(leagues, news_items=None, checked_at=None):
    """Attach at most one latest relevant article to each injury card."""
    checked_at = checked_at or datetime.now(timezone.utc)
    for league in leagues:
        league["news_source"] = "RotoWire" if news_items is not None else "unavailable"
        league["news_checked_at"] = checked_at.isoformat()
        for alert in league.get("alerts", []):
            alert["news"] = []
            if news_items is None:
                continue
            matching = [n for n in news_items if _matches_player(n["title"], alert["name"])]
            if matching:
                # Feed is newest first. Show one headline, dated and linked.
                alert["news"] = [{k: matching[0][k] for k in (
                    "title", "published", "url", "source"
                )}]
    return leagues
