"""Explicitly approved, one-time MFL lineup swap.

NEVER called by scheduled injury monitoring. Requires two exact player IDs,
Week 11 matching the signed-in MFL form, and an intentional manual workflow.
Only one selected starter is replaced. Post-write MFL response and read-back
are checked; no automatic retry of a lineup write.
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .live_lineup_dry_run import fetch_authenticated_lineup
from .submitted_lineup import extract_submitted_lineup, LineupParseError


class ManualSwapError(RuntimeError):
    pass


def single_swap(selected, selectable, out_id, in_id, expected_count=17):
    original = list(selected)
    if len(original) != expected_count or len(set(original)) != len(original):
        raise ManualSwapError("Submitted lineup does not have the expected starter count")
    if not (out_id.isdigit() and in_id.isdigit()) or out_id == in_id:
        raise ManualSwapError("Swap player IDs are invalid")
    if original.count(out_id) != 1:
        raise ManualSwapError("Exact outgoing player is not a current starter")
    if in_id in original:
        raise ManualSwapError("Incoming player is already a starter")
    if in_id not in set(selectable):
        raise ManualSwapError("Incoming bench player is not selectable in MFL")
    updated = [in_id if p == out_id else p for p in original]
    if len(updated) != expected_count or len(set(updated)) != expected_count:
        raise ManualSwapError("Proposed lineup is malformed")
    if set(original).difference(updated) != {out_id}:
        raise ManualSwapError("More than the outgoing starter would be removed")
    if set(updated).difference(original) != {in_id}:
        raise ManualSwapError("More than the incoming bench player would be added")
    return updated


def read_week_lineup(opener, year, league, franchise, week, cookie):
    page = fetch_authenticated_lineup(
        year, league, franchise, opener, cookie,
        week=str(week), week_param="WEEK",
    )
    lineup = extract_submitted_lineup(page, expected_starters=17)
    if lineup["form_week_values"] != [int(week)]:
        raise ManualSwapError("MFL returned a different lineup week")
    return lineup


def check_approval(mode, phrase, out_id, in_id, week, event, attempt):
    if mode != "LIVE":
        return False
    expected = f"APPROVE {out_id} TO {in_id} WEEK {int(week)}"
    if phrase != expected or event != "workflow_dispatch" or str(attempt) != "1":
        raise ManualSwapError("Explicit one-time approval or initial manual dispatch missing")
    return True


def submit_full_lineup(opener, cookie, year, league, week, proposed):
    """One POST to league's own host; never follows redirects as successful writes."""
    if len(proposed) != 17 or len(set(proposed)) != 17:
        raise ManualSwapError("Invalid full-lineup POST proposal")
    url = (
        f"https://www46.myfantasyleague.com/{int(year)}/import?"
        + urllib.parse.urlencode({"TYPE": "lineup", "L": league})
    )
    form = urllib.parse.urlencode({
        "TYPE": "lineup", "L": league, "W": str(int(week)),
        "STARTERS": ",".join(proposed),
        "COMMENTS": "Approved one-time Fantasy Injury Watch swap test",
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=form, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie, "Accept": "application/xml,text/xml",
            "User-Agent": "FantasyInjuryWatchBryce/1.0",
        },
    )
    try:
        with opener.open(request,timeout=30) as result:
            if result.status not in (200,201,202):
                raise ManualSwapError("MFL lineup submission was not accepted")
            response = result.read(100_000)
    except (urllib.error.HTTPError,urllib.error.URLError,OSError,TimeoutError):
        raise ManualSwapError("MFL lineup submission failed or was interrupted") from None
    try:
        root = ET.fromstring(response)
    except ET.ParseError:
        raise ManualSwapError("MFL did not confirm lineup submission with XML") from None
    if root.tag.lower() != "status" or (root.text or "").strip().upper() != "OK":
        raise ManualSwapError("MFL rejected or did not confirm the lineup change")
    return True


def run():
    year=os.environ.get("MFL_SEASON") or "2026"
    league=os.environ.get("MFL_LEAGUE_ID") or ""
    franchise=os.environ.get("MFL_FRANCHISE_ID") or ""
    week=os.environ.get("TEST_LINEUP_WEEK") or ""
    out_id=(os.environ.get("TEST_OUT_PLAYER_ID") or "").strip()
    in_id=(os.environ.get("TEST_IN_PLAYER_ID") or "").strip()
    mode=(os.environ.get("TEST_SWAP_MODE") or "DRY_RUN").strip()
    approval=os.environ.get("TEST_APPROVAL") or ""
    if not all(x.isdigit() for x in (year, league, franchise, week, out_id, in_id)):
        raise ManualSwapError("Missing or invalid league, player, or week identifier")
    if str(year)!="2026" or str(league)!="40298" or str(franchise).zfill(4)!="0001":
        raise ManualSwapError("One-time tester restricted to designated league/franchise")
    if int(week)!=11:
        raise ManualSwapError("One-time tester restricted to 2026 Week 11")
    live=check_approval(
        mode,approval,out_id,in_id,week,
        os.environ.get("GITHUB_EVENT_NAME",""),
        os.environ.get("GITHUB_RUN_ATTEMPT",""),
    )
    if not live:
        print("MANUAL SWAP TEST: DRY RUN ONLY, no POST allowed")
    username=os.environ.get("MFL_OWNER_USERNAME") or ""
    password=os.environ.get("MFL_OWNER_PASSWORD") or ""
    if not username or not password:
        raise ManualSwapError("Missing MFL owner login secrets")
    opener=_make_opener()
    try:
        cookie=owner_login(opener,year,username,password,league)
        before=read_week_lineup(opener,year,league,franchise,week,cookie)
        if out_id not in before["starters"]:
            raise ManualSwapError("Outgoing player was not selected; no action")
        proposal=single_swap(
            before["starters"],before["all_selectable"],out_id,in_id
        )
        check=read_week_lineup(opener,year,league,franchise,week,cookie)
        if set(check["starters"])!=set(before["starters"]):
            raise ManualSwapError("Lineup changed between reads; no action")
        if in_id not in check["all_selectable"]:
            raise ManualSwapError("Incoming bench player no longer selectable")
        if not live:
            print("MANUAL SWAP TEST: one-for-one proposal validated; 16 starters preserved")
            return
        # ONLY LIVE WRITE call. All other paths above are GET requests.
        submit_full_lineup(opener,cookie,year,league,week,proposal)
        after=read_week_lineup(opener,year,league,franchise,week,cookie)
        if set(after["starters"])!=set(proposal):
            raise ManualSwapError(
                "CRITICAL: MFL accepted submission but read-back differs; "
                "check the lineup manually immediately"
            )
        print("MANUAL SWAP TEST: confirmed ONE starter replacement")
        print("MANUAL SWAP TEST: all 16 unrelated starters preserved")
    except (OwnerAuthError, LineupParseError) as error:
        raise ManualSwapError("MFL lineup read/login failed; no action assured") from None
    finally:
        cookie = ""


if __name__=="__main__":
    try:
        run()
    except ManualSwapError as error:
        # Error messages are deliberate, contain no player IDs, tokens, or URLs.
        print("MANUAL SWAP TEST: FAILED",str(error))
        raise SystemExit(1) from None
