"""see.tg guest feed -> SQLite -> conservative comparable-sale assessments.
No keys, custody, purchases or Telegram sending. Run with --seconds 60 --output-dir capture.
"""
import argparse
import asyncio
import hashlib
import json
import math
import sqlite3
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

VERSION = "exact-traits-v1"
FIELDS = ("slug", "num", "title", "model", "backdrop", "pattern")

def normalize(raw, observed_at):
    if raw.get("type") != "event" or raw.get("event") not in ("sale", "listing", "price", "delisting"):
        return None
    gift = raw.get("gift") or {}
    if not gift.get("slug") or not isinstance(gift.get("num"), int):
        raise ValueError("Missing gift identity")
    timestamp = datetime.fromisoformat(raw["at"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Missing event timezone")
    at = timestamp.timestamp()
    if at > observed_at + 5:
        raise ValueError("Future timestamp")
    price = raw.get("price") or {}
    amount = price.get("amount")
    currency = price.get("currency")
    # Only directly TON-denominated events can enter the valuation model.
    ton = None
    if currency == "gram":
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValueError("Invalid TON price")
        ton = amount / 1_000_000_000
    clean = {"event": raw["event"], "at": at, "observed_at": observed_at,
             "market": raw.get("market"), "gift": {k:gift[k] for k in FIELDS if k in gift},
             "price": {"amount":amount, "currency":currency}, "price_ton":ton}
    identity = {k:clean[k] for k in ("event", "at", "market", "gift", "price")}
    clean["id"] = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return clean

def database(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, event TEXT, at REAL, observed REAL, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS assessments (event_id TEXT PRIMARY KEY, payload TEXT)")
    db.commit()
    return db

def store_event(db, event):
    cursor = db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                        (event["id"], event["event"], event["at"], event["observed_at"], json.dumps(event)))
    db.commit()
    return cursor.rowcount == 1

def trait_key(event):
    gift = event["gift"]
    fields = ("slug","model","backdrop","pattern")
    return tuple(gift[k] for k in fields) if all(gift.get(k) for k in fields) else None

def assess(db, listing):
    out = {"event_id":listing["id"], "model_version":VERSION, "listing":listing,
           "status":"REJECTED", "reasons":[], "estimated_fair_value_ton":None,
           "opportunity_score":None, "alert_eligible":False}
    if listing["price_ton"] is None:
        out["reasons"].append("NON_TON_LISTING")
    age = listing["observed_at"] - listing["at"]
    out["event_age_seconds"] = round(age,3)
    if age > 120:
        out["reasons"].append("STALE_LISTING_EVENT")
    key = trait_key(listing)
    if key is None:
        out["reasons"].append("MISSING_TRAITS")
    sales = []
    if key:
        for (payload,) in db.execute("SELECT payload FROM events WHERE event='sale' AND at>=? AND at<=? AND observed<=?",
            (listing["at"]-7*86400, listing["at"], listing["observed_at"])):
            sale = json.loads(payload)
            if sale["price_ton"] is not None and trait_key(sale)==key and sale["gift"]["num"]!=listing["gift"]["num"]:
                sales.append(sale)
    # At most one latest completed sale per OTHER gift.
    unique = {}
    for sale in sorted(sales,key=lambda s:s["at"]):
        unique[(sale["gift"]["slug"],sale["gift"]["num"])] = sale
    sales = list(unique.values())
    out["comparable_count"] = len(sales)
    out["comparables"] = [{"event_id":s["id"],"number":s["gift"]["num"],"at":s["at"],
                           "price_ton":s["price_ton"],"market":s["market"]} for s in sales]
    if len(sales)<5:
        out["reasons"].append("INSUFFICIENT_COMPARABLE_SALES")
    if out["reasons"]:
        return out
    prices = [s["price_ton"] for s in sales]
    fair = median(prices)
    dispersion = median(abs(p-fair) for p in prices)/fair
    discount = 1-listing["price_ton"]/fair
    out.update(estimated_fair_value_ton=fair,estimated_gross_discount=discount,
               relative_median_absolute_deviation=dispersion)
    if dispersion>0.25:
        out["reasons"].append("DISPERSED_COMPARABLES")
    if discount<0.15:
        out["reasons"].append("DISCOUNT_BELOW_THRESHOLD")
    if out["reasons"]:
        return out
    out["status"] = "RESEARCH_CANDIDATE"
    # Score components reflect observed evidence; no invented liquidity or cost assumptions.
    value = round(min(100,max(0,discount/0.30*100)))
    sample = round(min(100,len(sales)/10*100))
    consistency = round(max(0,1-dispersion/0.25)*100)
    out["score_components"] = {"value":value,"comparable_sample":sample,"price_consistency":consistency}
    out["research_score"] = round(0.5*value+0.25*sample+0.25*consistency)
    out["reasons"] = ["EXECUTION_COSTS_NOT_VERIFIED","LISTING_AVAILABILITY_NOT_REVERIFIED",
                      "SERIAL_PREMIUM_NOT_MODELED","VALUATION_MODEL_NOT_BACKTESTED"]
    return out

def export(db, directory, counters):
    events = [json.loads(p) for (p,) in db.execute("SELECT payload FROM events ORDER BY observed")]
    assessments = [json.loads(p) for (p,) in db.execute("SELECT payload FROM assessments")]
    reasons = Counter(reason for a in assessments for reason in a["reasons"])
    report = {"model_version":VERSION,"events":dict(Counter(e["event"] for e in events)),
              "session":dict(counters),"assessments":len(assessments),
              "research_candidates":sum(a["status"]=="RESEARCH_CANDIDATE" for a in assessments),
              "alerts_sent":0,"rejection_or_hold_reasons":dict(reasons)}
    (directory/"events.json").write_text(json.dumps(events,ensure_ascii=False,indent=2))
    (directory/"assessments.json").write_text(json.dumps(assessments,ensure_ascii=False,indent=2))
    (directory/"summary.json").write_text(json.dumps(report,indent=2))
    return report

async def capture(seconds, directory):
    import websockets
    directory.mkdir(parents=True,exist_ok=True)
    db = database(directory/"market.sqlite")
    counters = Counter()
    try:
        async with websockets.connect("wss://live.see.tg/v1/ws",open_timeout=10,max_size=1000000) as ws:
            await ws.send(json.dumps({"type":"subscribe","events":["sale","listing","price","delisting"]}))
            deadline = time.monotonic()+seconds
            while time.monotonic()<deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(),max(0.01,deadline-time.monotonic()))
                except asyncio.TimeoutError:
                    break
                try:
                    event = normalize(json.loads(raw),time.time())
                    if event is None:
                        continue
                    if not store_event(db,event):
                        counters["duplicates"]+=1
                        continue
                    counters["accepted"]+=1
                    if event["event"] in ("listing","price"):
                        result = assess(db,event)
                        db.execute("INSERT OR REPLACE INTO assessments VALUES (?,?)",(event["id"],json.dumps(result)))
                        db.commit()
                    if counters["accepted"]%25==0:
                        print("PROGRESS:",json.dumps(export(db,directory,counters)),flush=True)
                except (ValueError,TypeError,KeyError,OverflowError):
                    counters["malformed"]+=1
    finally:
        print("PIPELINE_RESULT:",json.dumps(export(db,directory,counters)),flush=True)
        db.close()

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds",type=int,default=60)
    parser.add_argument("--output-dir",type=Path,default=Path("capture"))
    args = parser.parse_args()
    if not 1<=args.seconds<=3600:
        parser.error("seconds must be between 1 and 3600")
    asyncio.run(capture(args.seconds,args.output_dir))
