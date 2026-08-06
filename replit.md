# Telegram Subscription Content Bot

A paid Telegram bot: customers pay with a TrueMoney gift-voucher (angpao) to
activate a subscription, then send Telegram post links and the bot delivers the
content back. Built with Python + Pyrogram. A Flask admin web UI is kept for the
owner's own use.

## Architecture

- `app.py` — entry point. Creates one shared asyncio loop, then runs:
  - the owner **UserClient** (`src/client.py`, session `mysession`) that actually
    fetches content — it must be logged in once by the admin.
  - the **subscription bot** (`bot.py`, session `botsession`, uses `BOT_TOKEN`).
  - the **Flask admin web UI** (`src/web.py`) in a background thread on port 5000.
- `src/config.py` — plans, admin ID, support contact, voucher gateway.
- `src/db.py` — SQLite (`data.db`): subscriptions, usage, redeemed vouchers.
- `src/payment.py` — TrueMoney gift-voucher redemption.
- `src/downloader.py` — existing download/forward engine (reused).

## Subscription plans (edit in `src/config.py`)

- 15 วัน = 350 บาท
- 30 วัน = 500 บาท
- 90 วัน = 800 บาท

The voucher amount must match a plan price exactly to grant that plan.

## Bot commands

Customer: `/start`, `/help`, `/myplan`, `/upgrade`, `/id` (+ inline buttons).
On first use, choose Thai or English, tap **Start fetching**, then paste one
Telegram post link. Each Telegram account receives two successful trial
retrievals for its lifetime; paid memberships remain unlimited.

Admin (ID from `ADMIN_ID`):
- `/login +66xxxxxxxxx` → `/code 12345` → (`/twofa <password>` if 2FA) — logs in
  the owner Telegram account so the bot can access private groups.
- `/stats` — usage & revenue.
- `/grant <user_id> <days>` — manually grant a subscription.
- `/grantme <days>` — grant a test subscription to the admin's own account.

## Required secrets (Replit Secrets)

- `BOT_TOKEN` — from @BotFather
- `API_ID` / `API_HASH` — from https://my.telegram.org/auth (owner account)
- `TRUEMONEY_WALLET_PHONE` — wallet phone that receives voucher top-ups
- `ADMIN_ID` — **required for admin functions**: Telegram user ID of the admin.
  Without it, `/login`, `/stats`, `/grant` and admin notifications are disabled.
- `SUPPORT_CONTACT` — (optional) support handle for the ช่วยเหลือ button
- `SESSION_SECRET` / `WEB_PASSWORD` — for the admin web UI

## Running on Replit

Workflow **Start application** runs `python app.py`. First-time setup: open the
bot in Telegram, send `/login` as admin to authenticate the owner account.

## Deployment (always-on)

Configured as a **VM** deployment (`run = python app.py`) so the bot stays
online after you close Replit. Click **Publish** to go live. Autoscale is NOT
suitable — a Telegram bot must run continuously.

## Notes / boundaries

- The bot only fetches content the owner account is genuinely allowed to access;
  it does not bypass Telegram access controls or permissions.
- Bot API upload limit (~50 MB) applies to files delivered to customers.
- Trial items are deducted only after the bot successfully delivers content.

## User Preferences

- ภาษา: ผู้ใช้เลือกภาษาไทยหรืออังกฤษในบอทได้
