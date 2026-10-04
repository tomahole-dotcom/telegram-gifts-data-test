import json
import tempfile
import unittest
from pathlib import Path
from guest_pipeline import normalize,database,store_event,assess

def event(number,kind="sale",amount=10_000_000_000,at="2026-10-04T22:00:00+00:00",observed=1791151210):
    return normalize({"type":"event","event":kind,"at":at,"market":"mrkt",
        "price":{"amount":amount,"currency":"gram"},
        "gift":{"slug":"ScaredCat","num":number,"model":"A","backdrop":"B","pattern":"C"}},observed)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=database(Path(self.temp.name)/"test.sqlite")
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def test_duplicate_and_price_units(self):
        sale=event(1)
        self.assertEqual(sale["price_ton"],10)
        self.assertTrue(store_event(self.db,sale))
        again=dict(sale,observed_at=sale["observed_at"]+1)
        self.assertFalse(store_event(self.db,again))
    def test_no_own_sale_or_lookahead(self):
        for number in range(5):
            store_event(self.db,event(number))
        listing=event(0,"listing",7_000_000_000)
        self.assertEqual(assess(self.db,listing)["comparable_count"],4)
        store_event(self.db,event(6,at="2026-10-04T22:00:05+00:00"))
        self.assertEqual(assess(self.db,listing)["comparable_count"],4)
    def test_candidate_never_eligible_without_costs(self):
        for number in range(5):
            store_event(self.db,event(number))
        result=assess(self.db,event(99,"listing",7_000_000_000))
        self.assertEqual(result["status"],"RESEARCH_CANDIDATE")
        self.assertAlmostEqual(result["estimated_gross_discount"],0.3)
        self.assertFalse(result["alert_eligible"])
        self.assertIsNone(result["opportunity_score"])
    def test_stale_and_future_rejected(self):
        listing=event(99,"listing",observed=1791151500)
        self.assertIn("STALE_LISTING_EVENT",assess(self.db,listing)["reasons"])
        with self.assertRaises(ValueError):
            event(1,at="2026-10-04T22:10:00+00:00")
    def test_unknown_currency_never_valued(self):
        row=event(99,"listing")
        row["price_ton"]=None
        self.assertIn("NON_TON_LISTING",assess(self.db,row)["reasons"])

if __name__=="__main__":
    unittest.main()
