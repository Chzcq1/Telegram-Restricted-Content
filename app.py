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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 5000))


async def main():
    tg_client = UserClient()
    logger.info("Connecting to Telegram…")
    try:
        await tg_client.connect()
    except AttributeError as e:
        # API_ID / API_HASH not set — start web server anyway so the user
        # sees the error message in the UI instead of a blank crash.
        logger.error(f"Telegram credentials missing: {e}")
        logger.error("Please set API_ID and API_HASH environment variables.")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {e}")

    if tg_client.is_authorized:
        me = await tg_client.get_me()
        logger.info(f"Logged in as: {me.get('name')} ({me.get('phone')})")
    else:
        logger.info("Not authenticated yet — open the web interface to log in.")

    loop = asyncio.get_running_loop()
    flask_app = create_app(tg_client, loop)

    flask_thread = threading.Thread(
        target=lambda: flask_app.run(
            host="0.0.0.0",
            port=PORT,
            use_reloader=False,
            threaded=True,
        ),
        daemon=True,
        name="flask",
    )
    flask_thread.start()
    logger.info(f"Web interface running on port {PORT} — open the Preview tab.")

    # Keep the asyncio loop alive for Pyrogram coroutines
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)
