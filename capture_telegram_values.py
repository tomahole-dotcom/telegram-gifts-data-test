"""Read-only data probe. Authentication/session files stay outside the repository."""
import asyncio
import getpass
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from telethon import TelegramClient, functions, types, utils

ROOT = Path.home() / ".local" / "share" / "telegram-gifts-data-test"

def http(path, payload, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = token
    request = urllib.request.Request(
        "https://api.tgmrkt.io/api/v1" + path,
        data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return status, None

async def main():
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    config = ROOT / "api.json"
    if config.exists():
        settings = json.loads(config.read_text())
    else:
        settings = {"api_id": 39205261, "api_hash": getpass.getpass("API hash (hidden, saved privately for reuse): ").strip()}
        if not settings["api_hash"]:
            raise ValueError("Missing API hash")
        config.write_text(json.dumps(settings))
        config.chmod(0o600)
    client = TelegramClient(str(ROOT / "gifts"), settings["api_id"], settings["api_hash"])
    result = {"kind": "telegram-value-evidence-probe", "started_at": time.time(), "errors": []}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Session is not logged in. Run setup_session.py first.")
            return
        result["telegram_authenticated"] = True
        catalog = await client(functions.payments.GetStarGiftsRequest(hash=0))
        gifts = [g for g in catalog.gifts if getattr(g, "availability_resale", 0)]
        collection = next((g for g in gifts if getattr(g, "title", "") == "Scared Cat"), None)
        if collection is None:
            raise ValueError("Scared Cat not found")
        listings = await client(functions.payments.GetResaleStarGiftsRequest(gift_id=collection.id, offset="", limit=20))
        result["collection"] = "Scared Cat"
        result["total_listings"] = listings.count
        result["listings"] = []
        for gift in listings.gifts:
            traits = []
            for trait in gift.attributes:
                if hasattr(trait, "name"):
                    rarity = getattr(trait, "rarity", None)
                    traits.append({"type": type(trait).__name__, "name": trait.name,
                                   "rarity_permille": getattr(rarity, "permille", None)})
            amounts = [{"type": type(a).__name__, "amount": a.amount,
                        "nanos": getattr(a, "nanos", 0)}
                       for a in (getattr(gift, "resell_amount", None) or [])]
            result["listings"].append({"slug": gift.slug, "number": gift.num,
                                       "observed_at": time.time(), "traits": traits, "prices_raw": amounts})
        print("Telegram: logged in; listings captured:", len(result["listings"]))
        recent = 0
        last_sales = 0
        averages = 0
        for index, listing in enumerate(result["listings"]):
            try:
                value = await client(functions.payments.GetUniqueStarGiftValueInfoRequest(slug=listing["slug"]))
                sale_date = getattr(value, "last_sale_date", None)
                timestamp = sale_date.timestamp() if hasattr(sale_date, "timestamp") else sale_date
                listing["sale_evidence"] = {
                    "currency": value.currency,
                    "estimated_value_minor": value.value,
                    "value_is_average": bool(getattr(value, "value_is_average", False)),
                    "last_sale_timestamp": timestamp,
                    "last_sale_price_minor": getattr(value, "last_sale_price", None),
                    "collection_floor_minor": getattr(value, "floor_price", None),
                    "collection_average_minor": getattr(value, "average_price", None),
                }
                if timestamp and getattr(value, "last_sale_price", None) is not None:
                    last_sales += 1
                    if 0 <= time.time() - timestamp <= 7 * 86400:
                        recent += 1
                if listing["sale_evidence"]["value_is_average"]:
                    averages += 1
            except Exception as error:
                result["errors"].append({"stage": "telegram_value", "slug": listing["slug"],
                                         "error_type": type(error).__name__})
                if type(error).__name__ == "FloodWaitError":
                    print("Telegram rate limit reached; stopping value lookups.")
                    break
            if (index + 1) % 5 == 0:
                print("Value lookups:", index + 1, "/", len(result["listings"]))
            await asyncio.sleep(1.2)
        result["summary"] = {"listings": len(result["listings"]), "assets_with_last_sale": last_sales,
                             "last_sales_within_7d": recent, "collection_average_fallbacks": averages}
        print("Result:", json.dumps(result["summary"]))
        print("Opportunity: NOT VALIDATED. Fiat sale evidence is not compared directly with TON or Stars.")
        result["valuation_status"] = "NOT_VALIDATED"
        result["finished_at"] = time.time()
        output = ROOT / "telegram-values-probe.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        output.chmod(0o600)
        print("Read-only test finished. Result:", output)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=120))
    except Exception as error:
        print("Probe stopped:", type(error).__name__)
