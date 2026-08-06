---
name: Telegram bot stack
description: Durable, non-obvious setup lessons for this project's Pyrogram bot
---

- The `pyrogram` import is provided by the **`pyrotgfork`** package (a maintained
  fork). There is NO separate `pyrogram` pip package. If imports fail with
  ModuleNotFoundError, install `pyrotgfork`, not `pyrogram`.
- The owner **user account** and the **bot** are two Pyrogram clients that must
  run on the SAME asyncio loop (created before importing Pyrogram). Never drive a
  Pyrogram client from a second/ad-hoc loop.
  **Why:** mixing loops causes runtime errors and connection instability.
- Content is fetched via the user account but delivered to customers via the bot
  (a user account can't reliably message arbitrary users). This means the Bot API
  ~50 MB upload cap governs customer delivery — enforce size BEFORE downloading.
- On VM deployments, open the health-checked port (Flask) as the very first thing
  in `main()`, before any Telegram `connect()`/`bot.start()` calls.
  **Why:** Pyrogram DC handshakes can take many seconds (or hang); if the port
  opens after that, Replit's healthcheck sees the port as "never opened" and
  kills/restarts the process mid-startup, which restarts the slow handshake too —
  an endless crash-restart loop that looks like "the bot never responds after
  being idle a long time." Also catch `BaseException` (not just `Exception`)
  around `bot.start()` — a mid-startup kill delivers `asyncio.CancelledError`,
  which doesn't subclass `Exception` and will otherwise escape retry logic and
  crash the whole process.
