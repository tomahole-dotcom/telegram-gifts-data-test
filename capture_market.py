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
    result = {"kind": "authenticated-market-probe", "started_at": time.time(), "errors": []}
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
        try:
            bot = await client.get_input_entity("mrkt")
            app = types.InputBotAppShortName(bot_id=utils.get_input_user(bot), short_name="app")
            view = await client(functions.messages.RequestAppWebViewRequest(
                peer=bot, app=app, platform="android", write_allowed=False))
            url = urllib.parse.urlsplit(view.url)
            fields = urllib.parse.parse_qs(url.fragment)
            if "tgWebAppData" not in fields:
                fields = urllib.parse.parse_qs(url.query)
            init_data = fields["tgWebAppData"][0]
            status, auth = await asyncio.to_thread(http, "/auth", {"data": init_data})
            result["mrkt_auth_status"] = status
            token = auth.get("token") if isinstance(auth, dict) else None
            if status == 200 and isinstance(token, str) and token:
                feed_status, feed = await asyncio.to_thread(http, "/feed", {}, token)
                result["mrkt_feed_status"] = feed_status
                items = feed.get("items", []) if isinstance(feed, dict) else []
                result["mrkt_feed_events"] = []
                for item in items[:100]:
                    if not isinstance(item, dict):
                        continue
                    gift = item.get("gift") or {}
                    if not isinstance(gift, dict):
                        gift = {}
                    safe_gift = {key: gift[key] for key in (
                        "name", "title", "number", "collectionName", "modelName",
                        "backdropName", "symbolName", "salePrice") if key in gift}
                    result["mrkt_feed_events"].append({
                        key: item[key] for key in ("id", "type", "amount", "date") if key in item
                    } | {"gift": safe_gift})
                print("MRKT feed HTTP:", feed_status, "events:", len(result["mrkt_feed_events"]))
            else:
                print("MRKT authentication HTTP:", status, "(no response body logged)")
        except Exception as error:
            result["errors"].append({"stage": "mrkt", "error_type": type(error).__name__})
            print("MRKT probe failed:", type(error).__name__)
        result["valuation_status"] = "NOT_VALIDATED"
        result["finished_at"] = time.time()
        output = ROOT / "gifts-authenticated-probe.json"
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
