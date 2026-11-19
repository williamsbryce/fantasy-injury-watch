"""Independently refresh current-week lineup roles in a cached public injury report.

This job is GET-only. It does not refresh injuries, change the injury sync
timestamp, send emails, or write any MFL lineup. If lineup/season identity
cannot be verified, it deliberately marks roles unverified.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .lineup_monitor import (
    EXPECTED_STARTERS, REGINA, current_week_context,
    fetch_weekly_lineup, submitted_starter_ids,
)

REPORT_PATH = Path(__file__).resolve().parent.parent / "site" / "data" / "report.json"
MAX_ROSTER_AGE = timedelta(hours=48)


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def apply_lineup_snapshot(document, league_id, franchise_id, context, payload, now=None):
    """Safely enrich cached injury alerts from a current, exact-week MFL lineup.

    Only a complete, explicit set of 17 starters may classify nonstarters
    as bench. The prior injury report must still identify a recent roster.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Current time must have a timezone")
    if not isinstance(document, dict) or not isinstance(document.get("leagues"), list):
        raise ValueError("Invalid published report")
    report_age = _time(document.get("synced_at"))
    roster_recent = (
        report_age is not None
        and timedelta(0) <= now - report_age <= MAX_ROSTER_AGE
    )
    for league in document["leagues"]:
        if not isinstance(league, dict):
            continue
        if str(league.get("id")) != str(league_id) or str(
            league.get("franchise_id", "")
        ).zfill(4) != str(franchise_id).zfill(4):
            continue
        info = {
            "state": "unknown",
            "week": context.get("week") if isinstance(context, dict) else None,
            "checked_at": now.isoformat(),
            "starters_count": None,
            "warning": None,
            "kickoff": None,
        }
        league["lineup"] = info
        for alert in league.get("alerts", []):
            if isinstance(alert, dict):
                alert["lineup_role"] = "unknown"

        if not context or not roster_recent or not isinstance(payload, dict):
            continue
        selected = submitted_starter_ids(payload, franchise_id)
        if selected is None:
            continue
        count = len(selected)
        info["starters_count"] = count
        if count == 0:
            info["state"] = "not_submitted"
        elif count != EXPECTED_STARTERS:
            info["state"] = "incomplete"
        else:
            info["state"] = "submitted"
            starters = set(selected)
            for alert in league.get("alerts", []):
                if isinstance(alert, dict) and str(alert.get("player_id", "")).isdigit():
                    alert["lineup_role"] = (
                        "starter" if str(alert["player_id"]) in starters else "bench"
                    )

        # Treat a missing current-week lineup as a warning only when the
        # published roster has a team in the first Thursday game close to kickoff.
        if info["state"] not in {"not_submitted", "incomplete"}:
            continue
        local_now = now.astimezone(REGINA)
        if local_now.weekday() not in (3, 6):
            continue
        upcoming = sorted(
            (game for game in context.get("games", []) if
             game["kickoff"].astimezone(REGINA).date() == local_now.date()
             and timedelta(0) < game["kickoff"] - now <= timedelta(hours=4)),
            key=lambda game: game["kickoff"],
        )
        if local_now.weekday() == 3:
            # Cached injury alerts do not describe all rostered players,
            # so cannot establish Thursday participation. Don't guess.
            continue
        if upcoming:
            info["kickoff"] = upcoming[0]["kickoff"].isoformat()
            info["warning"] = (
                f"Week {context['week']} has no submitted starting lineup in MFL."
                if info["state"] == "not_submitted" else
                f"Week {context['week']} has only {count} of "
                f"{EXPECTED_STARTERS} expected starters in MFL."
            )
    return document


def run():
    season = int(os.environ.get("MFL_SEASON") or "2026")
    league_id = os.environ.get("MFL_LEAGUE_ID", "").strip()
    franchise_id = os.environ.get("MFL_FRANCHISE_ID", "").strip()
    key = os.environ.get("MFL_API_KEY", "")
    if not league_id.isdigit() or not (len(franchise_id) == 4 and franchise_id.isdigit()):
        raise RuntimeError("Lineup monitor league configuration missing")
    if not key:
        raise RuntimeError("Lineup monitor API access is not configured")
    if not REPORT_PATH.exists():
        raise RuntimeError("No verified injury report to enrich")
    document = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if not any(str(l.get("id")) == league_id and
               str(l.get("franchise_id", "")).zfill(4) == franchise_id
               for l in document.get("leagues", []) if isinstance(l, dict)):
        raise RuntimeError("Cached report league identity mismatch")
    now = datetime.now(timezone.utc)
    context = current_week_context(season, now)
    payload = None
    if context is not None:
        payload = fetch_weekly_lineup(season, league_id, key, context["week"])
    apply_lineup_snapshot(document, league_id, franchise_id, context, payload, now)
    REPORT_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    league = next(l for l in document["leagues"] if str(l["id"]) == league_id)
    roles = {r: sum(a.get("lineup_role") == r for a in league.get("alerts", []))
             for r in ("starter", "bench", "unknown")}
    print("Read-only weekly lineup lookup:", league["lineup"]["state"],
          "classified injury alerts:", roles,
          "injury sync timestamp unchanged; no lineup write or email.")


if __name__ == "__main__":
    run()
