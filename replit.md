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

## Running on Replit

The workflow **Start application** runs `python app.py`. The web interface is available in the Preview tab on port 5000.

Required secrets (set in Replit Secrets):
- `API_ID` — Telegram app ID (from https://my.telegram.org/auth)
- `API_HASH` — Telegram app hash
- `SESSION_SECRET` — Flask session signing key (auto-generated if absent)
- `WEB_PASSWORD` — Password to protect the web interface
- `PHONE_NUMBER` — (optional) pre-fills the login form

## Deploying Elsewhere (optional)

This repo was originally set up for Render and still includes `render.yaml` for that path (not needed on Replit): push to GitHub, create a Render Web Service, connect the repo (Render auto-detects `render.yaml`), and set `API_ID` / `API_HASH` / `PHONE_NUMBER` as env vars there. The app listens on `PORT` and exposes a health check at `/healthz`.

## User Preferences

- No specific preferences recorded yet.
