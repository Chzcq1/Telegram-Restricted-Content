"""Telegram subscription bot.

Customers pay with a TrueMoney gift-voucher (angpao) to activate a subscription,
then send Telegram message links; the bot fetches the content through the
owner's user account and delivers it back through the bot.

Runs on the shared asyncio loop created in app.py, alongside the Flask admin
web UI and the owner UserClient.
"""
import io
import time
import asyncio
import logging
import re

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

from src import config, db, payment
from src.downloader import BotForwarder, parse_link, _fmt_size

logger = logging.getLogger("bot")

# Bot API upload cap for files delivered to customers (~50 MB).
MAX_DELIVERY_BYTES = 50 * 1024 * 1024


def _media_size(msg) -> int:
    """Best-effort byte size of a message's media (0 if unknown)."""
    for attr in ("video", "document", "animation", "audio", "voice", "video_note"):
        obj = getattr(msg, attr, None)
        if obj is not None:
            return int(getattr(obj, "file_size", 0) or 0)
    if getattr(msg, "photo", None) is not None:
        return int(getattr(msg.photo, "file_size", 0) or 0)
    return 0

# Pending action per user: e.g. waiting for a voucher for a chosen plan.
_pending_plan: dict[int, str] = {}

# Pending fetch context per user, awaiting Core-plan preview confirmation
# (link matches expected content?) before the real fetch runs.
_pending_fetch: dict[int, dict] = {}


# ── Bilingual customer-facing copy ───────────────────────────────────────────

