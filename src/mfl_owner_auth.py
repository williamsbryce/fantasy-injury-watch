"""In-memory MFL owner login and pregame Starting Lineups read-only probe.

Never prints response bodies, cookies, passwords, usernames, player IDs,
roster names, page URLs, or tokens. Never sends an MFL import/write request.
"""
from .submitted_lineup import extract_submitted_lineup, report_counts, LineupParseError
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit, parse_qs
import os
import re
import json
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



class SafeFormShape(HTMLParser):
    """Only counts input controls and selected lineup values; no field values logged."""
    def __init__(self):
        super().__init__()
        self.form_count = 0
        self.input_types = {}
        self.inputs_numeric_value = 0
        self.inputs_checked = 0
        self.inputs_selected = 0
        self.select_count = 0
        self.option_count = 0
        self.options_selected = 0
        self.field_categories = set()
        self.numeric_option_count = 0
        self.numeric_option_selected = 0
        self.form_method_get = 0
        self.form_method_post = 0
        self.safe_hidden_weeks = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.form_count += 1
            method = (a.get("method") or "GET").lower()
            if method == "post":
                self.form_method_post += 1
            elif method == "get":
                self.form_method_get += 1
        if tag == "input":
            if (a.get("type") or "").lower() == "hidden" and (a.get("name") or "").upper() == "WEEK":
                week_text = str(a.get("value") or "").strip()
                if week_text.isdigit() and 1 <= int(week_text) <= 18:
                    self.safe_hidden_weeks.append(int(week_text))
            kind = (a.get("type") or "text").lower()
            kind = kind if re.fullmatch(r"[a-z]{1,20}", kind) else "other"
            self.input_types[kind] = self.input_types.get(kind, 0) + 1
            if a.get("checked") is not None or "checked" in a:
                self.inputs_checked += 1
            val = a.get("value") or ""
            if val.isdigit() and len(val) <= 8:
                self.inputs_numeric_value += 1
            name = (a.get("name") or "").lower()
            for token in ("starter", "player", "lineup", "bench", "week", "status"):
                if token in name:
                    self.field_categories.add(token)
        if tag == "select":
            self.select_count += 1
        if tag == "option":
            self.option_count += 1
            val = a.get("value") or ""
            if val.isdigit() and len(val) <= 8:
                self.numeric_option_count += 1
                if a.get("selected") is not None or "selected" in a:
                    self.numeric_option_selected += 1
            if a.get("selected") is not None or "selected" in a:
                self.options_selected += 1

    def public(self):
        return {
            "forms": self.form_count, "post_forms": self.form_method_post,
            "get_forms": self.form_method_get,
            "input_types": self.input_types,
            "inputs_checked": self.inputs_checked,
            "inputs_numeric_values": self.inputs_numeric_value,
            "selects": self.select_count, "options": self.option_count,
            "options_selected": self.options_selected,
            "options_numeric": self.numeric_option_count,
            "options_numeric_selected": self.numeric_option_selected,
            "field_categories": sorted(self.field_categories),
            "safe_hidden_week_values": self.safe_hidden_weeks,
        }



