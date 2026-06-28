# Telegram Restricted Content Downloader

A web-based tool to download media (videos, photos, documents) from Telegram channels and groups, including restricted content. Built with Python + Flask + Pyrogram.

## How to Use

1. Run the app — Flask web server starts on the configured port.
2. Open the web interface and log in with your Telegram phone number.
3. Enter a Telegram message link to scan and preview media.
4. Select items and download them to the server, then save them locally.

## Setup

Requires Telegram API credentials (get from https://my.telegram.org/auth):
- `API_ID` — numeric app ID
- `API_HASH` — app hash string
- `PHONE_NUMBER` — (optional) pre-fills the login form

## Running Locally

```bash
python app.py
```

## Deploying to Render

1. Push this repo to GitHub.
2. Go to https://dashboard.render.com → New → Web Service.
3. Connect your GitHub repo.
4. Render auto-detects `render.yaml` — settings are pre-configured.
5. Add environment variables in the Render dashboard:
   - `API_ID`
   - `API_HASH`
   - `PHONE_NUMBER` (optional)
6. Click **Deploy**.

The app listens on the `PORT` env var (set automatically by Render). Health check runs at `/healthz`.

## User Preferences

- No specific preferences recorded yet.