COPY = {
    "th": {
        "welcome": "👋 <b>ยินดีต้อนรับ!</b>\n\nส่งลิงก์โพสต์ Telegram มาให้บอทเพื่อรับข้อความ รูป หรือวิดีโอ\n\n🎁 <b>เริ่มทดลองฟรีได้ 2 รายการ</b> ต่อ 1 บัญชี\nกด <b>เริ่มดึงเนื้อหา</b> แล้วส่งลิงก์โพสต์ได้เลย",
        "language": "🌐 <b>เลือกภาษา</b>\nคุณเปลี่ยนภาษาได้ตลอดเวลาจากเมนู",
        "howto": "📖 <b>วิธีใช้งาน</b>\n\n<b>ก่อนเริ่ม:</b> แอดมินต้องล็อกอินบัญชี Telegram เจ้าของเข้าระบบก่อน บัญชีนี้ต้องเป็นสมาชิกกลุ่ม/แชนแนลต้นทางและมีสิทธิ์เห็นโพสต์นั้น\n\n<b>ดึง 1 โพสต์</b>\n1️⃣ เปิดโพสต์ Telegram ที่ต้องการ\n2️⃣ กด <b>คัดลอกลิงก์</b>\n3️⃣ กลับมาที่บอท แล้วกด <b>เริ่มดึงเนื้อหา</b>\n4️⃣ วางและส่งลิงก์\n\nตัวอย่าง:\n<code>https://t.me/channel_name/123</code>\n\n<b>ดึงหลายโพสต์ต่อเนื่องแบบง่าย ด้วย +N</b>\nเติม <code>+N</code> ท้ายลิงก์เพื่อดึงโพสต์นั้นและอีก N โพสต์ถัดไป เช่น:\n<code>https://t.me/channel_name/100+10</code>\nระบบจะดึงโพสต์ 100 ถึง 110 (รวม 11 โพสต์) ให้ต่อเนื่องในคำสั่งเดียว และนับเป็น 1 รายการ\n\n<b>ดึงหลายโพสต์ต่อเนื่องแบบระบุช่วง</b>\nส่งลิงก์แบบช่วงได้เลย เช่น:\n<code>https://t.me/channel_name/100-120</code>\nหรือส่งลิงก์กับเลขโพสต์สุดท้ายคั่นด้วยเว้นวรรค:\n<code>https://t.me/channel_name/100 120</code>\nระบบจะดึงโพสต์ 100 ถึง 120 ให้ต่อเนื่อง และนับเป็น 1 รายการ\n\n🎁 ทดลองฟรีได้ 2 รายการต่อบัญชี\n💎 เมื่อครบแล้ว เลือกแพ็กเกจเพื่อใช้งานไม่จำกัด\n\n<b>สำคัญ:</b> ลูกค้าไม่ต้องล็อกอินเอง แต่บัญชีเจ้าของของระบบต้องอยู่ในกลุ่ม/แชนแนลนั้นจริง หากบัญชีนี้เข้าไม่ถึงโพสต์ ระบบจะดึงไม่ได้",
        "ready": "📎 <b>พร้อมแล้ว!</b>\nบัญชีเจ้าของระบบล็อกอินแล้ว\n\nส่งลิงก์โพสต์ Telegram ที่ต้องการดึงมาได้เลย\n\nตัวอย่าง: <code>https://t.me/channel_name/123</code>\n\n⚠️ ตรวจสอบว่าบัญชีเจ้าของระบบเป็นสมาชิกกลุ่ม/แชนแนลต้นทางแล้ว",
        "login_required": "🔐 <b>ยังเริ่มดึงไม่ได้</b>\n\nแอดมินต้องล็อกอินบัญชี Telegram เจ้าของระบบก่อน 1 ครั้ง โดยส่งคำสั่งในแชตส่วนตัวกับบอท:\n\n<code>/login +668xxxxxxxx</code>\n<code>/code 1 2 3 4 5</code> (เว้นวรรคทีละตัว กัน Telegram บล็อก)\n<code>/twofa รหัสผ่าน</code> (ถ้ามี 2FA)\n\nหลังล็อกอินแล้ว บัญชีเจ้าของระบบต้องเป็นสมาชิกกลุ่ม/แชนแนลต้นทางที่ต้องการดึงด้วย\n\nลูกค้าไม่ต้องล็อกอินเอง เมื่อพร้อมแล้วกด “เริ่มดึงเนื้อหา” อีกครั้ง",
        "access_rule": "📌 <b>เงื่อนไขการดึงเนื้อหา</b>\n\nบัญชี Telegram เจ้าของระบบต้องอยู่ในกลุ่มหรือแชนแนลต้นทาง และต้องเปิดดูโพสต์นั้นได้จริง\n\nลูกค้าเพียงส่งลิงก์โพสต์ ไม่ต้องล็อกอินบัญชีของตัวเอง\n\nหากบัญชีเจ้าของไม่ได้อยู่ในกลุ่ม/แชนแนล หรือโพสต์ถูกลบ/ไม่มีสิทธิ์ ระบบจะดึงไม่ได้",
        "upgrade": "💎 <b>อัปเกรดเป็นสมาชิก</b>\n\n✅ ดึงเนื้อหาได้ไม่จำกัด\n✅ ไม่มีข้อจำกัดโปรทดลอง\n\nชำระผ่านซองอั่งเปา TrueMoney แล้วเลือกแพ็กเกจด้านล่าง",
        "start_fetch": "🚀 เริ่มดึงเนื้อหา",
        "howto_btn": "📖 วิธีใช้งาน",
        "myplan_btn": "📋 สถานะของฉัน",
        "upgrade_btn": "💎 อัปเกรด",
        "language_btn": "🌐 ภาษา / Language",
        "help_btn": "🎧 ช่วยเหลือ",
        "trial": "🎁 โปรทดลองคงเหลือ: <b>{remaining}/2</b> รายการ",
        "member": "✅ <b>สมาชิกใช้งานได้ — แพ็ก {plan_label}</b>\n{expiry}\nใช้งานสำเร็จ: {jobs} ครั้ง\n⚡ ความเร็ว: ~{delay} วิ/รายการ{preview_note}",
        "nonmember": "📋 <b>สถานะของฉัน</b>\nยังไม่ได้เป็นสมาชิก\n{trial}\n\nกด “เริ่มดึงเนื้อหา” เพื่อใช้สิทธิ์ทดลอง หรืออัปเกรดเพื่อใช้งานไม่จำกัด",
        "trial_done": "🎉 ดึงสำเร็จแล้ว! เหลือสิทธิ์ทดลอง <b>{remaining}/2</b> รายการ",
        "trial_finished": "⛔ <b>คุณใช้สิทธิ์ทดลองครบ 2 รายการแล้ว</b>\n\nอัปเกรดเป็นสมาชิกเพื่อดึงเนื้อหาได้ไม่จำกัด",
        "not_understood": "❓ ไม่พบลิงก์โพสต์ Telegram\nกด “วิธีใช้งาน” เพื่อดูตัวอย่างลิงก์ที่ถูกต้อง",
        "payment": "💳 คุณเลือกแพ็กเกจ <b>{label} — {price} บาท / {days} วัน</b>\n\nส่ง <b>ลิงก์ซองอั่งเปา TrueMoney</b> มูลค่า {price} บาทเข้ามาได้เลย",
        "fetching": "📥 กำลังดึงเนื้อหา…",
        "not_ready": "🔐 บัญชีเจ้าของระบบยังไม่ได้ล็อกอิน\nแอดมินต้องใช้ /login, /code และ /twofa (ถ้ามี) ก่อนเริ่มดึงเนื้อหา",
        "access_denied": "⚠️ บัญชีเจ้าของระบบเข้าไม่ถึงโพสต์นี้\n\nตรวจสอบว่าบัญชีเจ้าของเป็นสมาชิกกลุ่ม/แชนแนลต้นทาง และยังเปิดดูโพสต์นี้ได้ จากนั้นลองส่งลิงก์ใหม่",
        "not_found": "❌ ไม่พบข้อความหรือสื่อในโพสต์นี้",
        "text_sent": "✅ ส่งข้อความเรียบร้อยแล้ว",
        "downloading": "⬇️ กำลังดาวน์โหลด…",
        "download_failed": "❌ ดาวน์โหลดไม่สำเร็จ",
        "uploading": "⬆️ กำลังส่งไฟล์ ({size})…",
        "delivered": "✅ ส่งเนื้อหาเรียบร้อย!",
        "file_failed": "❌ ส่งไฟล์ไม่สำเร็จ: {error}",
        "too_large": "⚠️ ไฟล์นี้ใหญ่ {size} เกินขีดจำกัดการส่งของบอท ({limit})\nยังไม่รองรับไฟล์ขนาดนี้ กรุณาติดต่อแอดมิน",
    },
    "en": {
        "welcome": "👋 <b>Welcome!</b>\n\nSend a Telegram post link and the bot will return its text, photo, or video.\n\n🎁 <b>Get 2 free trial items</b> per account.\nTap <b>Start fetching</b>, then send a post link.",
        "language": "🌐 <b>Choose your language</b>\nYou can change it anytime from the menu.",
        "howto": "📖 <b>How to use</b>\n\n<b>Before you start:</b> An admin must log in the owner Telegram account first. That account must be a member of the source group/channel and be able to view the post.\n\n<b>Fetch one post</b>\n1️⃣ Open the Telegram post you want\n2️⃣ Tap <b>Copy Link</b>\n3️⃣ Return here and tap <b>Start fetching</b>\n4️⃣ Paste and send the link\n\nExample:\n<code>https://t.me/channel_name/123</code>\n\n<b>Fetch multiple consecutive posts the easy way — +N</b>\nAppend <code>+N</code> to the link to fetch that post plus the next N posts, e.g.:\n<code>https://t.me/channel_name/100+10</code>\nThis fetches posts 100 through 110 (11 posts total) in one request and counts as 1 item.\n\n<b>Fetch a specific range</b>\nSend a range link, for example:\n<code>https://t.me/channel_name/100-120</code>\nOr send the link followed by the final post ID:\n<code>https://t.me/channel_name/100 120</code>\nThe bot fetches posts 100 through 120 as one request and counts it as 1 item.\n\n🎁 You get 2 trial items per account.\n💎 Upgrade after that for unlimited use.\n\n<b>Important:</b> Customers do not need to log in. The system owner account must genuinely belong to the source group/channel; otherwise the post cannot be fetched.",
        "ready": "📎 <b>Ready!</b>\nThe owner account is logged in.\n\nSend the Telegram post link you want to fetch.\n\nExample: <code>https://t.me/channel_name/123</code>\n\n⚠️ Make sure the owner account is a member of the source group/channel.",
        "login_required": "🔐 <b>Fetching is not ready</b>\n\nAn admin must log in the owner Telegram account once from the private bot chat:\n\n<code>/login +668xxxxxxxx</code>\n<code>/code 1 2 3 4 5</code> (space out digits so Telegram doesn't block the login)\n<code>/twofa password</code> (if 2FA is enabled)\n\nThe owner account must also be a member of the source group/channel.\n\nCustomers do not need to log in. Tap “Start fetching” again after setup.",
        "access_rule": "📌 <b>Content access rules</b>\n\nThe owner Telegram account must be a member of the source group or channel and must be able to open the post.\n\nCustomers only send the post link and do not need to log in.\n\nIf the owner account is not a member, or the post was deleted or restricted, it cannot be fetched.",
        "upgrade": "💎 <b>Upgrade your membership</b>\n\n✅ Unlimited content retrieval\n✅ No trial limit\n\nPay with a TrueMoney gift voucher, then choose a plan below.",
        "start_fetch": "🚀 Start fetching",
        "howto_btn": "📖 How to use",
        "myplan_btn": "📋 My status",
        "upgrade_btn": "💎 Upgrade",
        "language_btn": "🌐 Language / ภาษา",
        "help_btn": "🎧 Help",
        "trial": "🎁 Trial remaining: <b>{remaining}/2</b> items",
        "member": "✅ <b>Active member — {plan_label} plan</b>\n{expiry}\nCompleted: {jobs} items\n⚡ Speed: ~{delay}s/item{preview_note}",
        "nonmember": "📋 <b>My status</b>\nNo active membership\n{trial}\n\nTap “Start fetching” to use your trial, or upgrade for unlimited access.",
        "trial_done": "🎉 Done! You have <b>{remaining}/2</b> trial items left.",
        "trial_finished": "⛔ <b>You have used all 2 trial items.</b>\n\nUpgrade for unlimited content retrieval.",
        "not_understood": "❓ I couldn't find a Telegram post link.\nTap “How to use” to see a valid example.",
        "payment": "💳 You selected <b>{label} — {price} THB / {days} days</b>\n\nSend a <b>TrueMoney gift voucher link</b> worth {price} THB.",
        "fetching": "📥 Fetching content…",
        "not_ready": "🔐 The owner account is not logged in yet.\nAn admin must complete /login, /code, and /twofa (if enabled) before fetching.",
        "access_denied": "⚠️ The owner account cannot access this post.\n\nMake sure it is a member of the source group/channel and can still open the post, then try again.",
        "not_found": "❌ No text or media was found in this post.",
        "text_sent": "✅ Text delivered.",
        "downloading": "⬇️ Downloading…",
        "download_failed": "❌ Download failed.",
        "uploading": "⬆️ Sending file ({size})…",
        "delivered": "✅ Content delivered!",
        "file_failed": "❌ Could not send the file: {error}",
        "too_large": "⚠️ This file is {size}, above the bot delivery limit ({limit}).\nLarge files are not supported yet. Please contact support.",
    },
}