class SafePageDiagnostics(HTMLParser):
    """Tag and wording categories only. Never emits HTML, text or link destinations."""
    CHECKS = {
        "login_required": r"log\s*in\s*(?:to|first|before)|must\s+be\s+logged\s+in",
        "owner_required": r"must\s+be\s+(?:the\s+)?(?:franchise\s+)?owner|not\s+authorized|permission\s+denied",
        "lineup_not_available": r"lineup\s+(?:is\s+)?(?:not\s+available|unavailable|locked)",
        "lineup_not_submitted": r"(?:no|not)\s+(?:starting\s+)?lineup\s+(?:has\s+been\s+)?submitted",
        "javascript_required": r"javascript\s+(?:must\s+be\s+enabled|is\s+required)",
        "submit_lineup": r"submit\s+(?:your|a)?\s*lineup",
        "starter_or_bench": r"\bstarters?\b|\bbench\b",
        "lineup_change_disallowed": r"(?:cannot|can.t|not\s+allowed\s+to)\s+(?:make\s+)?(?:lineup|submit)",
    }

    def __init__(self):
        super().__init__()
        self.script_depth = 0
        self.style_depth = 0
        self.visible = []
        self.script_text_chunks = []
        self.scripts = 0
        self.scripts_inline = 0
        self.sources = {}
        self.iframe_count = 0
        self.divs = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.script_depth += 1
            self.scripts += 1
            src = a.get("src") or ""
            if not src:
                self.scripts_inline += 1
            else:
                leaf = urlsplit(src).path.rsplit("/", 1)[-1].lower()
                for marker in ("lineup", "roster", "app", "main", "jquery", "mfl", "script"):
                    if marker in leaf:
                        self.sources[marker] = self.sources.get(marker, 0) + 1
        if tag == "style":
            self.style_depth += 1
        if tag == "iframe":
            self.iframe_count += 1
        if tag == "div":
            self.divs += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.script_depth = max(0, self.script_depth - 1)
        if tag == "style":
            self.style_depth = max(0, self.style_depth - 1)

    def handle_data(self, data):
        if self.script_depth and data.strip():
            self.script_text_chunks.append(data)
        if not self.script_depth and not self.style_depth and data.strip():
            self.visible.append(data)

    def public(self):
        visible = " ".join(self.visible)
        scripts = " ".join(self.script_text_chunks)
        categories = {
            "inline_player_data": r"player(?:s|id)?\s*[:=]",
            "inline_starter_data": r"starter(?:s)?\s*[:=]",
            "inline_roster_data": r"roster\s*[:=]",
            "lineup_status": r"lineup.*?(?:status|submitted)",
            "ajax_call": r"\b(?:fetch|ajax|XMLHttpRequest)\s*\(",
            "mfl_api_endpoint": r"/(?:export|import)\?",
        }
        notice_terms = {
            "permission": r"permission|permitted|not\s+authorized",
            "access": r"access|denied",
            "submitted": r"submitted|submission",
            "lineup": r"lineup",
            "week": r"week",
            "error": r"error|failed|not\s+allowed",
            "inactive_franchise": r"inactive\s+franchise|select\s+(?:your\s+)?franchise",
            "lineup_form": r"(?:select|choose|change)\s+(?:your\s+)?(?:starting\s+)?lineup",
            "none_available": r"not\s+available|not\s+found|nothing\s+to\s+show",
        }
        return {
            "visible_text_chars": len(visible),
            "visible_nodes": len(self.visible),
            "script_count": self.scripts, "inline_scripts": self.scripts_inline,
            "script_categories": self.sources,
            "iframes": self.iframe_count, "divs": self.divs,
            "marker_categories": {
                key: bool(re.search(pattern, visible, re.I))
                for key, pattern in self.CHECKS.items()
            },
            "notice_counts": {
                key: len(re.findall(pattern, visible, re.I))
                for key, pattern in notice_terms.items()
            },
            "inline_script_chars": len(scripts),
            "inline_script_categories": {
                key: bool(re.search(pattern, scripts, re.I))
                for key, pattern in categories.items()
            },
            "inline_five_digit_numbers": len(re.findall(r"(?<!\d)\d{5}(?!\d)", scripts)),
        }



