"""CFFL automated injury guard, using the proven authenticated native MFL form.

Default is DRY_RUN. LIVE is permitted only on a scheduled main-branch run
with an explicit enable switch. A single guarded POST is followed by a
new authenticated readback. Never automatically rollback or retry a write.
"""
import os
import time
from datetime import datetime, timezone
from .auto_lineup_policy import select_replacements, AutoLineupError
from .auto_lineup_schedule import discover_current_nfl_week, check_due
from .mfl import fetch_all, MFLAPIError
from .mfl_owner_auth import _make_opener, owner_login, OwnerAuthError
from .live_lineup_dry_run import fetch_authenticated_lineup
from .submitted_lineup import extract_submitted_lineup, LineupParseError
from .mfl_native_lineup import prepare_post, submit_native
from .manual_lineup_test import ManualSwapError
from .recent_scores import recent_scores_for_week, rank_recent_weekly, RecentScoresError
from .nfl_week import fetch_espn_week, eligible_teams, NFLScheduleError
from .reversible_lineup_test import verify_list
from .model import as_list
from .notify import send_resend

YEAR, LEAGUE, FRANCHISE = 2026, "40298", "0001"


class AutoGuardFailure(RuntimeError):
    pass


def live_allowed(env):
    return (
        env.get("LINEUP_AUTOMATION_MODE") == "LIVE"
        and env.get("LINEUP_WRITE_ENABLED", "").lower() == "true"
        and env.get("GITHUB_EVENT_NAME") == "schedule"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_REPOSITORY") == "williamsbryce/fantasy-injury-watch"
        and env.get("GITHUB_RUN_ATTEMPT") == "1"
    )


def get_session(opener, username, password):
    try:
        return owner_login(opener, str(YEAR), username, password, LEAGUE)
    except OwnerAuthError as ex:
        if "returned html instead of valid XML" not in str(ex):
            raise
        print("AUTO GUARD: transient login HTML; one pre-write login retry")
        time.sleep(8)
        return owner_login(opener, str(YEAR), username, password, LEAGUE)


def get_form(opener, cookie, week):
    html = fetch_authenticated_lineup(
        str(YEAR), LEAGUE, FRANCHISE, opener, cookie, week=str(week),
        week_param="WEEK",
    )
    form = extract_submitted_lineup(html, expected_starters=17)
    if form["form_week_values"] != [week]:
        raise AutoGuardFailure("MFL returned lineup for unexpected week")
    return html, form


def check_injury_freshness(feeds, now):
    root = feeds.get("injuries", {}).get("injuries")
    if not isinstance(root, dict):
        raise AutoGuardFailure("MFL injury report missing")
    raw = str(root.get("timestamp") or "")
    try:
        stamp = datetime.fromtimestamp(int(raw), timezone.utc)
        age = (now - stamp).total_seconds()
    except (ValueError, OverflowError, OSError):
        raise AutoGuardFailure("Cannot verify MFL injury feed freshness") from None
    if not (-300 <= age <= 4 * 3600):
        raise AutoGuardFailure("MFL injury feed is stale or has a future timestamp")


def out_starter_ids(starters, feeds):
    root = feeds.get("injuries", {}).get("injuries")
    if not isinstance(root, dict) or "injury" not in root:
        raise AutoGuardFailure("Current injury designations unavailable")
    statuses = {str(p.get("id")): str(p.get("status") or "").lower().strip().replace("_", " ")
                for p in as_list(root["injury"]) if isinstance(p, dict)}
    from .lineup_replacements import OUT_DESIGNATIONS
    return [pid for pid in starters if statuses.get(pid, "") in OUT_DESIGNATIONS]


