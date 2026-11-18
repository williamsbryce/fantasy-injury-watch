"""In-memory MFL owner login and pregame Starting Lineups read-only probe.

Never prints response bodies, cookies, passwords, usernames, player IDs,
roster names, page URLs, or tokens. Never sends an MFL import/write request.
"""
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit, parse_qs
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
        lower = xml[:300].lstrip().lower()
        if lower.startswith((b"<html", b"<!doctype html")):
            safe_type = "html"
        elif lower.startswith((b"{", b"[")):
            safe_type = "json"
        elif lower.startswith(b"<?xml") or lower.startswith(b"<status"):
            safe_type = "broken_xml"
        else:
            safe_type = "other"
        # Only classification and rough length, never response content.
        raise OwnerAuthError(
            f"MFL owner login returned {safe_type} instead of valid XML "
            f"(response_bytes={len(xml)})"
        ) from None
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



class TableShape(HTMLParser):
    """Structural report diagnostics; never stores or emits player text."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.active = []
        self.tag_counts = {}
        self.headings = 0
        self.input_names = set()
        self.markers = set()

    def handle_starttag(self, tag, attrs):
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        a = dict(attrs)
        if tag == "table":
            classname = a.get("class", "")
            # Record only safe CSS class identifiers, never dynamic IDs.
            classname = " ".join(
                x for x in classname.split()
                if re.fullmatch(r"[a-zA-Z_-]{1,24}", x)
            )[:70]
            self.tables.append({"class": classname or "none", "rows": 0, "cells": 0,
                                "headings": 0, "links": 0, "texts": 0,
                                "link_routes": []})
            self.active.append(len(self.tables) - 1)
        elif tag == "tr" and self.active:
            self.tables[self.active[-1]]["rows"] += 1
        elif tag == "td" and self.active:
            self.tables[self.active[-1]]["cells"] += 1
        elif tag == "th" and self.active:
            self.tables[self.active[-1]]["headings"] += 1
        elif tag == "a" and self.active:
            current = self.tables[self.active[-1]]
            current["links"] += 1
            href = a.get("href") or ""
            if len(current["link_routes"]) < 6:
                parsed = urlsplit(href)
                route = parsed.path.split("/")[-1].lower()
                route = route if re.fullmatch(r"[a-z_]{1,20}", route) else "other"
                params = parse_qs(parsed.query)
                def code(key):
                    value = (params.get(key) or [""])[0]
                    return value if re.fullmatch(r"[0-9]{1,3}", value) else ""
                current["link_routes"].append({
                    "route": route, "O": code("O"), "R": code("R"),
                    "F_present": bool(params.get("F")),
                    "WEEK_present": bool(params.get("WEEK")),
                })
        if tag == "h1" or tag == "h2":
            self.headings += 1
        if tag == "input":
            name = a.get("name", "")
            # Input names can be dynamic; classify, never output raw names.
            for allowed in ("STARTERS", "PLAYERS", "WEEK", "F", "L", "O"):
                if name.upper() == allowed:
                    self.input_names.add(allowed)
        for known in ("lineup", "starter", "player", "report", "roster"):
            if known in (a.get("class", "") + " " + a.get("id", "")).lower():
                self.markers.add(known)

    def handle_endtag(self, tag):
        if tag == "table" and self.active:
            self.active.pop()

    def handle_data(self, data):
        if self.active and data.strip():
            self.tables[self.active[-1]]["texts"] += 1



class PlayerRowShapes(HTMLParser):
    """Read markup privately and output only row shape and generic slot labels."""
    SAFE_SLOTS = {"qb", "rb", "wr", "te", "pk", "k", "def", "dst", "dl", "lb",
                  "db", "de", "dt", "cb", "s", "flex", "ir", "bench"}
    GENERIC = {
        "starters", "starter", "nonstarters", "non-starters", "bench",
        "starting lineup", "starting lineups", "lineup", "not submitted",
        "submitted", "player", "position", "status", "points", "average",
        "stats", "projected", "name", "opp", "total", "week",
    }

    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = {"cells": [], "class": self._safe_class(attrs.get("class", ""))}
        if tag in ("td", "th") and self.row is not None:
            self.cell = {"kind": tag, "class": self._safe_class(attrs.get("class", "")),
                         "text": [], "player_id": None}
        if tag == "a" and self.cell is not None:
            u = urlsplit(attrs.get("href", ""))
            if u.path.split("/")[-1].lower() == "player":
                p = (parse_qs(u.query).get("P") or [""])[0]
                if p.isdigit() and len(p) <= 8:
                    self.cell["player_id"] = p

    @staticmethod
    def _safe_class(classname):
        return " ".join(
            x for x in classname.split()
            if re.fullmatch(r"[a-zA-Z_-]{1,28}", x)
        )[:80]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.cell["text"] = " ".join(" ".join(self.cell["text"]).split())
            self.row["cells"].append(self.cell)
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def public_shapes(self):
        output = []
        for idx, row in enumerate(self.rows):
            if idx >= 85:
                break
            parts = []
            for cell in row["cells"]:
                lower = cell["text"].strip().lower()
                recognized = lower if lower in self.GENERIC else (
                    lower if lower in self.SAFE_SLOTS else "")
                if not recognized:
                    for label in ("starters", "nonstarters", "bench"):
                        if re.search(r"\b" + label + r"\b", lower):
                            recognized = label
                            break
                parts.append({
                    "kind": cell["kind"],
                    "class": cell["class"],
                    "label": recognized[:25],
                    "has_player_id": cell["player_id"] is not None,
                })
            output.append({"index": idx, "class": row["class"], "cells": parts})
        return output

    def player_id_summary(self):
        pids = [c["player_id"] for row in self.rows for c in row["cells"]
                if c["player_id"] is not None]
        return {"player_cell_count": len(pids), "unique_players": len(set(pids))}


def probe_owner_page(opener, year, league_id, franchise_id, week, session, report_code='06'):
    """Retrieve owner-only MFL report without displaying or committing its contents."""
    params = urlencode({
        "L": league_id, "O": report_code, "WEEK": week, "F": franchise_id,
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
    shape = TableShape()
    shape.feed(page)
    rows = PlayerRowShapes()
    rows.feed(page)
    report = {
        "host_valid": bool(final_host and re.fullmatch(
            r"www\d+\.myfantasyleague\.com", final_host)),
        "starting_lineups_heading": structure.starting_lineups_text,
        "html_table_count": structure.tables,
        "html_row_count": structure.rows,
        "html_cell_count": structure.cells,
        "login_form_present": structure.password_inputs > 0,
        "player_links_count": structure.linked_players,
        "html_length": len(page),
        "table_shapes": shape.tables,
        "input_names_allowlisted": sorted(shape.input_names),
        "css_marker_categories": sorted(shape.markers),
        "player_id_summary": rows.player_id_summary(),
        "row_shapes": rows.public_shapes(),
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
        overview = probe_owner_page(opener, season, league_id, franchise_id, week, cookie)
        result = probe_owner_page(opener, season, league_id, franchise_id, week, cookie, report_code="07")
    except OwnerAuthError as error:
        # Every raised exception is an allowlisted, credential-free category.
        print(f"AUTH PROBE: {error}")
        return
    finally:
        cookie = ""
    print("AUTH PROBE: lineup overview O=06 tables=", overview["html_table_count"])
    print("AUTH PROBE: franchise lineup detail O=07")
    # All output is class/tag counts, not user-specific HTML or player details.
    public_fields = {k:v for k,v in result.items() if k not in ("table_shapes", "row_shapes")}
    print("AUTH PROBE: " + ", ".join(f"{key}={value}" for key, value in public_fields.items()))
    # Do not print any HTML, player names or credentials.
    print("AUTH PROBE TABLE SHAPES:", result["table_shapes"])
    print("AUTH PROBE ROW SHAPES:", result["row_shapes"])
    if result["login_form_present"] or not result["host_valid"]:
        print("AUTH PROBE: authenticated webpage access not confirmed.")
    elif result["html_row_count"] == 0:
        print("AUTH PROBE: no pregame lineup table detected; needs further inspection.")
    else:
        print("AUTH PROBE: markup returned; next validate player ID extraction privately.")


if __name__ == "__main__":
    run()
