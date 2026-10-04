import sqlite3
import unittest
from telegram_alerts import render,guard,deliver

def assessment():
    return {"event_id":"test","status":"VERIFIED_OPPORTUNITY","alert_eligible":True,
      "listing":{"observed_at":1000,"price_ton":7,"market":"mrkt",
                 "gift":{"title":"A < B","slug":"Example","num":1}},
      "estimated_fair_value_ton":10,"estimated_gross_discount":0.3,
      "estimated_total_cost_ton":0.5,"costs_verified":True,
      "opportunity_score":80,"comparable_count":5,"reasons":[],
      "availability_verification":{"available":True,"source":"test fixture",
                                    "verified_at":1000,"price_ton":7}}

class AlertTests(unittest.TestCase):
    def test_html_and_preview(self):
        text=render(assessment())
        self.assertIn("NOT A BUY SIGNAL",text)
        self.assertIn("A &lt; B",text)
        self.assertNotIn("[BUY]",text)
    def test_research_candidate_blocked(self):
        a=assessment(); a["status"]="RESEARCH_CANDIDATE"
        with self.assertRaises(ValueError): guard(a,1001)
    def test_price_change_and_missing_costs_blocked(self):
        a=assessment(); a["availability_verification"]["price_ton"]=8
        with self.assertRaises(ValueError): guard(a,1001)
        a=assessment(); a["costs_verified"]=False
        with self.assertRaises(ValueError): guard(a,1001)
    def test_stale_verification_blocked(self):
        with self.assertRaises(ValueError): guard(assessment(),1031)
    def test_send_once(self):
        db=sqlite3.connect(":memory:"); calls=[]
        transport=lambda *args: calls.append(args) or 42
        self.assertEqual(deliver(db,assessment(),"fixture","fixture",transport,1001)["state"],"sent")
        self.assertEqual(deliver(db,assessment(),"fixture","fixture",transport,1001)["state"],"already_attempted")
        self.assertEqual(len(calls),1)
        db.close()
    def test_uncertain_delivery_never_automatically_retried(self):
        db=sqlite3.connect(":memory:")
        def failure(*args): raise TimeoutError("secret must not appear")
        self.assertEqual(deliver(db,assessment(),"fixture","fixture",failure,1001),{"state":"unknown"})
        self.assertEqual(deliver(db,assessment(),"fixture","fixture",failure,1001),{"state":"already_attempted"})
        db.close()
if __name__=="__main__": unittest.main()