def status_email(week, status, changes, unresolved, info=""):
    lines = [
        f"CFFL Dynasty: Week {week} automatic starting-lineup safety check",
        f"Status: {status}",
        "",
    ]
    if changes:
        lines.append("Confirmed changes:" if status == "VERIFIED" else "Proposed changes:")
        for c in changes:
            lines.append(
                f"- {c['out_name']} OUT -> {c['in_name']} IN "
                f"({c['position']}; recent {c['recent_average']} pts/game "
                f"over {c['recent_games']} scored game(s))"
            )
        lines.append("")
    if unresolved:
        lines.append("Out starters still unresolved:")
        for c in unresolved:
            lines.append(f"- {c['name']}: {c['reason'].replace('_', ' ')}")
        lines.append("")
    if info:
        lines.append(info)
    lines.append("")
    lines.append("Open MFL to verify or adjust your lineup:")
    lines.append(f"https://www46.myfantasyleague.com/{YEAR}/lineup?L={LEAGUE}&FRANCHISE={FRANCHISE}&WEEK={week}")
    return "\n".join(lines)


def notify_owner(env, subject, message):
    key = env.get("RESEND_API_KEY") or ""
    sender = env.get("ALERT_FROM") or ""
    recipient = env.get("ALERT_TO") or ""
    if not (key and sender and recipient):
        raise AutoGuardFailure("Missing critical lineup email notification configuration")
    send_resend(key, sender, recipient, subject, message)
    print("AUTO GUARD: alert email accepted by notification provider")


