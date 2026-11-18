"""Read the submitted MFL lineup through the existing read-only league API key."""
import os
import time

from .lineup import LineupError, inspect_lineup
from .mfl import export, MFLAPIError


def main():
    league = os.environ.get("MFL_LEAGUE_ID", "").strip()
    franchise = os.environ.get("MFL_FRANCHISE_ID", "").strip()
    year = int(os.environ.get("MFL_SEASON", "2026"))
    week = int(os.environ.get("MFL_WEEK", "12"))
    api_key = os.environ.get("MFL_API_KEY", "")
    if league != "40298" or franchise != "0001":
        raise ValueError("Lineup probe restricted to authorized CFFL Dynasty franchise 0001")
    if not api_key:
        raise ValueError("MFL_API_KEY secret is missing")
    print(f"LINEUP PROBE: league {league}, franchise {franchise}, season {year}, week {week}")
    print("OWNER_WRITE_AUTH_CONFIGURED=" + ("yes" if os.environ.get("MFL_USER_ID") else "no"))
    feeds = {}
    for kind in ("rosters", "players", "weeklyResults"):
        feeds[kind] = export(year, kind, league, api_key, week=week if kind == "weeklyResults" else None)
        if kind != "weeklyResults":
            time.sleep(2)
    lineup = inspect_lineup(feeds["weeklyResults"], feeds["rosters"], feeds["players"], franchise)
    print("VERIFIED SUBMITTED LINEUP (read only)")
    print("STARTERS:")
    for p in lineup["starters"]:
        print(f"  {p['id']} | {p['position']:>3} | {p['name']} | {p['team']}")
    print("ELIGIBLE BENCH:")
    for p in lineup["bench"]:
        print(f"  {p['id']} | {p['position']:>3} | {p['name']} | {p['team']}")
    print(f"READ_RESULT: {len(lineup['starters'])} starters, {len(lineup['bench'])} bench players.")
    print("NO MFL lineup change was submitted.")


if __name__ == "__main__":
    main()