def tr(lang: str, key: str, **values) -> str:
    return COPY.get(lang, COPY["th"])[key].format(**values)


_PLAN_ICON = {"lite": "🐢", "medium": "🚴", "core": "🚀"}


def plan_keyboard(lang: str = "th") -> InlineKeyboardMarkup:
    rows = []
    for key, plan in config.PLANS.items():
        icon = _PLAN_ICON.get(key, "📅")
        rows.append([
            InlineKeyboardButton(
                f"{icon} {plan['label']} — {plan['price']}฿ ({plan['days']} วัน, ~{plan['delay']}s/รายการ)",
                callback_data=f"buy:{key}",
            )
        ])
    rows.append([InlineKeyboardButton(tr(lang, "help_btn"), url=_support_url())])
    return InlineKeyboardMarkup(rows)


def main_keyboard(lang: str = "th") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "start_fetch"), callback_data="fetch")],
        [InlineKeyboardButton(tr(lang, "howto_btn"), callback_data="howto")],
        [InlineKeyboardButton("📌 เงื่อนไขการดึง" if lang == "th" else "📌 Access rules", callback_data="rules")],
        [InlineKeyboardButton(tr(lang, "myplan_btn"), callback_data="myplan")],
        [InlineKeyboardButton(tr(lang, "upgrade_btn"), callback_data="upgrade")],
        [InlineKeyboardButton(tr(lang, "language_btn"), callback_data="language")],
        [InlineKeyboardButton(tr(lang, "help_btn"), url=_support_url())],
    ])


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇹🇭 ไทย", callback_data="lang:th"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
    ]])


def normalize_phone(value: str) -> str | None:
    """Convert common phone formats to Telegram's E.164 format.

    Thai users commonly paste 08xxxxxxxx or +66 8xxxxxxxx. Telegram requires
    +668xxxxxxxx, without the domestic leading zero.
    """
    raw = re.sub(r"[\s().-]", "", (value or "").strip())
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    elif raw.startswith("0"):
        raw = "+66" + raw[1:]
    elif raw.startswith("66"):
        raw = "+" + raw
    if not re.fullmatch(r"\+[1-9]\d{7,14}", raw):
        return None
    return raw


def _support_url() -> str:
    c = config.SUPPORT_CONTACT.strip()
    if c.startswith("@"):
        return f"https://t.me/{c[1:]}"
    if c.startswith("http"):
        return c
    return f"https://t.me/{c}"


def _fmt_expiry(ts: int) -> str:
    if not ts or ts <= int(time.time()):
        return "ไม่มีสมาชิกที่ใช้งานได้"
    days_left = int((ts - time.time()) / 86400)
    return f"เหลืออีก {days_left} วัน"


# ── Bot builder ──────────────────────────────────────────────────────────────

