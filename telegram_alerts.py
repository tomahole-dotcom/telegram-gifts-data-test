"""Telegram alert rendering and guarded delivery. No BUY flow in this version."""
import html
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.request

def render(assessment, preview=True):
    listing=assessment["listing"]
    gift=listing["gift"]
    escape=lambda value: html.escape(str(value))
    title="🧪 ANALYSIS PREVIEW — NOT A BUY SIGNAL" if preview else "🎁 GIFT OPPORTUNITY"
    lines=[title,"", "<b>"+escape(gift.get("title",gift["slug"]))+" #"+escape(gift["num"])+"</b>"]
    price=listing.get("price_ton")
    lines.append("Listed: "+(f"{price:.4f} TON" if price is not None else "non-TON price"))
    fair=assessment.get("estimated_fair_value_ton")
    lines.append("Estimated fair value: "+(f"{fair:.4f} TON" if fair is not None else "insufficient comparable sales"))
    if fair is not None and assessment.get("estimated_gross_discount") is not None:
        lines.append(f"Estimated gross discount: {100*assessment['estimated_gross_discount']:.1f}%")
    comparables=assessment.get("comparables",[])
    lines.append("Comparable sales: "+str(assessment.get("comparable_count",len(comparables))))
    if comparables:
        lines.append(" / ".join(f"{c['price_ton']:.4f}" for c in comparables[:5])+" TON")
    score=assessment.get("opportunity_score")
    lines.append("Opportunity score: "+(f"{score}/100" if score is not None else "not validated"))
    for key,value in assessment.get("score_components",{}).items():
        lines.append(escape(key.replace("_"," ").title())+": "+escape(value))
    costs=assessment.get("estimated_total_cost_ton")
    lines.append("Estimated total costs: "+(f"{costs:.4f} TON" if costs is not None else "not verified"))
    lines.append("Source: see.tg · "+escape(listing.get("market","unknown")))
    lines.append("Event age at detection: "+escape(assessment.get("event_age_seconds","unknown"))+" sec")
    if assessment.get("reasons"):
        lines.append("Status: "+escape(", ".join(assessment["reasons"])))
    lines.extend(["","Estimated value is uncertain; profit is not guaranteed."])
    return "\n".join(lines)

def guard(assessment,now):
    if assessment.get("status")!="VERIFIED_OPPORTUNITY" or assessment.get("alert_eligible") is not True:
        raise ValueError("Opportunity not eligible")
    if assessment.get("reasons"):
        raise ValueError("Unresolved valuation or execution holds")
    if not 0 <= now-assessment["listing"]["observed_at"] <= 120:
        raise ValueError("Stale assessment")
    verification=assessment.get("availability_verification",{})
    if verification.get("available") is not True or not verification.get("source"):
        raise ValueError("Availability not reverified")
    if not 0 <= now-verification.get("verified_at",0) <= 30:
        raise ValueError("Stale availability verification")
    if verification.get("price_ton")!=assessment["listing"].get("price_ton"):
        raise ValueError("Listing price changed")
    for field in ("estimated_fair_value_ton","estimated_total_cost_ton","opportunity_score"):
        value=assessment.get(field)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError("Missing verified numeric field")
    if assessment["estimated_total_cost_ton"]<0 or not assessment.get("costs_verified"):
        raise ValueError("Costs not verified")
    if not 0<=assessment["opportunity_score"]<=100:
        raise ValueError("Invalid score")
    if assessment.get("comparable_count",0)<5:
        raise ValueError("Insufficient comparable sales")

def telegram_send(token,chat_id,text):
    request=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",
        data=json.dumps({"chat_id":chat_id,"text":text,"parse_mode":"HTML",
                         "link_preview_options":{"is_disabled":True}}).encode(),
        headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=15) as response:
            result=json.loads(response.read(100000))
        if not result.get("ok"):
            raise RuntimeError("Telegram rejected message")
        return result["result"]["message_id"]
    except Exception:
        # Never expose request URLs (which contain the bot token) or response bodies.
        raise RuntimeError("Telegram delivery failed; outcome requires review") from None

def deliver(db,assessment,token,chat_id,transport=telegram_send,now=None):
    now=time.time() if now is None else now
    guard(assessment,now)
    if not token or not chat_id:
        raise ValueError("Dedicated Gifts bot credentials missing")
    db.execute("CREATE TABLE IF NOT EXISTS alert_delivery (event_id TEXT, destination TEXT, state TEXT, attempted REAL, message_id INTEGER, PRIMARY KEY(event_id,destination))")
    try:
        db.execute("INSERT INTO alert_delivery VALUES (?,?,?,?,?)",
                   (assessment["event_id"],str(chat_id),"pending",now,None))
        db.commit()
    except sqlite3.IntegrityError:
        return {"state":"already_attempted"}
    try:
        message_id=transport(token,chat_id,render(assessment,preview=False))
    except Exception:
        db.execute("UPDATE alert_delivery SET state='unknown' WHERE event_id=? AND destination=?",
                   (assessment["event_id"],str(chat_id)))
        db.commit()
        return {"state":"unknown"}
    db.execute("UPDATE alert_delivery SET state='sent',message_id=? WHERE event_id=? AND destination=?",
               (message_id,assessment["event_id"],str(chat_id)))
    db.commit()
    return {"state":"sent","message_id":message_id}

if __name__=="__main__":
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser()
    parser.add_argument("assessment_file",type=Path)
    parser.add_argument("--send",action="store_true")
    parser.add_argument("--ledger",type=Path,default=Path("alert-delivery.sqlite"))
    args=parser.parse_args()
    assessment=json.loads(args.assessment_file.read_text())
    if args.send:
        connection=sqlite3.connect(args.ledger)
        try:
            print(json.dumps(deliver(connection,assessment,os.environ.get("GIFTS_BOT_TOKEN"),
                                     os.environ.get("GIFTS_ALERT_CHAT_ID"))))
        except Exception:
            print("Delivery blocked or failed. Check eligibility and dedicated bot configuration.")
            raise SystemExit(1)
        finally:
            connection.close()
    else:
        print(render(assessment))
