"""One-time, one-way test using MFL's actual authenticated lineup web form.

User explicitly authorized leaving Anthony Hill Jr. starting in Week 11.
Never revert a submitted change or retry a write.
"""
import os
import time
from .mfl import export, MFLAPIError
from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .live_lineup_dry_run import fetch_authenticated_lineup
from .submitted_lineup import extract_submitted_lineup, LineupParseError
from .manual_lineup_test import read_week_lineup, ManualSwapError
from .mfl_native_lineup import prepare_post, submit_native
from .reversible_lineup_test import identify_pair, verify_list
from .nfl_week import fetch_espn_week, NFLScheduleError

YEAR, LEAGUE, FRANCHISE, WEEK = "2026", "40298", "0001", "11"

def authorized(env):
    if not (
        env.get("GITHUB_EVENT_NAME") == "push"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
        and env.get("GITHUB_REPOSITORY") == "williamsbryce/fantasy-injury-watch"
        and env.get("GITHUB_ACTOR") == "williamsbryce"
        and env.get("NATIVE_LINEUP_APPROVAL") ==
            "APPROVED_ONE_WAY_NATIVE_CEDRIC_GRAY_TO_ANTHONY_HILL_W11"
    ):
        raise ManualSwapError("NATIVE ONE-WAY: authorization failed")

def read_html_and_selection(opener, cookie):
    html = fetch_authenticated_lineup(
        YEAR, LEAGUE, FRANCHISE, opener, cookie,
        week=WEEK, week_param="WEEK")
    lineup = extract_submitted_lineup(html, expected_starters=17)
    if lineup["form_week_values"] != [11]:
        raise ManualSwapError("NATIVE ONE-WAY: MFL returned different week")
    return html, lineup

def run():
    authorized(os.environ)
    user = os.environ.get("MFL_OWNER_USERNAME")
    password = os.environ.get("MFL_OWNER_PASSWORD")
    key = os.environ.get("MFL_API_KEY")
    if not (user and password and key):
        raise ManualSwapError("NATIVE ONE-WAY: missing owner login or key")
    opener = _make_opener()
    try:
        cookie = owner_login(opener, YEAR, user, password, LEAGUE)
    except OwnerAuthError as err:
        if "returned html instead of valid XML" not in str(err):
            raise
        print("NATIVE ONE-WAY: transient HTML login, retrying once before any write")
        time.sleep(8)
        cookie = owner_login(opener, YEAR, user, password, LEAGUE)

    before_html, first = read_html_and_selection(opener, cookie)
    rosters = export(int(YEAR), "rosters", LEAGUE, key)
    time.sleep(1)
    players = export(int(YEAR), "players", LEAGUE, key)
    schedule = fetch_espn_week(int(YEAR), int(WEEK))
    original, proposal = identify_pair(first, rosters, players, schedule)
    del before_html
    second_html, second = read_html_and_selection(opener, cookie)
    if second["starters"] != original:
        raise ManualSwapError("NATIVE ONE-WAY: starters changed between reads")
    outgoing = next(iter(set(original) - set(proposal)))
    incoming = next(iter(set(proposal) - set(original)))
    action, encoded = prepare_post(
        second_html, originals=original, proposed=proposal,
        outgoing=outgoing, incoming=incoming)
    del second_html
    print("NATIVE ONE-WAY: authenticated MFL form verified for Week 11, franchise 0001")
    print("NATIVE ONE-WAY: unchanged starter count=16, total selected=17")
    print("NATIVE ONE-WAY: Cedric Gray out, Anthony Hill Jr. in. No restore.")
    print("NATIVE ONE-WAY: submitting exact native website POST once")
    result = submit_native(opener, cookie, action, encoded)
    print("NATIVE ONE-WAY: submission HTTP status=", result["http_status"],
          "response_bytes=", result["response_bytes"])

    # Never assume HTML or HTTP 200 indicates success.
    time.sleep(2)
    saved = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
    if verify_list(saved["starters"], proposal):
        print("NATIVE ONE-WAY SUCCESS: Anthony Hill Jr. STARTING, Cedric Gray BENCHED")
        print("NATIVE ONE-WAY SUCCESS: all other 16 starters unchanged, no rollback")
    elif verify_list(saved["starters"], original):
        print("NATIVE ONE-WAY NO CHANGE: Cedric Gray still STARTING")
        raise ManualSwapError("NATIVE ONE-WAY: website form did not save desired lineup")
    else:
        print("NATIVE ONE-WAY CRITICAL: saved lineup differs from both checked states")
        raise ManualSwapError("NATIVE ONE-WAY: unexpected lineup state; inspect MFL manually")


if __name__ == "__main__":
    try:
        run()
    except (OwnerAuthError, ManualSwapError, LineupParseError, MFLAPIError,
            NFLScheduleError, ValueError) as exc:
        print("NATIVE ONE-WAY STOPPED:", type(exc).__name__, str(exc))
        raise SystemExit(1) from None
