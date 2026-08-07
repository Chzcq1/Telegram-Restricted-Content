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
- A plain text message that merely contains a URL gets `msg.media =
  MessageMediaType.WEB_PAGE` in Pyrogram (the link-preview object), not `None`.
  **Why:** any code that branches on `if msg.media` to decide "download vs.
  send as text" wrongly takes the download path for these, then crashes with
  `'WebPage' object has no attribute 'file_id'` inside `download_media()` —
  looks like "messages with links get silently skipped."
  **How to apply:** treat media as downloadable only if
  `msg.media and msg.media != MessageMediaType.WEB_PAGE`; otherwise handle as
  text. Also send raw fetched text with `parse_mode=ParseMode.DISABLED` (via
  `bot.send_message`, not the raw Bot API `BotForwarder`) — default Markdown
  parsing silently fails on stray `_`/`*` that are common in URLs.
- `parse_link()` must accept `t.me/s/<name>/<id>` (Telegram's browsable
  web-preview link format, used to view public channels without joining) in
  addition to the plain `t.me/<name>/<id>` form, and both `http://`/`https://`.
  **Why:** users commonly copy the `/s/` variant; missing it makes every such
  link silently fail with "link not found" — looked like a customer-specific
  bug but was a link-format gap in the regex.
