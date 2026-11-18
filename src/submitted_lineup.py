"""Read submitted starter IDs from MFL's authenticated /lineup HTML form.

Pure parser: no HTTP requests, no logging, and no lineup writes. Requiring a
single valid POST form and unique numeric player IDs prevents confusing the
complete roster with the submitted starting lineup.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs
import re


class LineupParseError(ValueError):
    pass


class _LineupFormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = 0
        self.post_forms = 0
        self.form_depth = 0
        self.active_post_form = False
        self.form_action_route = None
        self.form_action_query_keys = []
        self.player_checkbox_ids = []
        self.selected_player_ids = []
        self.checked_nonplayer = 0
        self.invalid_numeric_checkboxes = 0
        self.submit_inputs = 0
        self.checkbox_name_forms = set()

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "form":
            self.forms += 1
            self.form_depth += 1
            self.active_post_form = (attr.get("method") or "get").lower() == "post"
            if self.active_post_form:
                self.post_forms += 1
                action = urlsplit(attr.get("action") or "")
                self.form_action_route = action.path.split("/")[-1].lower()
                self.form_action_query_keys = sorted(parse_qs(action.query))
            return
        if not self.form_depth or not self.active_post_form or tag != "input":
            return
        kind = (attr.get("type") or "text").lower()
        if kind == "submit":
            self.submit_inputs += 1
        if kind != "checkbox":
            return
        name = str(attr.get("name") or "")
        if name:
            if name.isdigit():
                self.checkbox_name_forms.add("numeric")
            elif re.search(r"lineup|starter|player", name, re.I):
                self.checkbox_name_forms.add("lineup_named")
            else:
                self.checkbox_name_forms.add("other")
        raw_id = str(attr.get("value") or "").strip()
        selected = "checked" in attr
        if re.fullmatch(r"\d{1,8}", raw_id):
            self.player_checkbox_ids.append(raw_id)
            if selected:
                self.selected_player_ids.append(raw_id)
        else:
            self.invalid_numeric_checkboxes += 1
            if selected:
                self.checked_nonplayer += 1

    def handle_endtag(self, tag):
        if tag == "form" and self.form_depth:
            self.form_depth -= 1
            self.active_post_form = False


def extract_submitted_lineup(html, *, expected_starters=None):
    """Return starter and bench IDs only after validating the submitted form.

    This is in-memory, never use these IDs as a write payload without
    re-fetching the page and verifying league rules and current selections.
    """
    p = _LineupFormParser()
    p.feed(html)
    if p.forms != 1 or p.post_forms != 1 or p.submit_inputs < 1:
        raise LineupParseError("Expected exactly one MFL lineup POST form")
    if not p.form_action_route or p.form_action_route not in {"lineup", "submit_lineup"}:
        # Site action must be verified before using it as a write path.
        raise LineupParseError("Lineup POST action has an unrecognized route")
    if not p.player_checkbox_ids:
        raise LineupParseError("No MFL numeric player checkboxes found")
    if len(p.player_checkbox_ids) != len(set(p.player_checkbox_ids)):
        raise LineupParseError("Duplicate selectable MFL player IDs")
    if p.checked_nonplayer:
        raise LineupParseError("Checked non-player controls require manual review")
    if not p.selected_player_ids:
        raise LineupParseError("No submitted starters marked in MFL form")
    if len(p.selected_player_ids) != len(set(p.selected_player_ids)):
        raise LineupParseError("Duplicate starting player IDs")
    if expected_starters is not None and len(p.selected_player_ids) != int(expected_starters):
        raise LineupParseError("Starter count does not match verified league settings")
    return {
        "starters": p.selected_player_ids,
        "all_selectable": p.player_checkbox_ids,
        "form_action_route": p.form_action_route,
        "form_action_query_keys": p.form_action_query_keys,
        "checkbox_name_forms": sorted(p.checkbox_name_forms),
        "unrecognized_checkbox_count": p.invalid_numeric_checkboxes,
    }


def report_counts(lineup):
    """Only safe aggregated diagnostic output; never return player identifiers."""
    return {
        "starter_count": len(lineup["starters"]),
        "selectable_count": len(lineup["all_selectable"]),
        "action_route": lineup["form_action_route"],
        "action_query_keys": lineup["form_action_query_keys"],
        "checkbox_name_formats": lineup["checkbox_name_forms"],
        "nonplayer_checkbox_count": lineup["unrecognized_checkbox_count"],
    }
