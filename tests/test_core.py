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
 def test_end_to_end_public_report_has_no_api_key(self):
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
   with patch.dict(os.environ,env),patch.object(main,'REPORT_PATH',path),patch.object(main,'LEGACY_PATH',path.parent/'test-legacy.enc.json'),patch.object(main,'fetch_all',return_value=FIXTURE):
    main.run()
   text=path.read_text()
   self.assertIn('Test Smith',text)  # Public report, by user's explicit choice.
   self.assertNotIn('synthetic-test-key',text)
   decoded=json.loads(text)
   self.assertEqual(decoded['leagues'][0]['alerts'][0]['name'],'Test Smith')
   self.assertIn('mfl_news_url',decoded['leagues'][0]['alerts'][0])


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


class TestEmailTestMode(unittest.TestCase):
 def test_manual_email_test_sends_once_without_marking_digest(self):
  from pathlib import Path
  from tempfile import TemporaryDirectory
  from unittest.mock import patch
  import os, json
  from src import main
  with TemporaryDirectory() as td:
   path=Path(td)/'state.json'
   env={
    'MFL_API_KEY':'test-value','REPORT_PASSPHRASE':'a-very-long-testing-passphrase',
    'MFL_LEAGUE_ID':'12345','MFL_FRANCHISE_ID':'0001',
    'SEND_TEST_EMAIL':'true','RESEND_API_KEY':'test-provider-key',
    'ALERT_FROM':'onboarding@resend.dev','ALERT_TO':'test@example.com',
   }
   with patch.dict(os.environ,env),patch.object(main,'REPORT_PATH',path),patch.object(main,'LEGACY_PATH',path.parent/'test-legacy.enc.json'),patch.object(main,'fetch_all',return_value=FIXTURE),patch.object(main,'send_resend',return_value=True) as send:
    main.run()
   self.assertEqual(send.call_count,1)
   self.assertIn('Test email',send.call_args.args[3])
   state=json.loads(path.read_text())
   self.assertEqual(state.get('sent_digest_date'),'')
 def test_manual_email_requires_configuration(self):
  from pathlib import Path
  from tempfile import TemporaryDirectory
  from unittest.mock import patch
  import os
  from src import main
  with TemporaryDirectory() as td:
   env={
    'MFL_API_KEY':'test-value','REPORT_PASSPHRASE':'a-very-long-testing-passphrase',
    'MFL_LEAGUE_ID':'12345','MFL_FRANCHISE_ID':'0001',
    'SEND_TEST_EMAIL':'true','RESEND_API_KEY':'','ALERT_FROM':'','ALERT_TO':'',
   }
   with patch.dict(os.environ,env),patch.object(main,'REPORT_PATH',Path(td)/'report.json'),patch.object(main,'LEGACY_PATH',Path(td)/'legacy.enc.json'),patch.object(main,'fetch_all',return_value=FIXTURE):
    with self.assertRaisesRegex(RuntimeError,'Test email requested'):
     main.run()


class TestNotificationGating(unittest.TestCase):
 def test_credentials_alone_do_not_enable_emails(self):
  import os
  from pathlib import Path
  from tempfile import TemporaryDirectory
  from unittest.mock import patch
  from src import main
  with TemporaryDirectory() as td:
   env={'MFL_API_KEY':'sample-key','REPORT_PASSPHRASE':'a-very-long-testing-passphrase',
        'MFL_LEAGUE_ID':'12345','MFL_FRANCHISE_ID':'0001',
        'RESEND_API_KEY':'sample-mail-key','ALERT_FROM':'onboarding@resend.dev',
        'ALERT_TO':'test@example.com','EMAIL_ENABLED':'false','SEND_TEST_EMAIL':'false'}
   with patch.dict(os.environ,env),patch.object(main,'REPORT_PATH',Path(td)/'state.json'),patch.object(main,'LEGACY_PATH',Path(td)/'legacy.enc.json'),patch.object(main,'fetch_all',return_value=FIXTURE),patch.object(main,'send_resend') as sender:
    main.run()
   sender.assert_not_called()

 def test_safe_mfl_error_classification(self):
  from src.mfl import _error_category
  self.assertEqual(_error_category('Too many requests'), 'rate_limit')
  self.assertEqual(_error_category('Not authorized'), 'authorization')
  self.assertEqual(_error_category('Unexpected private response'), 'unclassified')

class TestResendErrorDiagnostics(unittest.TestCase):
 def test_http_error_reports_safe_code_not_provider_message(self):
  import io, json, urllib.error
  from unittest.mock import patch
  from src.notify import send_resend
  response={'name':'restricted_to_address','message':'private recipient and secret token 123'}
  error=urllib.error.HTTPError('https://api.resend.com/emails',403,'Forbidden',{},io.BytesIO(json.dumps(response).encode()))
  with patch('src.notify.urllib.request.urlopen',side_effect=error):
   with self.assertRaises(RuntimeError) as cm:
    send_resend('secret','onboarding@resend.dev','account@example.com','test','body')
  self.assertIn('HTTP 403, reason=restricted_to_address',str(cm.exception))
  self.assertNotIn('private recipient',str(cm.exception))
  self.assertNotIn('secret token',str(cm.exception))


