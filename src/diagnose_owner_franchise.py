"""MFL owner-to-franchise read-only diagnostic. No lineup POST/import requests.

This module logs structural and yes/no ownership evidence only, never cookies,
username, passwords, player IDs, full HTML, or private API response bodies.
"""
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .live_lineup_dry_run import fetch_authenticated_lineup
from .submitted_lineup import extract_submitted_lineup, LineupParseError


class Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden_franchises = []
        self.forms = 0
        self.action_paths = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms += 1
            action = urllib.parse.urlsplit(a.get("action") or "")
            self.action_paths.append(action.path.rsplit("/", 1)[-1].lower())
        if tag == "input" and (a.get("type") or "").lower() == "hidden":
            if (a.get("name") or "").upper() in {"FRANCHISE", "FRANCHISE_ID", "F"}:
                self.hidden_franchises.append(str(a.get("value") or ""))


def inspect_page(html, label):
    parser = Meta()
    parser.feed(html)
    result = {"label": label, "form_count": parser.forms,
              "has_lineup_post_form": any(a in {"lineup", "submit_lineup"} for a in parser.action_paths),
              "hidden_franchise_matches_0001": any(f.zfill(4) == "0001" for f in parser.hidden_franchises)}
    try:
        selection = extract_submitted_lineup(html, expected_starters=17)
        result.update({
            "selected_starters": len(selection["starters"]),
            "available_players": len(selection["all_selectable"]),
            "week_is_11": selection["form_week_values"] == [11],
            "same_starting_ids_as_other": None,
        })
        return result, selection["starters"]
    except LineupParseError:
        result.update({"selected_starters": "not_extractable",
                       "available_players": "not_extractable",
                       "week_is_11": False})
        return result, None


def read_default(opener, cookie):
    params = urllib.parse.urlencode({"L": "40298", "WEEK": "11"})
    req = urllib.request.Request(
        "https://www46.myfantasyleague.com/2026/lineup?" + params,
        headers={"Cookie": cookie, "Accept": "text/html",
                 "User-Agent": "FantasyInjuryWatchBryce/1.0"},
        method="GET",
    )
    with opener.open(req, timeout=25) as response:
        if not re.fullmatch(r"www\d+\.myfantasyleague\.com",
                            urllib.parse.urlsplit(response.url).hostname or ""):
            raise OwnerAuthError("Owner default lineup page redirected unexpectedly")
        return response.read(1_000_000).decode("utf-8", "replace")


def run():
    username = os.environ.get("MFL_OWNER_USERNAME") or ""
    password = os.environ.get("MFL_OWNER_PASSWORD") or ""
    if not username or not password:
        print("FRANCHISE DIAGNOSTIC: owner credentials missing")
        return
    opener = _make_opener()
    try:
        cookie = owner_login(opener, "2026", username, password, "40298")
        explicit_html = fetch_authenticated_lineup(
            "2026", "40298", "0001", opener, cookie,
            week="11", week_param="WEEK",
        )
        explicit, ids = inspect_page(explicit_html, "explicit_0001")
        default_html = read_default(opener, cookie)
        default, default_ids = inspect_page(default_html, "no_franchise_param")
        print("FRANCHISE DIAGNOSTIC:", explicit)
        print("FRANCHISE DIAGNOSTIC:", default)
        print("FRANCHISE DIAGNOSTIC: saved_starters_match_without_FRANCHISE=",
              None if not ids or not default_ids else set(ids) == set(default_ids))
        print("FRANCHISE DIAGNOSTIC: login_cookie_received=yes; no lineup changes made")
    except (OwnerAuthError, urllib.error.HTTPError, urllib.error.URLError,
            OSError, TimeoutError, ValueError) as exc:
        print("FRANCHISE DIAGNOSTIC: read failed, category=", type(exc).__name__)
        print("FRANCHISE DIAGNOSTIC: no lineup changes made")


if __name__ == "__main__":
    run()
