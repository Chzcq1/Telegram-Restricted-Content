# Telegram Restricted Content Downloader

A Python CLI tool that monitors your clipboard for Telegram media links and downloads both restricted and non-restricted content from Telegram channels and groups.

## How to Use

1. Run the app — it starts monitoring your clipboard automatically.
2. Copy any Telegram media link (e.g. `https://t.me/...`) to your clipboard.
3. The app detects it and adds it to the download queue.
4. Press **Enter** to download all queued media.
5. Press **r + Enter** to clear the queue.
6. Type **exit** to stop the program.

## Setup

Requires two Telegram API credentials stored as secrets:
- `API_ID` — from https://my.telegram.org/auth
- `API_HASH` — from https://my.telegram.org/auth

## Running

```bash
python app.py
```

## User Preferences

- No specific preferences recorded yet.
