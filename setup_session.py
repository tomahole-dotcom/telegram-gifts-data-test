"""Run interactively; no credentials or session files belong in the repository."""
import asyncio
import getpass
import os
from pathlib import Path

from telethon import TelegramClient

async def main():
    os.umask(0o077)
    directory = Path.home() / ".local" / "share" / "telegram-gifts-data-test"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    api_id = int(input("Telegram API ID: ").strip())
    api_hash = getpass.getpass("Telegram API hash (hidden): ").strip()
    client = TelegramClient(str(directory / "gifts"), api_id, api_hash,
                            device_model="Gifts Data Test")
    try:
        await client.start(
            phone=lambda: getpass.getpass("Phone with country code (hidden): "),
            code_callback=lambda: getpass.getpass("Telegram login code (hidden): "),
            password=lambda: getpass.getpass("Telegram two-step password (hidden): "),
        )
        print("Dedicated Gifts session ready. No market requests or trades made.")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("Login cancelled.")
    except Exception as error:
        print("Login failed:", type(error).__name__)
