"""One-off lineup submission tests use synthetic requests only."""
import unittest
from email.message import Message

from src.manual_lineup_test import (
    single_swap, check_approval, submit_full_lineup, ManualSwapError,
)


class Response:
    def __init__(self,body=b"<status>OK</status>",status=200):
        self.body=body
        self.status=status
        self.headers=Message()
    def read(self,size):
        return self.body[:size]
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False


class Opener:
    def __init__(self,response):
        self.response=response
        self.calls=[]
    def open(self,request,timeout=None):
        self.calls.append(request)
        return self.response


class TestExplicitLineupSwap(unittest.TestCase):
    def test_one_change_preserves_all_other_16(self):
        start=[str(i) for i in range(101,118)]
        proposal=single_swap(start,start+["200"],"101","200")
        self.assertEqual(len(proposal),17)
        self.assertEqual(set(start)-set(proposal),{"101"})
        self.assertEqual(set(proposal)-set(start),{"200"})

    def test_outgoing_must_be_current_starter(self):
        start=[str(i) for i in range(101,118)]
        with self.assertRaisesRegex(ManualSwapError,"not a current starter"):
            single_swap(start,start+["200"],"999","200")

    def test_replacement_must_be_available_and_not_selected(self):
        start=[str(i) for i in range(101,118)]
        with self.assertRaisesRegex(ManualSwapError,"not selectable"):
            single_swap(start,start,"101","200")
        with self.assertRaisesRegex(ManualSwapError,"already a starter"):
            single_swap(start,start,"101","102")

    def test_wrong_week_or_attempt_refuses_live(self):
        args=("LIVE","APPROVE 101 TO 200 WEEK 11","101","200","11","workflow_dispatch","1")
        self.assertTrue(check_approval(*args))
        with self.assertRaisesRegex(ManualSwapError,"approval"):
            check_approval("LIVE","APPROVE 101 TO 200 WEEK 12","101","200","11",
                           "workflow_dispatch","1")
        with self.assertRaisesRegex(ManualSwapError,"approval"):
            check_approval(*args[:-1],"2")
        self.assertFalse(check_approval("DRY_RUN","", "101","200","12","pull_request","1"))

    def test_submit_requires_full_starters_and_success_xml(self):
        opener=Opener(Response())
        result=submit_full_lineup(opener,"MFL_USER_ID=example","2026","40298","11",
                                  [str(x) for x in range(101,118)])
        self.assertTrue(result)
        self.assertEqual(len(opener.calls),1)
        req=opener.calls[0]
        self.assertEqual(req.get_method(),"POST")
        self.assertIn("TYPE=lineup",req.full_url)
        self.assertIn(b"STARTERS=101%2C102",req.data)
        self.assertIn(b"W=11",req.data)
        self.assertNotIn("MFL_USER_ID",req.full_url)

    def test_import_error_or_html_is_never_success(self):
        for body in (b"<error>Bad roster</error>",b"<html>login</html>",b"Not XML"):
            with self.subTest(body=body):
                opener=Opener(Response(body))
                with self.assertRaisesRegex(ManualSwapError,"MFL"):
                    submit_full_lineup(opener,"MFL_USER_ID=test","2026","40298","11",
                                      [str(x) for x in range(101,118)])


if __name__=="__main__":
    unittest.main()
