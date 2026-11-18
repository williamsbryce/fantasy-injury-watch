"""User-authorized, ONE-WAY live MFL Week 11 lineup swap.

Exactly Cedric Gray -> Anthony Hill Jr. for CFFL Dynasty franchise 0001.
Never restores, retries, or changes any other players. Run only from the
deliberately created one-off GitHub Actions push trigger, not scheduled work.
"""
import os
import time
from .mfl import export, MFLAPIError
from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .manual_lineup_test import (
    read_week_lineup, submit_full_lineup, ManualSwapError,
)
from .reversible_lineup_test import identify_pair, verify_list
from .submitted_lineup import LineupParseError
from .nfl_week import fetch_espn_week, NFLScheduleError


YEAR, LEAGUE, FRANCHISE, WEEK = "2026", "40298", "0001", "11"
APPROVAL = "AUTHORIZED_ONE_WAY_CEDRIC_GRAY_TO_ANTHONY_HILL_WEEK11"


def verify_environment(env):
    if (
        env.get("GITHUB_EVENT_NAME") != "push"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("GITHUB_RUN_ATTEMPT") != "1"
        or env.get("GITHUB_REPOSITORY") != "williamsbryce/fantasy-injury-watch"
        or env.get("GITHUB_ACTOR") != "williamsbryce"
        or env.get("ONE_WAY_LINEUP_APPROVAL") != APPROVAL
    ):
        raise ManualSwapError("ONE-WAY: authorization gate rejected this run")


def read_back(opener, cookie):
    return read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)


def check_readback(actual, original, proposal):
    if verify_list(actual, proposal):
        return "APPLIED"
    if verify_list(actual, original):
        return "UNCHANGED"
    return "UNEXPECTED"


def run():
    verify_environment(os.environ)
    username = os.environ.get("MFL_OWNER_USERNAME") or ""
    password = os.environ.get("MFL_OWNER_PASSWORD") or ""
    api_key = os.environ.get("MFL_API_KEY") or ""
    if not (username and password and api_key):
        raise ManualSwapError("ONE-WAY: missing owner secret or export key")
    opener = _make_opener()
    try:
        cookie = owner_login(opener, YEAR, username, password, LEAGUE)
    except OwnerAuthError as e:
        if "returned html instead of valid XML" not in str(e):
            raise
        print("ONE-WAY: login returned transient HTML; retrying login once, no write yet")
        time.sleep(6)
        cookie = owner_login(opener, YEAR, username, password, LEAGUE)

    first = read_back(opener, cookie)
    rosters = export(int(YEAR), "rosters", LEAGUE, api_key)
    time.sleep(1)
    players = export(int(YEAR), "players", LEAGUE, api_key)
    schedule = fetch_espn_week(int(YEAR), int(WEEK))
    original, proposal = identify_pair(first, rosters, players, schedule)
    second = read_back(opener, cookie)
    if second["starters"] != original or second["form_week_values"] != [11]:
        raise ManualSwapError("ONE-WAY: original lineup changed before write, aborted")
    print("ONE-WAY: verified current Week 11 and 17 starters.")
    print("ONE-WAY: Cedric Gray -> Anthony Hill Jr. (both TEN LB); 16 other starters retained.")
    print("ONE-WAY: submitting once to the official api.myfantasyleague.com import endpoint")

    # Do not retry the POST, even if response is empty or interrupted. Read back.
    error = None
    try:
        submit_full_lineup(opener, cookie, YEAR, LEAGUE, WEEK, proposal)
        print("ONE-WAY: MFL returned XML status OK")
    except ManualSwapError as e:
        error = str(e)
        print("ONE-WAY: POST response classification: " + error)

    time.sleep(2)
    after = read_back(opener, cookie)
    state = check_readback(after["starters"], original, proposal)
    if state == "APPLIED":
        print("ONE-WAY SUCCESS: Anthony Hill Jr. is STARTING; Cedric Gray is BENCHED.")
        print("ONE-WAY SUCCESS: all other 16 Week 11 starters unchanged; no restore attempted.")
    elif state == "UNCHANGED":
        print("ONE-WAY NO CHANGE: Cedric Gray still STARTING; Anthony Hill Jr. still BENCHED.")
        raise ManualSwapError("ONE-WAY: MFL did not save requested substitution")
    else:
        print("ONE-WAY CRITICAL: saved Week 11 starters differ from both expected lineups.")
        raise ManualSwapError("ONE-WAY: unexpected saved lineup, inspect MFL manually")
    if error:
        print("ONE-WAY NOTICE: MFL response was unexpected but authenticated readback confirms the swap")


if __name__ == "__main__":
    try:
        run()
    except (ManualSwapError, OwnerAuthError, LineupParseError, MFLAPIError,
            NFLScheduleError, ValueError) as exc:
        print("ONE-WAY STOPPED:", type(exc).__name__, str(exc))
        raise SystemExit(1) from None
