"""Synthetic tests only. No network connection, MFL credentials or writes."""
import unittest
import urllib.request
from email.message import Message
from unittest.mock import patch
from src.mfl_owner_auth import owner_login, probe_owner_page, OwnerAuthError, MFLOnlyRedirects


class FakeResponse:
    def __init__(self, body, url, cookies=None):
        self._body = body
        self.url = url
        self.headers = Message()
        for cookie in cookies or []:
            self.headers.add_header("Set-Cookie", cookie)

    def read(self, size):
        return self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.response


class TestOwnerLogin(unittest.TestCase):
    def test_posted_password_never_in_url_and_xml_cookie_used(self):
        opener = FakeOpener(FakeResponse(
            b'<status MFL_USER_ID="test+/=token">OK</status>',
            "https://api.myfantasyleague.com/2026/login"))
        result = owner_login(opener, "2026", "private-user", "private-password", "40298")
        self.assertEqual(result, "MFL_USER_ID=test+/=token")
        self.assertEqual(opener.requests[0].get_method(), "POST")
        self.assertNotIn("private-password", opener.requests[0].full_url)
        self.assertIn(b"PASSWORD=private-password", opener.requests[0].data)

    def test_header_cookie_used_if_present(self):
        opener = FakeOpener(FakeResponse(
            b'<status>OK</status>',
            "https://api.myfantasyleague.com/2026/login",
            ["MFL_USER_ID=opaque; Path=/; Secure", "MFL_PW_SEQ=2; Path=/; Secure"]))
        result = owner_login(opener, "2026", "usr", "pwd", "40298")
        self.assertIn("MFL_USER_ID=opaque", result)
        self.assertIn("MFL_PW_SEQ=2", result)

    def test_rejected_credentials_generic_error_only(self):
        opener = FakeOpener(FakeResponse(
            b'<error>Invalid Password for private-user</error>',
            "https://api.myfantasyleague.com/2026/login"))
        with self.assertRaises(OwnerAuthError) as caught:
            owner_login(opener, "2026", "private-user", "private-password", "40298")
        self.assertNotIn("private", str(caught.exception))
        self.assertIn("rejected", str(caught.exception))

    def test_import_post_redirect_is_rejected_before_method_change(self):
        request = urllib.request.Request(
            "https://www46.myfantasyleague.com/2026/import?TYPE=lineup&L=40298",
            data=b"W=11&STARTERS=101%2C102", method="POST",
            headers={"Cookie": "MFL_USER_ID=fake"},
        )
        with self.assertRaisesRegex(OwnerAuthError, "POST payload"):
            MFLOnlyRedirects().redirect_request(
                request, None, 302, "Found", Message(),
                "https://www46.myfantasyleague.com/2026/lineup?L=40298",
            )

    def test_readonly_lineup_request_only_counts_markup(self):
        opener = FakeOpener(FakeResponse(
            b'<html><h1>Starting Lineups</h1><table><tr><td>SECRET PLAYER</td></tr></table></html>',
            "https://www46.myfantasyleague.com/2026/options?L=40298&O=06"))
        result = probe_owner_page(
            opener, "2026", "40298", "0001", "12", "MFL_USER_ID=test")
        self.assertEqual(opener.requests[0].get_method(), "GET")
        self.assertEqual(result["html_row_count"], 1)
        self.assertTrue(result["starting_lineups_heading"])
        self.assertNotIn("SECRET PLAYER", str(result))
        self.assertIn("MFL_USER_ID=test", opener.requests[0].headers["Cookie"])


if __name__ == "__main__":
    unittest.main()
