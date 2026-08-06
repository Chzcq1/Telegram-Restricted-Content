"""Central configuration for the subscription bot.

All sensitive values come from environment variables (Replit Secrets).
Plan prices are defined here so they are easy to adjust in one place.
"""
import os

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Admin who can run /login and management commands + receives notifications.
# Must be configured explicitly (env/secret). 0 disables all admin commands.
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)

# TrueMoney wallet phone number that receives the gift-voucher (angpao) top-ups.
TRUEMONEY_WALLET_PHONE = os.environ.get("TRUEMONEY_WALLET_PHONE", "")

# Support contact shown on the "ช่วยเหลือ" button.
SUPPORT_CONTACT = os.environ.get("SUPPORT_CONTACT", "@Signals899")

# Subscription plans: key -> (label, days, price_baht)
# The price must match the exact voucher amount for that plan to be granted.
PLANS = {
    "p15": {"days": 15, "price": 350, "label": "15 วัน"},
    "p30": {"days": 30, "price": 500, "label": "30 วัน"},
    "p90": {"days": 90, "price": 800, "label": "90 วัน"},
}

# One-time trial: non-members may successfully retrieve this many items in total.
TRIAL_MAX_ITEMS = 2

# TrueMoney gift voucher gateway (from the provided API docs).
VOUCHER_GATEWAY = "https://gateway.autozy.app/api/giftvoucher"


def plan_by_price(amount: float):
    """Return (plan_key, plan) whose price matches the given amount, else (None, None)."""
    for key, plan in PLANS.items():
        if int(plan["price"]) == int(round(amount)):
            return key, plan
    return None, None
