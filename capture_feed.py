"""Bounded market intake only. No valuation, alerts, credentials or trades."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from collections import Counter
from guest_pipeline import database, normalize, store_event

async def capture(seconds, directory):
    import websockets
    directory.mkdir(parents=True,exist_ok=True)
    db=database(directory/"market.sqlite")
    started=time.time()
    deadline=time.monotonic()+seconds
    counts=Counter()
    windows=[]
    def save():
        report={"started":started,"updated":time.time(),"requested_seconds":seconds,
                "counts":dict(counts),"connection_windows":windows,
                "sales_are_provider_reported":True,"replay_available":False,
                "assessments_run":0,"alerts_sent":0}
        target=directory/"intake-health.json"
        temporary=directory/"intake-health.tmp"
        temporary.write_text(json.dumps(report,indent=2))
        temporary.replace(target)
        return report
    try:
        while time.monotonic()<deadline:
            window={"attempt_started":time.time(),"connected_at":None,"messages":0}
            windows.append(window)
            save()
            try:
                async with websockets.connect("wss://live.see.tg/v1/ws",open_timeout=10,max_size=1000000) as ws:
                    window["connected_at"]=time.time()
                    await ws.send(json.dumps({"type":"subscribe","events":["sale","listing","price","delisting"]}))
                    checkpoint=time.monotonic()
                    while time.monotonic()<deadline:
                        try:
                            raw=await asyncio.wait_for(ws.recv(),min(10,max(.01,deadline-time.monotonic())))
                        except asyncio.TimeoutError:
                            save()
                            continue
                        window["messages"]+=1
                        try:
                            event=normalize(json.loads(raw),time.time())
                            if event:
                                if store_event(db,event):
                                    counts[event["event"]]+=1
                                else:
                                    counts["duplicate_event_ids"]+=1
                        except (ValueError,TypeError,KeyError,OverflowError):
                            counts["malformed"]+=1
                        if time.monotonic()-checkpoint>=30:
                            print("INTAKE_PROGRESS:",json.dumps(dict(counts)),flush=True)
                            save()
                            checkpoint=time.monotonic()
                        # Let connection keepalive tasks run even with buffered messages.
                        await asyncio.sleep(0)
                window["outcome"]="completed"
            except Exception as exc:
                window["outcome"]="disconnected"
                window["error_type"]=type(exc).__name__
                window["close_code"]=getattr(getattr(exc,"rcvd",None),"code",None)
                counts["disconnects"]+=1
            finally:
                window["ended"]=time.time()
                save()
            if time.monotonic()<deadline:
                await asyncio.sleep(min(2,max(0,deadline-time.monotonic())))
    finally:
        report=save()
        db.close()
        print("INTAKE_RESULT:",json.dumps(report),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=int,default=60)
    parser.add_argument("--output-dir",type=Path,default=Path("intake"))
    args=parser.parse_args()
    if not 1<=args.seconds<=10800:
        parser.error("seconds must be between 1 and 10800")
    asyncio.run(capture(args.seconds,args.output_dir))
