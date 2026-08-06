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
