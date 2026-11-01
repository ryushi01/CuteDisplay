#!/usr/bin/env python3
import unittest
from kitty_owner_session_v6 import issue_grant,verify_grant
class OwnerSessionTests(unittest.TestCase):
    def setUp(self):
        self.key=b"k"*32
        self.sid="trusted-session-123"
    def test_unverified_cannot_issue(self):
        with self.assertRaises(PermissionError):
            issue_grant(self.key,False,self.sid,now=1000)
    def test_valid_expiring_session(self):
        token=issue_grant(self.key,True,self.sid,now=1000,ttl=90)
        self.assertTrue(verify_grant(self.key,token,self.sid,now=1001))
        self.assertFalse(verify_grant(self.key,token,self.sid,now=1090))
        self.assertFalse(verify_grant(self.key,token,"other-session",now=1001))
        self.assertFalse(verify_grant(b"x"*32,token,self.sid,now=1001))
    def test_no_forged_owner_grant(self):
        token=issue_grant(self.key,True,self.sid,now=1000)
        self.assertFalse(verify_grant(self.key,token[:-3]+"AAA",self.sid,now=1001))
        self.assertFalse(verify_grant(self.key,"Shana",self.sid,now=1001))
if __name__=="__main__":unittest.main()
