"""One-shot, pregame, reversible engineering test. NO automated weekly use.

The one authorized test pair is Cedric Gray -> Anthony Hill Jr. (TEN, LB).
This is NOT an injury-based replacement recommendation.
Owner's existing 17 starters are saved and restored within the same job.
"""
import os
import time
from datetime import datetime, timedelta, timezone

from .mfl import export, MFLAPIError
from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .live_lineup_dry_run import fetch_authenticated_lineup
from .manual_lineup_test import (
    read_week_lineup, single_swap, submit_full_lineup, ManualSwapError,
)
from .submitted_lineup import LineupParseError
from .nfl_week import fetch_espn_week, normalize_team, NFLScheduleError
from .model import as_list, friendly_name

YEAR, LEAGUE, FRANCHISE, WEEK = "2026", "40298", "0001", "11"
OUT_NAME, IN_NAME = "Cedric Gray", "Anthony Hill Jr."
POSITION, NFL_TEAM = "LB", "TEN"
EXPECTED_STARTERS = 17


def validate_one_shot_environment(env):
    if (env.get("GITHUB_EVENT_NAME") != "push" or
        env.get("GITHUB_REF") != "refs/heads/feature/out-starter-guard" or
        env.get("GITHUB_RUN_ATTEMPT") != "1" or
        env.get("GITHUB_RUN_NUMBER") != "1" or
        env.get("GITHUB_REPOSITORY") != "williamsbryce/fantasy-injury-watch" or
        env.get("GITHUB_ACTOR") != "williamsbryce" or
        env.get("LIVE_REVERSIBLE_TEST") != "AUTHORIZED_CEDRIC_GRAY_TO_ANTHONY_HILL_WEEK_11"):
        raise ManualSwapError("One-shot authorization failed; no changes permitted")


def identify_pair(before, rosters, players, schedule, now=None):
    now = now or datetime.now(timezone.utc)
    if before["form_week_values"] != [11]:
        raise ManualSwapError("Lineup page is not for current Week 11")
    originals = list(before["starters"])
    if len(originals) != EXPECTED_STARTERS:
        raise ManualSwapError("Existing starter count changed; no action")
    franchise = next((f for f in as_list(rosters.get("rosters", {}).get("franchise"))
                      if str(f.get("id") or "").zfill(4) == FRANCHISE), None)
    if not isinstance(franchise, dict):
        raise ManualSwapError("Owner roster not found")
    roster = {str(p.get("id")): p for p in as_list(franchise.get("player"))
              if isinstance(p, dict) and p.get("id") is not None}
    identity = {str(p.get("id")): p for p in as_list(players.get("players", {}).get("player"))
                if isinstance(p, dict) and p.get("id") is not None}
    if any(pid not in roster or pid not in identity for pid in originals):
        raise ManualSwapError("Saved starters cannot be reconciled to active roster")

    def lookup(name):
        hits = [pid for pid, p in identity.items()
                if friendly_name(p.get("name")) == name and pid in roster]
        if len(hits) != 1:
            raise ManualSwapError("Target or bench player identity ambiguous")
        pid = hits[0]
        player = identity[pid]
        if str(player.get("position") or "").upper() != POSITION or normalize_team(player.get("team")) != NFL_TEAM:
            raise ManualSwapError("Expected same-position, same-team player identity has changed")
        if str(roster[pid].get("status") or "").upper().replace(" ", "_") in {
            "IR", "INJURED_RESERVE", "TAXI", "TAXI_SQUAD"
        }:
            raise ManualSwapError("Player is not on the active roster")
        return pid

    outgoing, incoming = lookup(OUT_NAME), lookup(IN_NAME)
    if outgoing not in originals or incoming in originals:
        raise ManualSwapError("The authorized starter/bench pair is not available")
    if incoming not in before["all_selectable"]:
        raise ManualSwapError("Incoming player is not selectable on MFL lineup form")
    if not isinstance(schedule, dict) or NFL_TEAM not in schedule:
        raise ManualSwapError("Tennessee game not verifiably scheduled this week")
    kickoff = schedule[NFL_TEAM]
    if kickoff <= now + timedelta(hours=4):
        raise ManualSwapError("Too close to Tennessee kickoff for a reversible test")
    proposed = single_swap(originals, before["all_selectable"], outgoing, incoming)
    return originals, proposed