def build_bot(user_client) -> Client:
    """Create the bot Client and register handlers.

    `user_client` is the owner UserClient used to actually fetch content.
    """
    bot = Client(
        "botsession",
        workdir="/tmp",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
    )

    if not config.ADMIN_ID:
        logger.warning(
            "ADMIN_ID is not configured — all admin commands are disabled. "
            "Set the ADMIN_ID environment variable to enable them."
        )

    def is_admin(uid: int) -> bool:
        # Never treat anyone as admin when ADMIN_ID is unset.
        return bool(config.ADMIN_ID) and uid == config.ADMIN_ID

    async def notify_admin(text: str):
        if not config.ADMIN_ID:
            return
        try:
            await bot.send_message(config.ADMIN_ID, text)
        except Exception as e:
            logger.warning(f"notify_admin failed: {e}")

    async def get_lang(uid: int) -> str:
        user = await db.get_user(uid)
        return user.get("language", "th") if user else "th"

    # ── Commands ────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("start") & filters.private)
    async def start_cmd(_, m: Message):
        await db.ensure_user(m.from_user.id, m.from_user.username or "")
        lang = await get_lang(m.from_user.id)
        await m.reply_text(
            tr(lang, "welcome"), reply_markup=main_keyboard(lang), disable_web_page_preview=True
        )

    @bot.on_message(filters.command("help") & filters.private)
    async def help_cmd(_, m: Message):
        lang = await get_lang(m.from_user.id)
        await m.reply_text(tr(lang, "howto"), reply_markup=main_keyboard(lang))

    @bot.on_message(filters.command("myplan") & filters.private)
    async def myplan_cmd(_, m: Message):
        await _send_myplan(m.from_user.id, m.reply_text)

    @bot.on_message(filters.command("id") & filters.private)
    async def id_cmd(_, m: Message):
        await m.reply_text(
            f"🆔 Telegram ID ของคุณคือ: <code>{m.from_user.id}</code>"
        )

    @bot.on_message(filters.command("upgrade") & filters.private)
    async def upgrade_cmd(_, m: Message):
        lang = await get_lang(m.from_user.id)
        await m.reply_text(tr(lang, "upgrade"), reply_markup=plan_keyboard(lang))

    async def _send_myplan(uid: int, reply):
        u = await db.get_user(uid)
        active = await db.is_active(uid)
        lang = u.get("language", "th") if u else "th"
        trial_used = int(u.get("trial_used", 0)) if u else 0
        remaining = max(0, config.TRIAL_MAX_ITEMS - trial_used)
        trial = tr(lang, "trial", remaining=remaining)
        if active:
            plan_key = u.get("plan_key", "") if u else ""
            plan = config.PLANS.get(plan_key)
            plan_label = plan["label"] if plan else "-"
            delay, preview = config.plan_speed(plan_key)
            preview_note = (
                (" + พรีวิวลิงก์ก่อนดึงจริง" if lang == "th" else " + link preview before fetching")
                if preview else ""
            )
            txt = tr(
                lang, "member",
                expiry=_fmt_expiry(int(u.get("expires_at", 0))),
                jobs=u.get("total_jobs", 0),
                plan_label=plan_label,
                delay=delay,
                preview_note=preview_note,
            )
        else:
            txt = tr(lang, "nonmember", trial=trial)
        await reply(txt, reply_markup=main_keyboard(lang))

    # ── Admin ─────────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("login") & filters.private)
    async def login_cmd(_, m: Message):
        if not is_admin(m.from_user.id):
            return
        parts = m.text.split(maxsplit=1)
        if len(parts) < 2:
            await m.reply_text(
                "การล็อกอินบัญชีเจ้าของ (แอดมินเท่านั้น):\n"
                "1) <code>/login 0812345678</code> หรือ <code>/login +66812345678</code>\n"
                "2) <code>/code 12345</code> กรอกรหัสที่ได้รับ\n"
                "3) ถ้ามี 2FA ใช้ <code>/twofa รหัสผ่าน</code>"
            )
            return
        phone = normalize_phone(parts[1])
        if not phone:
            await m.reply_text(
                "❌ รูปแบบเบอร์ไม่ถูกต้อง\n\n"
                "ใช้เบอร์แบบใดแบบหนึ่ง:\n"
                "• <code>/login 0812345678</code>\n"
                "• <code>/login +66812345678</code>\n\n"
                "ถ้าใช้ +66 แล้ว ห้ามใส่ 0 ซ้ำ เช่นไม่ใช่ +660812345678"
            )
            return
        res = await user_client.send_code(phone)
        if res.get("ok"):
            _pending_plan[m.from_user.id] = f"login:{phone}"
            await m.reply_text(
                "📲 ส่งรหัสไปที่แอป Telegram ของบัญชีนั้นแล้ว\n\n"
                "⚠️ <b>สำคัญมาก:</b> ห้ามพิมพ์รหัสติดกันตรง ๆ เช่น <code>/code 12345</code>\n"
                "Telegram จะบล็อกการล็อกอินทันที (มองว่าแชร์รหัส)\n\n"
                "✅ ให้พิมพ์แบบ <b>เว้นวรรคทีละตัว</b> แทน ตัวอย่าง:\n"
                "<code>/code 1 2 3 4 5</code>\n"
                "หรือคั่นด้วยขีด: <code>/code 1-2-3-4-5</code>"
            )
        else:
            error = res.get("error", "")
            if "PHONE_NUMBER_INVALID" in error:
                await m.reply_text(
                    "❌ Telegram ไม่ยอมรับเบอร์นี้\n"
                    "ตรวจสอบว่าเบอร์เป็นเบอร์ที่ผูกกับบัญชี Telegram และใช้รูปแบบ "
                    "<code>+66812345678</code> โดยไม่ใส่ 0 ซ้ำ"
                )
            else:
                await m.reply_text(f"❌ {error}")

    @bot.on_message(filters.command("code") & filters.private)
    async def code_cmd(_, m: Message):
        if not is_admin(m.from_user.id):
            return
        pending = _pending_plan.get(m.from_user.id, "")
        if not pending.startswith("login:"):
            await m.reply_text("เริ่มด้วย /login +เบอร์ ก่อนครับ")
            return
        phone = pending.split(":", 1)[1]
        parts = m.text.split(maxsplit=1)
        if len(parts) < 2:
            await m.reply_text("ใช้: <code>/code 1 2 3 4 5</code> (เว้นวรรคทีละตัว)")
            return
        # รับได้ทุกรูปแบบ: "1 2 3 4 5", "1-2-3-4-5", "12345" — ดึงเฉพาะตัวเลข
        code = "".join(ch for ch in parts[1] if ch.isdigit())
        if not code:
            await m.reply_text("ใช้: <code>/code 1 2 3 4 5</code> (เว้นวรรคทีละตัว)")
            return
        res = await user_client.sign_in(phone, code)
        if res.get("ok"):
            _pending_plan.pop(m.from_user.id, None)
            await m.reply_text("✅ ล็อกอินบัญชีเจ้าของสำเร็จ! บอทพร้อมดึงเนื้อหาแล้ว")
        elif res.get("need_2fa"):
            await m.reply_text("🔐 บัญชีเปิด 2FA — ใช้ <code>/twofa รหัสผ่าน</code>")
        else:
            err = str(res.get("error", ""))
            if "confirmed via" in err or "PHONE_CODE" in err.upper() or "declined" in err.lower():
                await m.reply_text(
                    "❌ Telegram บล็อกรหัสนี้แล้ว (ถูกมองว่าแชร์รหัสในแชต)\n\n"
                    "วิธีแก้:\n"
                    "1) ขอรหัสใหม่ด้วย /login +เบอร์ อีกครั้ง\n"
                    "2) พิมพ์รหัสแบบ<b>เว้นวรรคทีละตัว</b>: <code>/code 1 2 3 4 5</code>\n"
                    "3) ถ้ายังไม่ได้ ให้ล็อกอินผ่านหน้าเว็บแอดมินแทน (ปลอดภัยกว่า)"
                )
            else:
                await m.reply_text(f"❌ {err}")

    @bot.on_message(filters.command("twofa") & filters.private)
    async def twofa_cmd(_, m: Message):
        if not is_admin(m.from_user.id):
            return
        pending = _pending_plan.get(m.from_user.id, "")
        if not pending.startswith("login:"):
            await m.reply_text("เริ่มด้วย /login +เบอร์ ก่อนครับ")
            return
        phone = pending.split(":", 1)[1]
        parts = m.text.split(maxsplit=1)
        if len(parts) < 2:
            await m.reply_text("ใช้: <code>/twofa รหัสผ่าน</code>")
            return
        res = await user_client.sign_in(phone, "", parts[1].strip())
        if res.get("ok"):
            _pending_plan.pop(m.from_user.id, None)
            await m.reply_text("✅ ล็อกอินบัญชีเจ้าของสำเร็จ!")
        else:
            await m.reply_text(f"❌ {res.get('error')}")

    @bot.on_message(filters.command("stats") & filters.private)
    async def stats_cmd(_, m: Message):
        if not is_admin(m.from_user.id):
            return
        s = await db.stats()
        await m.reply_text(
            "📊 <b>สถิติ</b>\n\n"
            f"ผู้ใช้ทั้งหมด: {s['total_users']}\n"
            f"สมาชิกที่ใช้งานอยู่: {s['active']}\n"
            f"ซองที่รับแล้ว: {s['vouchers']}\n"
            f"รายได้รวม: {s['revenue']:.2f} บาท"
        )

    @bot.on_message(filters.command("grant") & filters.private)
    async def grant_cmd(_, m: Message):
        if not is_admin(m.from_user.id):
            return
        parts = m.text.split()
        if len(parts) < 3:
            await m.reply_text("ใช้: <code>/grant &lt;user_id&gt; &lt;วัน&gt;</code>")
            return
        try:
            uid, days = int(parts[1]), int(parts[2])
        except ValueError:
            await m.reply_text("รูปแบบไม่ถูกต้อง")
            return
        await db.ensure_user(uid)
        exp = await db.add_subscription(uid, days)
        await m.reply_text(f"✅ เพิ่ม {days} วันให้ {uid} แล้ว ({_fmt_expiry(exp)})")
        try:
            await bot.send_message(uid, f"🎉 คุณได้รับสมาชิก {days} วันจากแอดมิน!")
        except Exception:
            pass

    @bot.on_message(filters.command("grantme") & filters.private)
    async def grantme_cmd(_, m: Message):
        """Convenience command for the admin's own test subscription."""
        if not is_admin(m.from_user.id):
            await m.reply_text(
                "⛔ คำสั่งนี้สำหรับแอดมินเท่านั้น\n"
                f"ID ของคุณคือ <code>{m.from_user.id}</code> — "
                "หากคุณคือแอดมิน ให้ตั้งค่า ADMIN_ID ให้ตรงกับ ID นี้"
            )
            return
        parts = m.text.split()
        if len(parts) < 2:
            await m.reply_text("ใช้: <code>/grantme &lt;วัน&gt;</code>\nตัวอย่าง: <code>/grantme 30</code>")
            return
        try:
            days = int(parts[1])
            if days <= 0 or days > 3650:
                raise ValueError
        except ValueError:
            await m.reply_text("จำนวนวันต้องเป็นตัวเลขตั้งแต่ 1 ถึง 3650")
            return
        exp = await db.add_subscription(m.from_user.id, days)
        await m.reply_text(
            f"✅ เพิ่มสมาชิกให้ตัวเอง {days} วันแล้ว\n"
            f"หมดอายุ: {_fmt_expiry(exp)}"
        )

    # ── Callback buttons ───────────────────────────────────────────────────────

    @bot.on_callback_query()
    async def on_cb(_, cq: CallbackQuery):
        data = cq.data or ""
        uid = cq.from_user.id
        await db.ensure_user(uid, cq.from_user.username or "")
        lang = await get_lang(uid)
        if data == "fetch":
            if user_client.is_authorized:
                await cq.message.reply_text(tr(lang, "ready"), reply_markup=main_keyboard(lang))
            else:
                await cq.message.reply_text(
                    tr(lang, "login_required"), reply_markup=main_keyboard(lang)
                )
            await cq.answer()
        elif data == "howto":
            await cq.message.reply_text(tr(lang, "howto"), reply_markup=main_keyboard(lang))
            await cq.answer()
        elif data == "rules":
            await cq.message.reply_text(tr(lang, "access_rule"), reply_markup=main_keyboard(lang))
            await cq.answer()
        elif data == "language":
            await cq.message.reply_text(tr(lang, "language"), reply_markup=language_keyboard())
            await cq.answer()
        elif data.startswith("lang:"):
            selected = data.split(":", 1)[1]
            if selected not in {"th", "en"}:
                await cq.answer("Invalid language", show_alert=True)
                return
            await db.set_language(uid, selected)
            await cq.message.reply_text(
                tr(selected, "welcome"), reply_markup=main_keyboard(selected)
            )
            await cq.answer("บันทึกแล้ว" if selected == "th" else "Saved")
        elif data == "upgrade":
            await cq.message.reply_text(tr(lang, "upgrade"), reply_markup=plan_keyboard(lang))
            await cq.answer()
        elif data == "myplan":
            await _send_myplan(uid, cq.message.reply_text)
            await cq.answer()
        elif data.startswith("buy:"):
            key = data.split(":", 1)[1]
            plan = config.PLANS.get(key)
            if not plan:
                await cq.answer("แพ็กเกจไม่ถูกต้อง", show_alert=True)
                return
            _pending_plan[uid] = f"pay:{key}"
            await cq.message.reply_text(
                tr(lang, "payment", label=plan["label"], price=plan["price"], days=plan["days"])
            )
            await cq.answer()
        elif data == "confirm_fetch":
            ctx = _pending_fetch.pop(uid, None)
            await cq.answer()
            if not ctx:
                await cq.message.reply_text(tr(lang, "not_understood"), reply_markup=main_keyboard(lang))
                return
            await _run_fetch(cq.message, uid, ctx)
        elif data == "cancel_fetch":
            _pending_fetch.pop(uid, None)
            await cq.answer("ยกเลิกแล้ว" if lang == "th" else "Cancelled")
        else:
            await cq.answer()

    # ── Free-text: voucher or content link ─────────────────────────────────────

    @bot.on_message(filters.private & filters.text & ~filters.command([
        "start", "help", "myplan", "upgrade", "id", "login", "code", "twofa", "stats", "grant", "grantme",
    ]))
    async def on_text(_, m: Message):
        uid = m.from_user.id
        text = (m.text or "").strip()
        await db.ensure_user(uid, m.from_user.username or "")

        # 1) TrueMoney voucher?
        code = payment.extract_code(text)
        is_voucher_context = _pending_plan.get(uid, "").startswith("pay:") or "truemoney" in text.lower()
        if code and (is_voucher_context or "gift.truemoney" in text.lower()):
            await _handle_voucher(m, uid, code)
            return

        # 2) Telegram content link? (single or range: t.me/ch/100-300 or "link 300")
        try:
            _chat, _start, _end = parse_link(text)
            link, end_override = text, None
        except ValueError:
            # Check "link end_id" format: "https://t.me/ch/100 300"
            parts = text.rsplit(None, 1)
            if len(parts) == 2 and parts[1].isdigit():
                try:
                    _chat, _start, _end = parse_link(parts[0])
                    link, end_override = parts[0], int(parts[1])
                except ValueError:
                    link = None
            else:
                link = None

        if link is None:
            lang = await get_lang(uid)
            await m.reply_text(tr(lang, "not_understood"), reply_markup=main_keyboard(lang))
            return

        await _handle_content(m, uid, link, end_override)

    async def _handle_voucher(m: Message, uid: int, code: str):
        if not config.TRUEMONEY_WALLET_PHONE:
            await m.reply_text("⚠️ ระบบยังไม่ได้ตั้งค่าเบอร์รับเงิน กรุณาติดต่อแอดมิน")
            return
        # Atomically claim the code first: only one caller can proceed even under
        # concurrent/replayed submissions of the same voucher.
        if not await db.claim_voucher(code, uid):
            await m.reply_text("❌ ซองนี้ถูกใช้ไปแล้ว หรือกำลังถูกตรวจสอบอยู่")
            return
        status = await m.reply_text("⏳ กำลังตรวจสอบซอง…")
        res = await payment.redeem_voucher(code)
        if not res.get("ok"):
            # Release the claim so a genuinely-unused code can be retried.
            await db.release_voucher(code)
            await status.edit_text(f"❌ รับซองไม่สำเร็จ: {res.get('error')}")
            return

        amount = res.get("amount", 0)

        pending = _pending_plan.get(uid, "")
        chosen_key = pending.split(":", 1)[1] if pending.startswith("pay:") else None
        key, plan = config.plan_by_price(amount)

        if plan is None:
            # Record the amount (no grant) so revenue/stats stay accurate.
            await db.finalize_voucher(code, amount)
            await status.edit_text(
                f"✅ รับซองมูลค่า {amount:.2f} บาทแล้ว แต่ยอดไม่ตรงกับแพ็กเกจใด\n"
                "กรุณาติดต่อแอดมินเพื่อรับสิทธิ์ที่เหมาะสม"
            )
            await notify_admin(
                f"⚠️ ซองยอด {amount:.2f}฿ จาก {uid} (@{m.from_user.username}) "
                f"ไม่ตรงแพ็กเกจ — code {code}"
            )
            return

        # If they had chosen a plan, prefer matching that exact plan price.
        if chosen_key and config.PLANS[chosen_key]["price"] != int(round(amount)):
            await status.edit_text(
                f"⚠️ คุณเลือกแพ็กเกจ {config.PLANS[chosen_key]['label']} "
                f"({config.PLANS[chosen_key]['price']}฿) แต่ยอดซองคือ {amount:.2f}฿\n"
                f"ระบบจะให้สิทธิ์ตามยอดจริง: {plan['label']}"
            )
        # Finalize the voucher and grant the subscription in ONE transaction —
        # a paid voucher is never marked used without granting entitlement.
        # The matched plan's key (not necessarily chosen_key, if amount differed)
        # sets the delivery speed/preview the customer actually gets.
        exp = await db.finalize_and_grant(code, uid, amount, plan["days"], key)
        _pending_plan.pop(uid, None)
        preview_note = " + พรีวิวลิงก์ก่อนดึงจริง" if plan.get("preview") else ""
        await status.edit_text(
            f"🎉 ชำระเงินสำเร็จ! เปิดสมาชิก <b>{plan['label']}</b> แล้ว\n"
            f"อายุสมาชิก: {_fmt_expiry(exp)}\n"
            f"⚡ ความเร็ว: ~{plan['delay']} วิ/รายการ{preview_note}\n\n"
            "ส่งลิงก์โพสต์ Telegram เข้ามาเพื่อเริ่มดึงเนื้อหาได้เลย 🚀"
        )
        await notify_admin(
            f"💰 ชำระเงินใหม่: {amount:.2f}฿ → {plan['label']}\n"
            f"ผู้ใช้: {uid} (@{m.from_user.username})"
        )

    async def _handle_content(m: Message, uid: int, link: str, end_override: int = None):
        active = await db.is_active(uid)
        user = await db.get_user(uid)
        lang = user.get("language", "th") if user else "th"

        if not active:
            trial_used = int(user.get("trial_used", 0)) if user else 0
            if trial_used >= config.TRIAL_MAX_ITEMS:
                await m.reply_text(tr(lang, "trial_finished"), reply_markup=plan_keyboard(lang))
                return

        if not user_client.is_authorized:
            await m.reply_text(tr(lang, "not_ready"))
            await notify_admin("⚠️ มีผู้ใช้ส่งลิงก์แต่บัญชีเจ้าของยังไม่ได้ล็อกอิน (/login)")
            return

        # Determine range
        chat_id, start_id, end_id = parse_link(link)
        if end_override is not None:
            end_id = end_override
        is_range = end_id is not None and end_id > start_id

        # Speed/preview are set by the customer's active plan tier
        # (lite/medium/core). Non-members / trial users get the default
        # (slowest, no preview) pace.
        plan_key = user.get("plan_key", "") if (user and active) else ""
        delay, preview_enabled = config.plan_speed(plan_key)

        ctx = {
            "link": link, "active": active, "lang": lang, "delay": delay,
            "is_range": is_range, "start_id": start_id, "end_id": end_id,
        }

        if preview_enabled:
            await _send_preview(m, uid, chat_id, start_id, lang, ctx)
            return

        await _run_fetch(m, uid, ctx)

    async def _run_fetch(m: Message, uid: int, ctx: dict):
        """Runs the actual fetch/delivery — either directly, or after the
        customer confirms a Core-plan link preview."""
        link, active, lang, delay = ctx["link"], ctx["active"], ctx["lang"], ctx["delay"]
        is_range, start_id, end_id = ctx["is_range"], ctx["start_id"], ctx["end_id"]

        if is_range:
            msg_count = end_id - start_id + 1
            status = await m.reply_text(
                f"📥 กำลังดึง {msg_count} โพสต์ ({start_id}–{end_id})…"
                if lang == "th" else
                f"📥 Fetching {msg_count} posts ({start_id}–{end_id})…"
            )
            try:
                delivered = await _fetch_and_deliver_range(m, uid, link, start_id, end_id, status, lang, delay)
            except Exception:
                logger.exception("range fetch failed")
                delivered = False
                await status.edit_text(tr(lang, "access_denied"))
        else:
            status = await m.reply_text(tr(lang, "fetching"))
            try:
                delivered = await _fetch_and_deliver(m, uid, link, status, lang)
            except Exception:
                logger.exception("fetch failed")
                delivered = False
                await status.edit_text(tr(lang, "access_denied"))

        if delivered:
            if active:
                await db.record_usage(uid)
            else:
                await db.record_trial_usage(uid)
                fresh = await db.get_user(uid)
                remaining = max(0, config.TRIAL_MAX_ITEMS - int(fresh.get("trial_used", 0)))
                await m.reply_text(
                    tr(lang, "trial_done", remaining=remaining),
                    reply_markup=main_keyboard(lang) if remaining else plan_keyboard(lang),
                )

    async def _send_preview(m: Message, uid: int, chat_id, start_id: int, lang: str, ctx: dict):
        """Core-plan feature: show a thumbnail/preview of the linked post so the
        customer can confirm it matches what they expect BEFORE the real fetch
        (and its usage count) runs."""
        try:
            msg = await user_client.client.get_messages(chat_id, start_id)
        except Exception as e:
            logger.warning(f"preview fetch failed: {e}")
            msg = None

        if not msg or (not msg.media and not (msg.text and msg.text.strip())):
            await m.reply_text(tr(lang, "not_found"))
            return

        _pending_fetch[uid] = ctx
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ยืนยัน ดึงเลย" if lang == "th" else "✅ Confirm, fetch it",
                                  callback_data="confirm_fetch"),
            InlineKeyboardButton("❌ ยกเลิก" if lang == "th" else "❌ Cancel",
                                  callback_data="cancel_fetch"),
        ]])
        caption = (
            "🔍 <b>พรีวิว (Core)</b> — ตรวจสอบก่อนดึงจริง"
            if lang == "th" else
            "🔍 <b>Preview (Core)</b> — confirm before the real fetch"
        )
        if msg.caption:
            caption += f"\n\n{msg.caption[:200]}"
        elif msg.text:
            caption += f"\n\n{msg.text[:200]}"

        thumb_bytes = None
        try:
            thumbs = None
            if msg.video:
                thumbs = getattr(msg.video, "thumbs", None)
            elif msg.document:
                thumbs = getattr(msg.document, "thumbs", None)
            elif msg.animation:
                thumbs = getattr(msg.animation, "thumbs", None)
            if thumbs:
                raw = await user_client.client.download_media(thumbs[-1], in_memory=True)
            elif msg.photo:
                raw = await user_client.client.download_media(msg, in_memory=True)
            else:
                raw = None
            if raw:
                thumb_bytes = bytes(raw.getvalue()) if hasattr(raw, "getvalue") else bytes(raw)
        except Exception:
            pass  # preview thumbnail is best-effort; text preview still works

        if thumb_bytes:
            await m.reply_photo(io.BytesIO(thumb_bytes), caption=caption, reply_markup=kb)
        else:
            await m.reply_text(caption, reply_markup=kb)

    async def _fetch_and_deliver_range(
        m: Message, uid: int, link: str, start_id: int, end_id: int, status, lang: str,
        delay: float = config.DEFAULT_DELAY,
    ) -> bool:
        """Fetch a range of posts and deliver them one by one. Returns True if at least one was delivered.

        `delay` (seconds) paces each delivery and comes from the customer's
        plan tier (lite=17s, medium=5s, core=1.5s) — this is the concrete
        difference in "how fast a job finishes" between plans.
        """
        chat_id, _s, _e = parse_link(link)
        total = end_id - start_id + 1
        delivered_count = 0
        skipped_count = 0
        MAX_RANGE = 500
        actual_end = min(end_id, start_id + MAX_RANGE - 1)

        for msg_id in range(start_id, actual_end + 1):
            if not user_client.is_authorized:
                break
            try:
                msg = await user_client.client.get_messages(chat_id, msg_id)
                if not msg or (not msg.media and not (msg.text and msg.text.strip())):
                    skipped_count += 1
                    continue

                done = delivered_count + skipped_count + 1
                await status.edit_text(
                    f"📥 {done}/{total} — กำลังส่ง…" if lang == "th"
                    else f"📥 {done}/{total} — sending…"
                )

                if not msg.media and msg.text:
                    await bot.send_message(uid, msg.text)
                    delivered_count += 1
                    await asyncio.sleep(delay)
                    continue

                size = _media_size(msg)
                if size > MAX_DELIVERY_BYTES:
                    skipped_count += 1
                    continue

                raw = await user_client.client.download_media(msg, in_memory=True)
                if not raw:
                    skipped_count += 1
                    continue

                data = bytes(raw.getvalue()) if hasattr(raw, "getvalue") else bytes(raw)
                fname = getattr(raw, "name", f"file_{msg_id}")
                caption = getattr(msg, "caption", "") or ""
                forwarder = BotForwarder(config.BOT_TOKEN, str(uid))
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

                def _send(d=data, fn=fname, cap=caption, ex=ext):
                    import tempfile, os
                    suffix = f".{ex}" if ex else ""
                    tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    try:
                        tf.write(d); tf.close()
                        from pathlib import Path as _P
                        return forwarder.send_file(_P(tf.name), caption=cap)
                    finally:
                        try: os.unlink(tf.name)
                        except Exception: pass

                ok, _err = await asyncio.to_thread(_send)
                if ok:
                    delivered_count += 1
                else:
                    skipped_count += 1
                await asyncio.sleep(delay)

            except Exception as e:
                logger.warning(f"range fetch msg {msg_id}: {e}")
                skipped_count += 1

        summary = (
            f"✅ เสร็จแล้ว — ส่งสำเร็จ {delivered_count} / ข้าม {skipped_count} โพสต์"
            if lang == "th" else
            f"✅ Done — delivered {delivered_count} / skipped {skipped_count} posts"
        )
        await status.edit_text(summary)
        return delivered_count > 0

    async def _fetch_and_deliver(
        m: Message, uid: int, link: str, status, lang: str
    ) -> bool:
        """Fetch content and deliver via the bot. Returns True only if the
        customer actually received content (so usage is counted only then)."""
        chat_id, msg_id, _end = parse_link(link)
        msg = await user_client.client.get_messages(chat_id, msg_id)
        if not msg or (not msg.media and not (msg.text and msg.text.strip())):
            await status.edit_text(tr(lang, "not_found"))
            return False

        # Text-only
        if not msg.media and msg.text:
            await bot.send_message(uid, msg.text)
            await status.edit_text(tr(lang, "text_sent"))
            return True

        # Enforce Bot API delivery cap BEFORE downloading, so paid users aren't
        # led through a "success" flow for media the bot cannot deliver.
        size = _media_size(msg)
        if size > MAX_DELIVERY_BYTES:
            await status.edit_text(
                tr(
                    lang, "too_large",
                    size=_fmt_size(size), limit=_fmt_size(MAX_DELIVERY_BYTES),
                )
            )
            return False

        await status.edit_text(tr(lang, "downloading"))

        def progress(cur, tot):
            pass

        raw = await user_client.client.download_media(msg, in_memory=True, progress=progress)
        if not raw:
            await status.edit_text(tr(lang, "download_failed"))
            return False

        data = bytes(raw.getvalue()) if hasattr(raw, "getvalue") else bytes(raw)
        fname = getattr(raw, "name", f"file_{msg_id}")
        caption = getattr(msg, "caption", "") or ""

        await status.edit_text(tr(lang, "uploading", size=_fmt_size(len(data))))

        # Deliver through the bot so it reliably reaches the customer.
        forwarder = BotForwarder(config.BOT_TOKEN, str(uid))
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

        def _send_blocking():
            import tempfile, os
            suffix = f".{ext}" if ext else ""
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            try:
                tf.write(data)
                tf.close()
                from pathlib import Path as _P
                return forwarder.send_file(_P(tf.name), caption=caption)
            finally:
                try:
                    os.unlink(tf.name)
                except Exception:
                    pass

        ok, err = await asyncio.to_thread(_send_blocking)
        if ok:
            await status.edit_text(tr(lang, "delivered"))
            return True
        await status.edit_text(tr(lang, "file_failed", error=err))
        return False

    return bot
