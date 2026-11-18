"""Prepare exact native MFL lineup-form POST from its authenticated HTML.

No changes to owner selections other than one supplied player ID pair.
All fields, including hidden form state, are preserved in memory.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlencode
import re
import urllib.request
import urllib.error

from .manual_lineup_test import ManualSwapError


class NativeForm(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = 0
        self.active = False
        self.action = ""
        self.method = ""
        self.controls = []
        self.select = None
        self.textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms += 1
            self.active = True
            self.method = str(a.get("method") or "get").lower()
            self.action = str(a.get("action") or "")
            return
        if not self.active:
            return
        if tag == "input":
            kind = str(a.get("type") or "text").lower()
            self.controls.append({
                "type": kind, "name": str(a.get("name") or ""),
                "value": str(a.get("value") or ""),
                "checked": "checked" in a,
                "disabled": "disabled" in a,
            })
        elif tag == "select":
            self.select = {"type": "select", "name": str(a.get("name") or ""),
                           "options": [], "disabled": "disabled" in a}
        elif tag == "option" and self.select is not None:
            self.select["options"].append({
                "value": str(a.get("value") or ""),
                "selected": "selected" in a,
                "disabled": "disabled" in a,
            })
        elif tag == "textarea":
            self.textarea = {"type": "textarea", "name": str(a.get("name") or ""),
                             "value": "", "disabled": "disabled" in a}

    def handle_data(self, data):
        if self.textarea is not None:
            self.textarea["value"] += data

    def handle_endtag(self, tag):
        if tag == "select" and self.select is not None:
            self.controls.append(self.select)
            self.select = None
        elif tag == "textarea" and self.textarea is not None:
            self.controls.append(self.textarea)
            self.textarea = None
        elif tag == "form":
            self.active = False


def prepare_post(html, *, originals, proposed, outgoing, incoming):
    p = NativeForm()
    p.feed(html)
    if p.forms != 1 or p.method != "post":
        raise ManualSwapError("NATIVE: expected one MFL lineup POST form")
    action = urlsplit(p.action)
    if (
        action.scheme != "https"
        or action.hostname != "www46.myfantasyleague.com"
        or action.path != "/2026/lineup"
        or action.query or action.fragment
    ):
        raise ManualSwapError("NATIVE: unsafe or unexpected form action URL")
    hidden = {c["name"]: c["value"] for c in p.controls
              if c["type"] == "hidden" and not c["disabled"]}
    if not (
        hidden.get("LEAGUE_ID") == "40298"
        and hidden.get("FRANCHISE", "").zfill(4) == "0001"
        and hidden.get("WEEK") == "11"
    ):
        raise ManualSwapError("NATIVE: form league, franchise or week mismatched")
    checkboxes = [c for c in p.controls if c["type"] == "checkbox" and not c["disabled"]]
    if len(checkboxes) != 53:
        raise ManualSwapError("NATIVE: MFL selectable roster checkbox count changed")
    if any(not c["name"] or not re.fullmatch(r"\d{1,8}", c["value"]) for c in checkboxes):
        raise ManualSwapError("NATIVE: unrecognized player checkbox name or identifier")
    saved = [c["value"] for c in checkboxes if c["checked"]]
    if len(saved) != 17 or set(saved) != set(originals):
        raise ManualSwapError("NATIVE: website checkboxes do not match authenticated starter snapshot")
    by_id = {c["value"]: c for c in checkboxes}
    if len(by_id) != len(checkboxes):
        raise ManualSwapError("NATIVE: repeated player identifiers")
    if outgoing not in by_id or incoming not in by_id:
        raise ManualSwapError("NATIVE: test players not on selectable roster")
    if by_id[outgoing]["name"] != by_id[incoming]["name"]:
        raise ManualSwapError("NATIVE: outgoing and incoming players in different position fields")
    if len(proposed) != 17 or len(set(proposed)) != 17:
        raise ManualSwapError("NATIVE: invalid proposed starter count")
    if set(proposed) != (set(originals) - {outgoing}) | {incoming}:
        raise ManualSwapError("NATIVE: more than one starter substitution proposed")
    form_pairs = []
    selected_ids = []
    submit_seen = False
    for c in p.controls:
        if c["disabled"] or not c["name"]:
            continue
        typ = c["type"]
        if typ == "checkbox":
            if c["value"] in proposed:
                selected_ids.append(c["value"])
                form_pairs.append((c["name"], c["value"]))
        elif typ == "hidden":
            form_pairs.append((c["name"], c["value"]))
        elif typ in ("text", "textarea"):
            form_pairs.append((c["name"], c["value"]))
        elif typ == "submit" and c["name"] == "SUBMIT":
            form_pairs.append((c["name"], c["value"]))
            submit_seen = True
        elif typ == "select":
            options = [opt for opt in c["options"] if not opt["disabled"]]
            selected = next((opt for opt in options if opt["selected"]), None)
            if selected is None and options:
                selected = options[0]
            if selected:
                form_pairs.append((c["name"], selected["value"]))
        elif typ in ("button", "reset", "image"):
            continue
        else:
            raise ManualSwapError("NATIVE: unsupported form input type")
    if not submit_seen or len(selected_ids) != 17 or set(selected_ids) != set(proposed):
        raise ManualSwapError("NATIVE: website form submission payload incomplete")
    return p.action, urlencode(form_pairs).encode("utf-8")


def submit_native(opener, cookie, action, encoded_data):
    """At most one POST. No retry. All outcomes require separate readback."""
    req = urllib.request.Request(
        action, data=encoded_data, method="POST",
        headers={
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www46.myfantasyleague.com/2026/lineup?L=40298&FRANCHISE=0001&WEEK=11",
            "Origin": "https://www46.myfantasyleague.com",
            "Accept": "text/html",
            "User-Agent": "FantasyInjuryWatchBryce/1.0",
        },
    )
    try:
        with opener.open(req, timeout=30) as response:
            result = {"http_status": int(response.status),
                      "response_bytes": len(response.read(100_001))}
            final = urlsplit(response.url)
            if final.scheme != "https" or final.hostname != "www46.myfantasyleague.com":
                raise ManualSwapError("NATIVE: submission redirected off expected host")
            return result
    except urllib.error.HTTPError as error:
        return {"http_status": int(error.code), "response_bytes": None}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"http_status": None, "response_bytes": None}
