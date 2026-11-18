"""In-memory MFL owner login and pregame Starting Lineups read-only probe.

Never prints response bodies, cookies, passwords, usernames, player IDs,
roster names, page URLs, or tokens. Never sends an MFL import/write request.
"""
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


class OwnerAuthError(RuntimeError):
    pass


class MFLOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = urlsplit(newurl)
        if new.scheme != "https" or not new.hostname or not (
            new.hostname == "api.myfantasyleague.com"
            or re.fullmatch(r"www\d+\.myfantasyleague\.com", new.hostname)
        ):
            raise OwnerAuthError("MFL response redirected outside expected HTTPS host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _make_opener():
    return urllib.request.build_opener(MFLOnlyRedirects())


def owner_login(opener, year, username, password, league_id):
    """POST credentials over HTTPS, return short-lived session cookie string."""
    if not username or not password:
        raise OwnerAuthError("MFL owner login secrets are missing")
    body = urlencode({
        "USERNAME": username,
        "PASSWORD": password,
        "LEAGUE_ID": league_id,
        "XML": "1",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.myfantasyleague.com/{int(year)}/login",
        data=body, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "FantasyInjuryWatchBryce/1.0",
            "Accept": "application/xml,text/xml",
        },
    )
    try:
        with opener.open(request, timeout=20) as result:
            xml = result.read(128_000)
            header_cookies = result.headers.get_all("Set-Cookie") or []
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
        raise OwnerAuthError("MFL owner login request failed (no private response logged)") from None

    cookies = {}
    for header in header_cookies:
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            continue
        for key in ("MFL_USER_ID", "MFL_PW_SEQ"):
            if key in parsed:
                cookies[key] = parsed[key].value
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise OwnerAuthError("MFL owner login did not return valid XML") from None
    if root.tag.lower() == "error":
        raise OwnerAuthError("MFL owner login rejected credentials or denied access")
    if root.tag.lower() != "status":
        raise OwnerAuthError("MFL owner login did not return a status")
    for key in ("MFL_USER_ID", "MFL_PW_SEQ"):
        if not cookies.get(key) and root.get(key):
            cookies[key] = root.get(key)
    token = cookies.get("MFL_USER_ID")
    if not token or any(c in token for c in "\r\n; "):
        raise OwnerAuthError("MFL owner login did not supply a valid session cookie")
    values = []
    for key in ("MFL_USER_ID", "MFL_PW_SEQ"):
        val = cookies.get(key)
        if val and not any(c in val for c in "\r\n; "):
            values.append(f"{key}={val}")
    return "; ".join(values)


class ReportStructure(HTMLParser):
    """Inspect markup shape only, never retain or print player data."""
    def __init__(self):
        super().__init__()
        self.tables = 0
        self.rows = 0
        self.cells = 0
        self.forms = 0
        self.password_inputs = 0
        self.linked_players = 0
        self.starting_lineups_text = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "table":
            self.tables += 1
        elif tag == "tr":
            self.rows += 1
        elif tag == "td":
            self.cells += 1
        elif tag == "form":
            self.forms += 1
        elif tag == "input" and values.get("type", "").lower() == "password":
            self.password_inputs += 1
        elif tag == "a":
            href = values.get("href") or ""
            if re.search(r"PLAYERS=|P=\d{3,}", href, re.I):
                self.linked_players += 1

    def handle_data(self, data):
        if "starting lineups" in data.lower():
            self.starting_lineups_text = True


def probe_owner_page(opener, year, league_id, franchise_id, week, session):
    """Retrieve owner-only MFL report without displaying or committing its contents."""
    params = urlencode({
        "L": league_id, "O": "06", "WEEK": week, "F": franchise_id,
    })
    request = urllib.request.Request(
        f"https://www46.myfantasyleague.com/{int(year)}/options?{params}",
        headers={
            "Cookie": session,
            "User-Agent": "FantasyInjuryWatchBryce/1.0",
            "Accept": "text/html",
        }, method="GET",
    )
    try:
        with opener.open(request, timeout=25) as response:
            page = response.read(1_000_000).decode("utf-8", "replace")
            final_host = urlsplit(response.url).hostname
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
        raise OwnerAuthError("Authenticated MFL Starting Lineups request failed") from None
    structure = ReportStructure()
    structure.feed(page)
    report = {
        "host_valid": bool(final_host and re.fullmatch(
            r"www\d+\.myfantasyleague\.com", final_host)),
        "starting_lineups_heading": structure.starting_lineups_text,
        "html_table_count": structure.tables,
        "html_row_count": structure.rows,
        "html_cell_count": structure.cells,
        "login_form_present": structure.password_inputs > 0,
        "player_links_count": structure.linked_players,
    }
    return report


def run():
    username = os.environ.get("MFL_OWNER_USERNAME") or ""
    password = os.environ.get("MFL_OWNER_PASSWORD") or ""
    if not username or not password:
        print("AUTH PROBE: MFL owner credentials not configured in repository secrets.")
        return
    league_id = os.environ.get("MFL_LEAGUE_ID") or ""
    franchise_id = os.environ.get("MFL_FRANCHISE_ID") or ""
    season = os.environ.get("MFL_SEASON") or "2026"
    week = os.environ.get("MFL_LINEUP_WEEK") or "12"
    if not all(x.isdigit() for x in (league_id, franchise_id, season, week)):
        raise OwnerAuthError("Missing or invalid MFL league, season, week, or franchise configuration")
    opener = _make_opener()
    try:
        cookie = owner_login(opener, season, username, password, league_id)
        print("AUTH PROBE: MFL owner login returned a session cookie (value hidden).")
        result = probe_owner_page(opener, season, league_id, franchise_id, week, cookie)
    except OwnerAuthError as error:
        # Every raised exception is an allowlisted, credential-free category.
        print(f"AUTH PROBE: {error}")
        return
    finally:
        cookie = ""
    print("AUTH PROBE: " + ", ".join(f"{key}={value}" for key, value in result.items()))
    if result["login_form_present"] or not result["host_valid"]:
        print("AUTH PROBE: authenticated webpage access not confirmed.")
    elif result["html_row_count"] == 0:
        print("AUTH PROBE: no pregame lineup table detected; needs further inspection.")
    else:
        print("AUTH PROBE: markup returned; next validate player ID extraction privately.")


if __name__ == "__main__":
    run()
