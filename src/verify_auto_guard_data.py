"""One-off read-only production-data validation for the scheduled CFFL guard."""
import os
from .auto_lineup_schedule import discover_current_nfl_week
from .nfl_week import fetch_espn_week
from .recent_scores import fetch_week_scores, RecentScoresError
from .auto_lineup_guard import run

def main():
    year = 2026
    week = discover_current_nfl_week(year)
    schedule = fetch_espn_week(year, week)
    print("AUTO DATA SMOKE: current NFL week=", week,
          "scheduled teams=", len(schedule))
    key = os.environ.get("MFL_API_KEY") or ""
    if week > 1 and key:
        for past in (week - 1, max(1, week - 2)):
            scores = fetch_week_scores(year, "40298", key, past)
            print("AUTO DATA SMOKE: MFL league weekly scoring week=", past,
                  "valid_score_records=", len(scores))
    env = dict(os.environ)
    env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    env["LINEUP_AUTOMATION_MODE"] = "DRY_RUN"
    summary = run(env=env)
    print("AUTO DATA SMOKE: guard result=", summary.get("status"),
          "no native lineup POST or email performed.")

if __name__ == "__main__":
    main()
