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

# Subscription plans: key -> plan details.
# The price must match the exact voucher amount for that plan to be granted.
# All plans run for the same duration (15 days) and differ by processing
# speed and features:
#   delay: seconds the bot waits between delivering each item in a job
#          (lower = faster; this is the per-item pacing during range/+N fetches)
#   preview: whether the customer gets a thumbnail/preview to confirm the link
#            matches the expected content BEFORE the real fetch runs
PLANS = {
    "lite": {
        "days": 15,
        "price": 250,
        "label": "Lite",
        "delay": 17,
        "preview": False,
        "features": [
            "ดึงเนื้อหาได้ไม่จำกัดจำนวนภายใน 15 วัน",
            "ความเร็วมาตรฐาน — ประมวลผล ~17 วิ/งาน",
        ],
    },
    "medium": {
        "days": 15,
        "price": 450,
        "label": "Medium",
        "delay": 5,
        "preview": False,
        "features": [
            "ดึงเนื้อหาได้ไม่จำกัดจำนวนภายใน 15 วัน",
            "ความเร็วปานกลาง — ประมวลผล ~5 วิ/งาน (เร็วกว่า Lite ~3 เท่า)",
        ],
    },
    "core": {
        "days": 15,
        "price": 800,
        "label": "Core",
        "delay": 1.5,
        "preview": True,
        "features": [
            "ดึงเนื้อหาได้ไม่จำกัดจำนวนภายใน 15 วัน",
            "ความเร็วสูงสุด — ประมวลผล ~1.5 วิ/งาน",
            "พรีวิวลิงก์ก่อนดึงจริง — เห็นภาพตัวอย่าง/รายละเอียดโพสต์ ยืนยันว่าตรงกับที่ต้องการก่อนกดดึง",
        ],
    },
}

# Fallback speed/preview for users without an active plan (trial / expired).
DEFAULT_DELAY = 17
DEFAULT_PREVIEW = False


def plan_speed(plan_key: str):
    """Return (delay_seconds, preview_enabled) for a given plan key."""
    plan = PLANS.get(plan_key or "")
    if not plan:
        return DEFAULT_DELAY, DEFAULT_PREVIEW
    return plan.get("delay", DEFAULT_DELAY), plan.get("preview", DEFAULT_PREVIEW)

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
