"""Offline tests of NFL schedule validation and MFL code/lock filtering."""
import unittest
from datetime import datetime, timedelta, timezone
from src.nfl_week import parse_week_schedule, normalize_team, eligible_teams, NFLScheduleError

CODES = [
    ("ARI","ATL"),("BAL","BUF"),("CAR","CHI"),("CIN","CLE"),
    ("DAL","DEN"),("DET","GB"),("HOU","IND"),("JAX","KC"),
    ("LV","LAC"),("LAR","MIA"),("MIN","NE"),("NO","NYG"),
]


def schedule_at(when):
    events=[]
    for home,away in CODES:
        events.append({
            "date": when.isoformat().replace("+00:00","Z"),
            "competitions":[{"competitors":[
                {"team":{"abbreviation":home}},{"team":{"abbreviation":away}},
            ]}],
        })
    return {"season":{"year":2026},"week":{"number":12},"events":events}


class TestNFLWeek(unittest.TestCase):
    def test_week_and_team_mapping(self):
        kickoff=datetime(2026,11,19,23,15,tzinfo=timezone.utc)
        games=parse_week_schedule(schedule_at(kickoff),2026,12)
        self.assertEqual(len(games),24)
        self.assertEqual(normalize_team("GBP"),"GB")
        self.assertEqual(normalize_team("KCC"),"KC")
        self.assertEqual(normalize_team("SFO"),"SF")
        self.assertEqual(normalize_team("LVR"),"LV")
        self.assertEqual(normalize_team("JAC"),"JAX")
        self.assertEqual(normalize_team("WAS"),"WSH")

    def test_reject_wrong_week_and_partial_schedule(self):
        doc=schedule_at(datetime(2026,11,19,23,tzinfo=timezone.utc))
        with self.assertRaisesRegex(NFLScheduleError,"week mismatch"):
            parse_week_schedule(doc,2026,11)
        doc["events"].pop()
        with self.assertRaisesRegex(NFLScheduleError,"Incomplete"):
            parse_week_schedule(doc,2026,12)

    def test_lock_deadline_cushion(self):
        now=datetime(2026,11,19,23,0,tzinfo=timezone.utc)
        sched={"GB":now+timedelta(minutes=45),
               "KC":now+timedelta(minutes=5),
               "DAL":now-timedelta(minutes=3)}
        self.assertEqual(eligible_teams(sched,now),{"GB"})

    def test_duplicate_game_or_bad_code_rejected(self):
        doc=schedule_at(datetime(2026,11,19,23,tzinfo=timezone.utc))
        doc["events"][1]["competitions"][0]["competitors"][0]["team"]["abbreviation"]="ARI"
        with self.assertRaisesRegex(NFLScheduleError,"duplicates"):
            parse_week_schedule(doc,2026,12)


if __name__=="__main__":
    unittest.main()
