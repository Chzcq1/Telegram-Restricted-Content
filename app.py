import asyncio
import threading
import logging
import os
import shutil
import sys

# Must create event loop before importing Pyrogram.
# Python 3.10+ no longer auto-creates one, causing RuntimeError in pyrogram/sync.py.
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

from src.client import UserClient
from src.web import create_app
from src import db, config
from bot import build_bot


def _is_session_healthy(path: str) -> bool:
    """Return True if the SQLite session file at *path* passes integrity_check."""
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(path, timeout=3)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        return result is not None and result[0] == "ok"
    except Exception:
        return False


def _copy_sessions_to_tmp():
    """Copy Pyrogram session files to /tmp so they are writable in all environments.

    In Replit VM deployments the workspace may be read-only; /tmp is always writable.
    We copy existing sessions from the workspace to /tmp so that a previously
    authenticated owner account survives a re-deploy without needing to log in again.
    Malformed/corrupted sessions are removed so Pyrogram can create a fresh one.
    """
    log = logging.getLogger(__name__)
    in_deployment = bool(os.environ.get("REPLIT_DEPLOYMENT"))
    for name in ("mysession.session", "botsession.session"):
        # In production, never reuse the bot session from the snapshot —
        # the bot can always re-authenticate from BOT_TOKEN, and sharing the
        # same auth key with the dev environment causes AUTH_KEY_DUPLICATED.
        if in_deployment and name == "botsession.session":
            for p in (f"/tmp/{name}", f"/tmp/{name}-journal", f"/tmp/{name}-wal", f"/tmp/{name}-shm"):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            log.info("Production: starting bot with a fresh session (from BOT_TOKEN).")
            continue
        src_path = os.path.join(os.path.dirname(__file__), name)
        dst_path = f"/tmp/{name}"

        # If already in /tmp and healthy, leave it alone
        if os.path.exists(dst_path):
            if _is_session_healthy(dst_path):
                log.info(f"{name} already in /tmp (healthy)")
                continue
            else:
                log.warning(f"/tmp/{name} is malformed — removing")
                try:
                    os.remove(dst_path)
                    for ext in ("-journal", "-wal", "-shm"):
                        p = dst_path + ext
                        if os.path.exists(p):
                            os.remove(p)
                except Exception:
                    pass

        # Copy from workspace to /tmp if the workspace copy is healthy
        if os.path.exists(src_path):
            if _is_session_healthy(src_path):
                try:
                    shutil.copy2(src_path, dst_path)
                    log.info(f"Copied {name} → /tmp/{name}")
                except Exception as e:
                    log.warning(f"Could not copy {name}: {e}")
            else:
                log.warning(f"{name} in workspace is malformed — will create fresh session")
                # Remove the bad workspace copy too so it doesn't get picked up again
                try:
                    os.remove(src_path)
                except Exception:
                    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 5000))


async def main():
    _copy_sessions_to_tmp()
    await db.init_db()

    tg_client = UserClient()
    loop = asyncio.get_running_loop()

    # ── Flask admin web UI ──
    # Start this FIRST and immediately, before touching Telegram at all.
    # Deployment healthchecks probe the port right away; if we make them wait
    # on Telegram DC handshakes (which can take many seconds, or hang if
    # Telegram is briefly unreachable), the platform sees the port as never
    # opened, decides the app is unhealthy, and kills/restarts it — which
    # restarts the slow Telegram handshake too, producing an endless
    # crash-restart loop and a bot that never becomes responsive.
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

    logger.info("Connecting owner Telegram account…")
    try:
        await tg_client.connect()
    except AttributeError as e:
        logger.error(f"Telegram credentials missing: {e}")
        logger.error("Please set API_ID and API_HASH environment variables.")
    except BaseException as e:
        logger.error(f"Failed to connect owner account: {e}")

    if tg_client.is_authorized:
        me = await tg_client.get_me()
        logger.info(f"Owner logged in as: {me.get('name')} ({me.get('phone')})")
    else:
        logger.info("Owner account not authenticated — admin can use /login in the bot.")

    # ── Telegram subscription bot ──
    if config.BOT_TOKEN and config.API_ID and config.API_HASH:
        bot = build_bot(tg_client)
        try:
            await bot.start()
            me = await bot.get_me()
            logger.info(f"Bot started as @{me.username}")
        except BaseException as e:
            logger.error(f"Bot failed to start: {e}. Wiping bot session and retrying in 10s…")
            # A bad/duplicated session is the usual culprit — remove it so
            # Pyrogram re-authenticates cleanly from BOT_TOKEN.
            for p in ("/tmp/botsession.session", "/tmp/botsession.session-journal",
                      "/tmp/botsession.session-wal", "/tmp/botsession.session-shm"):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            bot = build_bot(tg_client)
            await asyncio.sleep(10)
            try:
                await bot.start()
                me = await bot.get_me()
                logger.info(f"Bot started (retry) as @{me.username}")
            except BaseException as e2:
                logger.error(f"Bot still failed after retry: {e2}. Running without bot.")
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
