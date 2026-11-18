"""Enrich cached public injury reports when the live MFL feed is unavailable.

Never alter the timestamp of the last successful MFL injury synchronization.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .news import enrich_reports, fetch_recent_news

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PATH = ROOT / "site/data/report.json"


def run():
    if not PUBLIC_PATH.exists():
        print("No verified public report; optional news refresh skipped.")
        return
    doc = json.loads(PUBLIC_PATH.read_text(encoding="utf-8"))
    leagues = doc.get("leagues")
    if not isinstance(leagues, list):
        raise RuntimeError("Cached report invalid; refusing news refresh")
    season = int(os.environ.get("MFL_SEASON") or "2026")
    for league in leagues:
        lid = str(league.get("id") or "")
        if not lid.isdigit():
            continue
        for alert in league.get("alerts", []):
            pid = str(alert.get("player_id") or "")
            if pid.isdigit():
                alert["mfl_news_url"] = (
                    f"https://www.myfantasyleague.com/{season}/news_articles?"
                    f"L={lid}&PLAYERS={pid}"
                )
    enrich_reports(leagues, fetch_recent_news(), checked_at=datetime.now(timezone.utc))
    PUBLIC_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    matched = sum(bool(a.get("news")) for league in leagues for a in league.get("alerts", []))
    print(f"Cached report news links updated; RSS headlines matched: {matched}.")
    print("Injury sync timestamp preserved. No MFL API call or email was sent.")


if __name__ == "__main__":
    run()