class TestSafeResendReasonClassifier(unittest.TestCase):
 def test_nested_testing_restriction_is_classified_and_sensitive_text_hidden(self):
  import io, json, urllib.error
  from unittest.mock import patch
  from src.notify import send_resend
  response={'error':{'name':'validation_error','message':'You can only send testing emails to your own email address (private@example.com)'}}
  error=urllib.error.HTTPError('https://api.resend.com/emails',403,'Forbidden',{'Content-Type':'application/json'},io.BytesIO(json.dumps(response).encode()))
  with patch('src.notify.urllib.request.urlopen',side_effect=error):
   with self.assertRaises(RuntimeError) as cm:
    send_resend('private-secret','onboarding@resend.dev','private@example.com','test','body')
  self.assertIn('reason=test_recipient_restriction',str(cm.exception))
  self.assertIn('response=json',str(cm.exception))
  self.assertNotIn('private@example.com',str(cm.exception))
  self.assertNotIn('private-secret',str(cm.exception))

 def test_non_json_rejection_is_classified_as_html_without_body(self):
  import io, urllib.error
  from unittest.mock import patch
  from src.notify import send_resend
  error=urllib.error.HTTPError('https://api.resend.com/emails',403,'Forbidden',{'Content-Type':'text/html'},io.BytesIO(b'<html><body>private internal error</body></html>'))
  with patch('src.notify.urllib.request.urlopen',side_effect=error):
   with self.assertRaises(RuntimeError) as cm:
    send_resend('private-secret','onboarding@resend.dev','test@example.com','test','body')
  self.assertIn('reason=unclassified, response=html',str(cm.exception))
  self.assertNotIn('private internal error',str(cm.exception))


class TestNewsIntegration(unittest.TestCase):
 def test_player_news_attaches_to_exact_matching_player(self):
  from src.news import enrich_reports
  import copy
  document=parse_report(FIXTURE,LEAGUE)
  news=[
   {'title':'Test Smith: Limited at Wednesday practice','published':'Wed, 18 Nov 2026','url':'https://www.rotowire.com/football/player/test-smith-123','source':'RotoWire RSS'},
   {'title':'Different Person: Sitting out practice','published':'Wed, 18 Nov 2026','url':'https://www.rotowire.com/football/player/other-123','source':'RotoWire RSS'}
  ]
  enrich_reports([document],news)
  self.assertEqual(document['alerts'][0]['news'][0]['title'],news[0]['title'])
  self.assertIn('PLAYERS=111',document['alerts'][0]['mfl_news_url'])

 def test_feed_unavailable_does_not_remove_mfl_injury_alerts(self):
  from src.news import enrich_reports
  document=parse_report(FIXTURE,LEAGUE)
  enrich_reports([document],None)
  self.assertEqual(len(document['alerts']),1)
  self.assertEqual(document['alerts'][0]['news'],[])

 def test_rss_parsing_extracts_player_practice_headline_only(self):
  import io
  from unittest.mock import patch
  from src.news import fetch_recent_news
  xml=b'''<rss><channel>
    <item><title>Test Smith: Limited at practice</title><description>Expected to be questionable</description><link>https://www.rotowire.com/football/player/test-smith-123</link><pubDate>Wed, 18 Nov 2026 10:00:00 GMT</pubDate></item>
    <item><title>Another Player: Big game</title><description>No injury</description><link>https://www.rotowire.com/football/player/other-123</link></item>
  </channel></rss>'''
  class FakeResponse:
   def __enter__(self):return self
   def __exit__(self,*args):return None
   def read(self,n):return xml
  with patch('src.news.urllib.request.urlopen',return_value=FakeResponse()):
   result=fetch_recent_news()
  self.assertEqual(result[0]['title'],'Test Smith: Limited at practice')
  self.assertEqual(len(result),1)


class TestCachedNewsFallback(unittest.TestCase):
 def test_cache_enrichment_preserves_last_verified_injury_timestamp(self):
  import tempfile, json
  from pathlib import Path
  from unittest.mock import patch
  from src import enrich_cached
  with tempfile.TemporaryDirectory() as td:
   report=Path(td)/"public.json"
   doc={"schema":1,"synced_at":"2026-11-17T17:17:12Z","leagues":[parse_report(FIXTURE,LEAGUE)]}
   report.write_text(json.dumps(doc))
   with patch.object(enrich_cached,"PUBLIC_PATH",report),patch.object(enrich_cached,"fetch_recent_news",return_value=[]):
    enrich_cached.run()
   after=json.loads(report.read_text())
   self.assertEqual(after["synced_at"],doc["synced_at"])
   self.assertIn("PLAYERS=111",after["leagues"][0]["alerts"][0]["mfl_news_url"])