def verify_owner_franchise(opener, year, session, league_id, franchise_id):
    """Only safe structural metadata, never user identity or league names."""
    results = []
    probes = [
        ("export", f"https://api.myfantasyleague.com/{int(year)}/export?"
         + urlencode({"TYPE": "myleagues", "JSON": "1", "YEAR": str(year)})),
        ("direct", f"https://api.myfantasyleague.com/{int(year)}/myleagues?JSON=1"),
    ]
    for mode, url in probes:
        request = urllib.request.Request(
            url, headers={"Cookie": session, "Accept": "application/json",
                          "User-Agent": "FantasyInjuryWatchBryce/1.0"}, method="GET",
        )
        try:
            with opener.open(request, timeout=20) as response:
                doc = json.loads(response.read(1_000_000))
        except (ValueError, urllib.error.HTTPError, urllib.error.URLError, OSError):
            results.append({"mode": mode, "available": False, "reason": "request_or_parse_failed"})
            continue
        if not isinstance(doc, dict):
            results.append({"mode": mode, "available": False, "reason": "non_object"})
            continue
        top = [key for key in ("myleagues", "error", "status", "version")
               if key in doc]
        if "error" in doc:
            results.append({"mode": mode, "available": False,
                            "reason": "api_error", "top_fields": top})
            continue
        root = doc.get("myleagues")
        if not isinstance(root, dict):
            results.append({"mode": mode, "available": False,
                            "reason": "missing_myleagues_root", "top_fields": top})
            continue
        items = root.get("league") or []
        leagues = items if isinstance(items, list) else [items]
        valid = [l for l in leagues if isinstance(l, dict)]
        matches = [l for l in valid
                   if str(l.get("id") or l.get("league_id") or "") == str(league_id)]
        results.append({
            "mode": mode, "available": True,
            "league_rows": len(valid), "league_field_present": "league" in root,
            "league_accessible": len(matches) == 1,
            "franchise_matches": any(
                str(m.get("franchise_id") or m.get("franchiseId") or m.get("FRANCHISE_ID") or "").zfill(4)
                == str(franchise_id).zfill(4) for m in matches
            ),
        })
    return results



def probe_owner_page(opener, year, league_id, franchise_id, week, session, report_code='06', include_f=True, include_week=True, endpoint='options', lineup_week_parameter=None):
    """Retrieve owner-only MFL report without displaying or committing its contents."""
    args = {"L": league_id, "O": report_code}
    if include_week:
        args["WEEK"] = week
    if include_f:
        args["F"] = franchise_id
    if endpoint == "lineup":
        # The user's actual 2026 Submit Lineup URL; do not substitute an options report.
        args = {"L": league_id, "FRANCHISE": franchise_id}
        if lineup_week_parameter in ("WEEK", "W"):
            args[lineup_week_parameter] = week
    elif endpoint != "options":
        raise ValueError("Unsupported MFL read-only endpoint")
    params = urlencode(args)
    request = urllib.request.Request(
        f"https://www46.myfantasyleague.com/{int(year)}/{endpoint}?{params}",
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
    form = SafeFormShape()
    form.feed(page)
    page_diagnostics = SafePageDiagnostics()
    page_diagnostics.feed(page)
    lineup_counts = {}
    if endpoint == "lineup":
        try:
            lineup_counts = report_counts(extract_submitted_lineup(page, expected_starters=17))
            lineup_counts["read_result"] = "verified"
        except LineupParseError:
            lineup_counts = {"read_result": "not_verified"}
    report = {
        "lineup_extraction": lineup_counts,
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
        "form_shape": form.public(),
        "page_diagnostics": page_diagnostics.public(),
        "visible_submit_markers": {
            "submit_lineup_title": bool(re.search(r"submit\s+(?:a\s+)?lineup", page, re.I)),
            "starter_word_count": len(re.findall(r"starters?", page, re.I)),
        },
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
        comparison = []
        for parameter in (None, "WEEK", "W"):
            data = probe_owner_page(
                opener, season, league_id, franchise_id, week, cookie,
                endpoint="lineup", lineup_week_parameter=parameter,
            )
            comparison.append({
                "parameter": parameter or "none",
                "hidden_weeks": data["form_shape"]["safe_hidden_week_values"],
                "starter_count": data["lineup_extraction"].get("starter_count"),
                "verified": data["lineup_extraction"].get("read_result") == "verified",
                "checked_count": data["form_shape"]["inputs_checked"],
            })
        result = data
    except OwnerAuthError as error:
        # Every raised exception is an allowlisted, credential-free category.
        print(f"AUTH PROBE: {error}")
        return
    finally:
        cookie = ""
    print("AUTH PROBE: compare three pregame lineup week URL variants:", comparison)
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
        if result["lineup_extraction"].get("read_result") == "verified":
            print("AUTH PROBE: submitted starters extracted with validated unique IDs (hidden).")
        else:
            print("AUTH PROBE: lineup selectors not verified; do not allow writes.")


if __name__ == "__main__":
    run()
