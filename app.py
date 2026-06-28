import asyncio
import threading
import logging
import sys

from src.client import UserClient
from src.web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    tg_client = UserClient()
    logger.info("Connecting to Telegram…")
    await tg_client.connect()

    if tg_client.is_authorized:
        me = await tg_client.get_me()
        logger.info(f"Logged in as: {me.get('name')} ({me.get('phone')})")
    else:
        logger.info("Not authenticated yet — open the web interface to log in.")

    loop = asyncio.get_event_loop()
    flask_app = create_app(tg_client, loop)

    flask_thread = threading.Thread(
        target=lambda: flask_app.run(
            host="0.0.0.0",
            port=5000,
            use_reloader=False,
            threaded=True,
        ),
        daemon=True,
        name="flask",
    )
    flask_thread.start()
    logger.info("Web interface running on port 5000 — open the Preview tab.")

    # Keep the asyncio loop alive for Pyrogram coroutines
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)
