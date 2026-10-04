"""Read-only wider Scared Cat sample with private, resumable checkpoints."""
import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from telethon import TelegramClient, functions

ROOT = Path.home() / ".local/share/telegram-gifts-data-test"
OUTPUT = ROOT / "telegram-wide-probe.json"
MAX_LISTINGS = 200

def save(data):
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(OUTPUT)

def summary(data):
    rows = data["listings"]
    evidence = [r for r in rows if r.get("sale_evidence")]
    sold = [r for r in evidence if r["sale_evidence"].get("last_sale_timestamp")
            and r["sale_evidence"].get("last_sale_price_minor") is not None]
    recent = [r for r in sold if 0 <= time.time() - r["sale_evidence"]["last_sale_timestamp"] <= 7*86400]
    groups = Counter()
    for row in recent:
        key = tuple(sorted((t["type"], t["name"]) for t in row["traits"]))
        groups[(row["sale_evidence"]["currency"], key)] += 1
    return {"listings": len(rows), "value_lookups_completed": len(evidence),
            "assets_with_last_sale": len(sold), "last_sales_within_7d": len(recent),
            "collection_average_fallbacks": sum(bool(r["sale_evidence"]["value_is_average"]) for r in evidence),
            "largest_same_currency_exact_trait_recent_sales_group": max(groups.values(), default=0),
            "errors": len(data["errors"])}

async def main():
    os.umask(0o077)
    settings = json.loads((ROOT / "api.json").read_text())
    cache = {}
    for path in (ROOT / "telegram-values-probe.json", OUTPUT):
        if path.exists():
            for row in json.loads(path.read_text()).get("listings", []):
                if row.get("sale_evidence") and time.time() - row.get("value_observed_at", 0) < 6*3600:
                    cache[row["slug"]] = row
    data = {"kind": "telegram-wide-read-only-probe", "started_at": time.time(),
            "listings": [], "errors": [], "valuation_status": "NOT_VALIDATED",
            "sample_note": "Up to 200 listings ordered by resale price change; not a global completed-sales feed."}
    client = TelegramClient(str(ROOT / "gifts"), settings["api_id"], settings["api_hash"],
                            flood_sleep_threshold=0)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Session is not logged in. Run setup_session.py first.", flush=True)
            return
        catalog = await client(functions.payments.GetStarGiftsRequest(hash=0))
        collection = next(g for g in catalog.gifts if getattr(g, "title", "") == "Scared Cat")
        data["collection"] = "Scared Cat"
        offset = ""
        seen = set()
        offsets = set()
        while len(data["listings"]) < MAX_LISTINGS:
            page = await client(functions.payments.GetResaleStarGiftsRequest(
                gift_id=collection.id, offset=offset, limit=min(100, MAX_LISTINGS-len(data["listings"]))))
            data["total_listings_reported"] = page.count
            for gift in page.gifts:
                if gift.slug in seen:
                    continue
                seen.add(gift.slug)
                row = {"slug": gift.slug, "number": gift.num, "observed_at": time.time(),
                       "traits": [{"type": type(t).__name__, "name": t.name,
                                   "rarity_permille": getattr(getattr(t, "rarity", None), "permille", None)}
                                  for t in gift.attributes if hasattr(t, "name")],
                       "prices_raw": [{"type": type(a).__name__, "amount": a.amount,
                                       "nanos": getattr(a, "nanos", 0)}
                                      for a in (getattr(gift, "resell_amount", None) or [])]}
                if gift.slug in cache:
                    row["sale_evidence"] = cache[gift.slug]["sale_evidence"]
                    row["value_observed_at"] = cache[gift.slug]["value_observed_at"]
                data["listings"].append(row)
            save(data)
            next_offset = getattr(page, "next_offset", None)
            if not next_offset or next_offset in offsets or not page.gifts:
                break
            offsets.add(next_offset)
            offset = next_offset
            await asyncio.sleep(1.5)
        print("Listings captured:", len(data["listings"]), "| Cached values:",
              sum("sale_evidence" in r for r in data["listings"]), flush=True)
        for index, row in enumerate(data["listings"]):
            if "sale_evidence" in row:
                continue
            try:
                value = await client(functions.payments.GetUniqueStarGiftValueInfoRequest(slug=row["slug"]))
                sale_date = getattr(value, "last_sale_date", None)
                row["sale_evidence"] = {
                    "currency": value.currency, "estimated_value_minor": value.value,
                    "value_is_average": bool(getattr(value, "value_is_average", False)),
                    "last_sale_timestamp": sale_date.timestamp() if hasattr(sale_date, "timestamp") else sale_date,
                    "last_sale_price_minor": getattr(value, "last_sale_price", None),
                    "collection_floor_minor": getattr(value, "floor_price", None),
                    "collection_average_minor": getattr(value, "average_price", None)}
                row["value_observed_at"] = time.time()
            except Exception as error:
                data["errors"].append({"stage": "value", "slug": row["slug"], "error_type": type(error).__name__})
                save(data)
                if type(error).__name__ == "FloodWaitError":
                    print("Rate limit: stopping. Saved values will be reused on the next run.", flush=True)
                    break
            save(data)
            if (index+1) % 20 == 0:
                print("Progress:", json.dumps(summary(data)), flush=True)
            await asyncio.sleep(1.5)
    finally:
        data["summary"] = summary(data)
        data["finished_at"] = time.time()
        save(data)
        print("RESULT:", json.dumps(data["summary"]), flush=True)
        print("Opportunity NOT VALIDATED: fiat sales require currency normalization and sufficient comparables.", flush=True)
        print("Saved:", OUTPUT, flush=True)
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=360))
    except KeyboardInterrupt:
        print("Stopped by user. Checkpoint preserved.")
    except Exception as error:
        print("Probe stopped:", type(error).__name__)
