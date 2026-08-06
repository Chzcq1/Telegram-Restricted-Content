import asyncio
import threading
import logging
import os
import sys

# Must create event loop before importing Pyrogram.
# Python 3.10+ no longer auto-creates one, causing RuntimeError in pyrogram/sync.py.
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

from src.client import UserClient
from src.web import create_app
from src import db, config
from bot import build_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 5000))


async def main():
    await db.init_db()

    tg_client = UserClient()
    logger.info("Connecting owner Telegram account…")
    try:
        await tg_client.connect()
    except AttributeError as e:
        logger.error(f"Telegram credentials missing: {e}")
        logger.error("Please set API_ID and API_HASH environment variables.")
    except Exception as e:
        logger.error(f"Failed to connect owner account: {e}")

    if tg_client.is_authorized:
        me = await tg_client.get_me()
        logger.info(f"Owner logged in as: {me.get('name')} ({me.get('phone')})")
    else:
        logger.info("Owner account not authenticated — admin can use /login in the bot.")

    loop = asyncio.get_running_loop()

    # ── Flask admin web UI (kept for the admin's own use) ──
    # Never expose this powerful UI without a configured password.
    if os.environ.get("WEB_PASSWORD"):
        flask_app = create_app(tg_client, loop)
        flask_thread = threading.Thread(
            target=lambda: flask_app.run(
                host="0.0.0.0", port=PORT, use_reloader=False, threaded=True,
            ),
            daemon=True,
            name="flask",
        )
        flask_thread.start()
        logger.info(f"Admin web UI running on port {PORT}.")
    else:
        logger.warning(
            "WEB_PASSWORD is not configured — admin web UI is disabled."
        )

    # ── Telegram subscription bot ──
    if config.BOT_TOKEN and config.API_ID and config.API_HASH:
        bot = build_bot(tg_client)
        await bot.start()
        me = await bot.get_me()
        logger.info(f"Bot started as @{me.username}")
    else:
        logger.error("BOT_TOKEN / API_ID / API_HASH missing — bot not started.")

    # Keep the loop alive for Pyrogram coroutines
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)