def verify_list(actual, expected):
    return (len(actual) == len(expected) == EXPECTED_STARTERS and
            set(actual) == set(expected) and len(set(actual)) == EXPECTED_STARTERS)


def run():
    validate_one_shot_environment(os.environ)
    username, password = os.environ.get("MFL_OWNER_USERNAME"), os.environ.get("MFL_OWNER_PASSWORD")
    api_key = os.environ.get("MFL_API_KEY")
    if not all((username, password, api_key)):
        raise ManualSwapError("Owner login or API key not available")
    opener = _make_opener()
    cookie = owner_login(opener, YEAR, username, password, LEAGUE)
    first = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
    roster = export(int(YEAR), "rosters", LEAGUE, api_key)
    time.sleep(2)
    players = export(int(YEAR), "players", LEAGUE, api_key)
    schedule = fetch_espn_week(int(YEAR), int(WEEK))
    original, proposal = identify_pair(first, roster, players, schedule)
    # Re-fetch just before any live submission to detect concurrent edits.
    second = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
    if second["starters"] != original or second["form_week_values"] != [11]:
        raise ManualSwapError("Lineup changed before test, no write submitted")
    print("TEST: Week 11, 17 starters verified, approved same-team LB pair identified.")
    print("TEST: snapshot of original lineup kept in this runner's memory.")
    changed = False
    observed_new = False
    restored = False
    try:
        # A network failure here is ambiguous: MFL may have accepted the POST.
        changed = True
        print("TEST: submitting exactly one replacement, preserving the other 16 starters.")
        try:
            submit_full_lineup(opener, cookie, YEAR, LEAGUE, WEEK, proposal)
            print("TEST: MFL returned XML success for replacement.")
        except ManualSwapError:
            print("TEST: replacement response was not confirmed; inspecting live page before restoration.")
        time.sleep(2)
        after = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
        if verify_list(after["starters"], proposal):
            observed_new = True
            print("TEST: replacement appeared on authenticated MFL Week 11 lineup page.")
        elif verify_list(after["starters"], original):
            print("TEST: replacement NOT seen on MFL; original still selected.")
            raise ManualSwapError("Replacement not applied; original lineup unchanged")
        else:
            raise ManualSwapError("CRITICAL: unexpected third lineup state after write")
    finally:
        if changed:
            # Always inspect first: do not overwrite an independently edited lineup.
            current = None
            try:
                current = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
            except (OwnerAuthError, LineupParseError, ManualSwapError):
                print("TEST: unable to re-read; attempting original-lineup recovery.")
            if current is not None and verify_list(current["starters"], original):
                restored = True
                print("RESTORE: original 17 starters already selected; no second write needed.")
            elif current is not None and not verify_list(current["starters"], proposal):
                raise ManualSwapError(
                    "CRITICAL: unknown lineup state, refusing to overwrite possible owner edits"
                )
            else:
                print("RESTORE: resubmitting exact original 17 starters.")
                try:
                    submit_full_lineup(opener, cookie, YEAR, LEAGUE, WEEK, original)
                    print("RESTORE: MFL returned XML success.")
                except ManualSwapError:
                    print("RESTORE: MFL success response missing; verifying actual lineup.")
                time.sleep(2)
                last = read_week_lineup(opener, YEAR, LEAGUE, FRANCHISE, WEEK, cookie)
                if not verify_list(last["starters"], original):
                    raise ManualSwapError(
                        "CRITICAL: restoration NOT confirmed, inspect Week 11 lineup immediately"
                    )
                restored = True
                print("RESTORE: 17 original Week 11 starters verified on MFL.")
    if not observed_new:
        raise ManualSwapError("MFL substitution was not confirmed; restoration checked")
    if not restored:
        raise ManualSwapError("CRITICAL: original lineup restoration could not be confirmed")
    print("SUCCESS: one genuine live MFL swap and full original-lineup restoration verified.")


if __name__ == "__main__":
    try:
        run()
    except (ManualSwapError, OwnerAuthError, LineupParseError, MFLAPIError, NFLScheduleError) as exc:
        # No user IDs, cookies, secrets or response bodies appear in diagnostic errors.
        print("REVERISIBLE TEST STOPPED:", type(exc).__name__, str(exc))
        raise SystemExit(1) from None
