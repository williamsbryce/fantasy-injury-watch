import unittest
from datetime import datetime, timezone
from src.crypto import encrypt, decrypt
from src.model import parse_report, status_group, friendly_name
from src.notify import urgent_new_alerts, digest_key

LEAGUE={"platform":"mfl","name":"CFFL Dynasty","id":"12345","franchise_id":"0001","season":2026}
FIXTURE={
 "rosters":{"rosters":{"franchise":[{"id":"0001","player":[{"id":"111","status":"ROSTER"},{"id":"222","status":"INJURED_RESERVE"},{"id":"333","status":"ROSTER"}]},{"id":"0002","player":{"id":"444"}}]}},
 "players":{"players":{"player":[{"id":"111","name":"Smith, Test","position":"WR","team":"CHI"},{"id":"222","name":"Jones, Sample","position":"RB","team":"NYG"},{"id":"333","name":"Person, Healthy","position":"QB","team":"KC"},{"id":"444","name":"Someone, Else","position":"TE","team":"DET"}]}},
 "injuries":{"injuries":{"timestamp":"2026-11-17T13:00:00Z","injury":[{"id":"111","status":"Questionable","details":"Hamstring"},{"id":"222","status":"Out","details":"Ankle"},{"id":"444","status":"Inactive","details":"Should be excluded"}]}}
}

class TestSync(unittest.TestCase):
 def test_roster_scoped_and_sorting(self):
  result=parse_report(FIXTURE,LEAGUE,datetime(2026,11,17,tzinfo=timezone.utc))
  self.assertEqual(result['players_checked'],2)
  self.assertEqual([a['name'] for a in result['alerts']],["Test Smith"])
  self.assertEqual(result['alerts'][0]['group'],'watch')
 def test_active_out_is_urgent(self):
  import copy
  modified=copy.deepcopy(FIXTURE)
  modified["rosters"]["rosters"]["franchise"][0]["player"][1]["status"]="ROSTER"
  result=parse_report(modified, LEAGUE)
  self.assertEqual([a["group"] for a in result["alerts"]],["action","watch"])
 def test_missing_player_mapping_does_not_report_healthy(self):
  modified={**FIXTURE,'players':{'players':{'player':[]}}}
  with self.assertRaisesRegex(ValueError,'incomplete'):parse_report(modified,LEAGUE)
 def test_status_classification(self):
  self.assertEqual(status_group('Out'),'action')
  self.assertEqual(status_group('Questionable'),'watch')
  self.assertEqual(status_group('Healthy'),'clear')
  self.assertEqual(status_group('Unexpected new designation'),'watch')
 def test_crypto_round_trip(self):
  phrase='something unique and long enough 123'
  doc={'leagues':[{'alerts':[{'name':'Testing'}]}]}
  enc=encrypt(doc,phrase)
  self.assertNotIn('Testing',str(enc))
  self.assertEqual(decrypt(enc,phrase),doc)
  with self.assertRaises(Exception):decrypt(enc,'another long enough password')
 def test_alert_not_repeated(self):
  now={'leagues':[{'alerts':[{'key':'x','status':'Out','group':'action'},{'key':'q','status':'Questionable','group':'watch'}]}]}
  self.assertEqual(len(urgent_new_alerts(now,{})),1)
  self.assertEqual(len(urgent_new_alerts(now,now)),0)
 def test_digests_regina(self):
  # 15:17 UTC = 09:17 Saskatchewan year-round.
  self.assertEqual(digest_key(datetime(2026,11,19,15,17,tzinfo=timezone.utc)),'2026-11-19')
  self.assertEqual(digest_key(datetime(2026,11,22,15,17,tzinfo=timezone.utc)),'2026-11-22')
  self.assertIsNone(digest_key(datetime(2026,11,18,15,17,tzinfo=timezone.utc)))

if __name__=='__main__':unittest.main()

class TestPipeline(unittest.TestCase):
 def test_end_to_end_pipeline_does_not_publish_plaintext(self):
  import json
  import os
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from src import main
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'report.enc.json'
   env={
    'MFL_API_KEY':'synthetic-test-key', 'REPORT_PASSPHRASE':'long-unique-testing-password-123',
    'MFL_LEAGUE_ID':'12345','MFL_FRANCHISE_ID':'0001',
    'RESEND_API_KEY':'','ALERT_FROM':'','ALERT_TO':'',
   }
   with patch.dict(os.environ,env),patch.object(main,'REPORT_PATH',path),patch.object(main,'fetch_all',return_value=FIXTURE):
    main.run()
   text=path.read_text()
   self.assertNotIn('Test Smith',text)
   self.assertNotIn('synthetic-test-key',text)
   decoded=decrypt(json.loads(text),env['REPORT_PASSPHRASE'])
   self.assertEqual(decoded['leagues'][0]['alerts'][0]['name'],'Test Smith')


class TestMFLResilience(unittest.TestCase):
 def test_transient_error_retried_without_exposing_key(self):
  from unittest.mock import patch
  from src.mfl import export
  import json
  class Response:
   def __init__(self, value):self.value=value
   def __enter__(self):return self
   def __exit__(self,*args):return None
   def read(self,n):return json.dumps(self.value).encode()
  responses=[Response({'error':{'$t':'Too many requests'}}),Response({'injuries':{'injury':[]}})]
  with patch('src.mfl.urllib.request.urlopen',side_effect=responses) as fetch,patch('src.mfl.time.sleep') as pause:
   result=export(2026,'injuries','40298','secret-test-value')
  self.assertIn('injuries',result)
  self.assertEqual(fetch.call_count,2)
  pause.assert_called_once()

 def test_auth_denial_is_not_retried(self):
  from unittest.mock import patch
  from src.mfl import export, MFLAPIError
  import json
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):return None
   def read(self,n):return json.dumps({'error':{'$t':'API requires logged in user'}}).encode()
  with patch('src.mfl.urllib.request.urlopen',return_value=Response()) as fetch:
   with self.assertRaisesRegex(MFLAPIError,'access denied'):
    export(2026,'injuries','40298','secret-test-value')
  self.assertEqual(fetch.call_count,1)