def run(env=None, now=None):
    env = env or os.environ
    now = now or datetime.now(timezone.utc)
    mode = env.get("LINEUP_AUTOMATION_MODE", "DRY_RUN").upper()
    if mode not in {"DRY_RUN", "LIVE"}:
        raise AutoGuardFailure("Unsupported automatic lineup mode")
    if mode == "LIVE" and not live_allowed(env):
        raise AutoGuardFailure("LIVE lineup writes are not authorized in this workflow")
    if env.get("GITHUB_REPOSITORY") != "williamsbryce/fantasy-injury-watch":
        raise AutoGuardFailure("Unexpected repository")
    if str(env.get("MFL_SEASON", "2026")) != str(YEAR):
        raise AutoGuardFailure("Unexpected league season")
    if env.get("MFL_LEAGUE_ID", LEAGUE) != LEAGUE or \
            env.get("MFL_FRANCHISE_ID", FRANCHISE).zfill(4) != FRANCHISE:
        raise AutoGuardFailure("Unexpected league or franchise")

    week = None
    changed = []
    unresolved = []
    sent_post = False
    try:
        week = discover_current_nfl_week(YEAR)
        schedule = fetch_espn_week(YEAR, week)
        due = check_due(schedule, now, force_dry_run=(
            mode == "DRY_RUN" and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        ))
        if not due["due"]:
            print("AUTO GUARD: outside single Thursday/Sunday pregame window",
                  "reason=", due["reason"], "no MFL reads or changes")
            return {"status": "not_due", "week": week}
        print("AUTO GUARD: week=", week, "mode=", mode,
              "schedule_gate=", due["reason"])
        username = env.get("MFL_OWNER_USERNAME") or ""
        password = env.get("MFL_OWNER_PASSWORD") or ""
        api_key = env.get("MFL_API_KEY") or ""
        if not all((username, password, api_key)):
            raise AutoGuardFailure("Missing MFL owner session or API credentials")
        if mode == "LIVE" and not all(env.get(k) for k in
                                      ("RESEND_API_KEY", "ALERT_FROM", "ALERT_TO")):
            raise AutoGuardFailure("Missing critical alert settings; live writes disabled")

        opener = _make_opener()
        cookie = get_session(opener, username, password)
        _, initial = get_form(opener, cookie, week)
        original = initial["starters"]
        feeds = fetch_all(YEAR, LEAGUE, api_key, env.get("MFL_CLIENT_NAME") or "FantasyInjuryWatch")
        check_injury_freshness(feeds, now)

        if not out_starter_ids(original, feeds):
            print("AUTO GUARD: no confirmed Out/Inactive starters; no change needed")
            return {"status": "healthy", "week": week}

        # Recent scores are collected only when an Out starter needs coverage.
        historical = recent_scores_for_week(
            YEAR, LEAGUE, api_key, week, env.get("MFL_CLIENT_NAME") or "FantasyInjuryWatch")
        roster = feeds["rosters"]["rosters"]
        our_row = next((r for r in as_list(roster.get("franchise"))
                        if isinstance(r, dict) and str(r.get("id") or "").zfill(4) == FRANCHISE), None)
        if not our_row:
            raise AutoGuardFailure("MFL active roster unavailable for scoring selection")
        candidate_ids = [str(p["id"]) for p in as_list(our_row.get("player"))
                         if isinstance(p, dict) and p.get("id") is not None]
        recent = rank_recent_weekly(historical, candidate_ids)
        eligible = eligible_teams(schedule, now=now, cushion_minutes=5)
        plan = select_replacements(
            original, initial["all_selectable"], feeds, recent, eligible, FRANCHISE)
        changed = plan["changes"]
        unresolved = plan["unresolved"]
        print("AUTO GUARD: actionable swaps=", len(changed),
              "unresolved Out starters=", len(unresolved))
        if mode == "DRY_RUN":
            print("AUTO GUARD: DRY RUN. No lineup submission.")
            for c in changed:
                print("  propose", c["out_name"], "->", c["in_name"],
                      "recent average=", c["recent_average"], "games=", c["recent_games"])
            return {"status": "dry_run", "week": week, "plan": plan}
        if changed:
            # Re-read authenticated form immediately before single write.
            html, current = get_form(opener, cookie, week)
            if current["starters"] != original:
                raise AutoGuardFailure("Owner changed lineup during evaluation; no overwrite")
            replan = select_replacements(
                current["starters"], current["all_selectable"], feeds, recent,
                eligible_teams(schedule, now=datetime.now(timezone.utc), cushion_minutes=5),
                FRANCHISE)
            if replan["proposed_lineup"] != plan["proposed_lineup"] or \
                    replan["changes"] != changed:
                raise AutoGuardFailure("Replacement selection changed before submission")
            changes = [(c["out_player_id"], c["in_player_id"]) for c in changed]
            action, payload = prepare_post(
                html, originals=original, proposed=plan["proposed_lineup"],
                changes=changes, expected_week=week)
            sent_post = True
            response = submit_native(opener, cookie, action, payload, week=week)
            print("AUTO GUARD: native POST HTTP status=", response["http_status"])
            time.sleep(2)
            _, verified = get_form(opener, cookie, week)
            if not verify_list(verified["starters"], plan["proposed_lineup"]):
                raise AutoGuardFailure(
                    "CRITICAL: write sent but saved lineup readback did not match proposal"
                )
            print("AUTO GUARD: confirmed native MFL save; unchanged starters preserved")
        if changed or unresolved:
            details = status_email(
                week, "VERIFIED" if changed else "ACTION REQUIRED",
                changed, unresolved,
                "All reported substitutions have been verified in MFL." if changed else
                "No eligible replacement could be found. Please check manually."
            )
            notify_owner(env,
                         f"Fantasy Injury Watch | Week {week} " +
                         ("Lineup changed" if changed else "Out starter needs attention"),
                         details)
        return {"status": "verified" if changed else "unresolved", "week": week,
                "changes": changed, "unresolved": unresolved}
    except (AutoGuardFailure, AutoLineupError, OwnerAuthError, LineupParseError,
            MFLAPIError, RecentScoresError, NFLScheduleError, ManualSwapError,
            ValueError, RuntimeError) as ex:
        print("AUTO GUARD: safety stop category=", type(ex).__name__,
              "reason=", str(ex))
        # A sent POST may have succeeded even if the readback failed.
        # Never claim the saved lineup remained unchanged after an ambiguous POST.
        if week is not None and mode == "LIVE":
            message = status_email(
                week, "UNVERIFIED WRITE - CHECK MFL" if sent_post else "AUTOMATION UNAVAILABLE",
                changed, unresolved,
                "A write was attempted but its saved result could not be verified; "
                "check the MFL starting lineup now." if sent_post else
                "No lineup write was attempted; check your starting lineup manually."
            )
            notify_owner(env, f"Fantasy Injury Watch | Week {week} IMPORTANT: check lineup", message)
        raise


if __name__ == "__main__":
    run()
