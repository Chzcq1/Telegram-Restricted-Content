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


# ── Bilingual customer-facing copy ───────────────────────────────────────────

COPY = {
    "th": {
        "welcome": "👋 <b>ยินดีต้อนรับ!</b>\n\nส่งลิงก์โพสต์ Telegram มาให้บอทเพื่อรับข้อความ รูป หรือวิดีโอ\n\n🎁 <b>เริ่มทดลองฟรีได้ 2 รายการ</b> ต่อ 1 บัญชี\nกด <b>เริ่มดึงเนื้อหา</b> แล้วส่งลิงก์โพสต์ได้เลย",
        "language": "🌐 <b>เลือกภาษา</b>\nคุณเปลี่ยนภาษาได้ตลอดเวลาจากเมนู",
        "howto": "📖 <b>วิธีใช้งาน</b>\n\n1️⃣ เปิดโพสต์ Telegram ที่ต้องการ\n2️⃣ กด <b>คัดลอกลิงก์</b> ของโพสต์\n3️⃣ กลับมาที่บอท แล้วกด <b>เริ่มดึงเนื้อหา</b>\n4️⃣ วางและส่งลิงก์\n\nตัวอย่าง:\n<code>https://t.me/channel_name/123</code>\n\n🎁 ทดลองฟรีได้ 2 รายการต่อบัญชี\n💎 เมื่อครบแล้ว เลือกแพ็กเกจเพื่อใช้งานไม่จำกัด\n\n<b>หมายเหตุ:</b> ระบบดึงได้เฉพาะโพสต์ที่บัญชีระบบมีสิทธิ์เข้าถึงเท่านั้น",
        "ready": "📎 <b>พร้อมแล้ว!</b>\nส่งลิงก์โพสต์ Telegram ที่ต้องการดึงมาได้เลย\n\nตัวอย่าง: <code>https://t.me/channel_name/123</code>",
        "upgrade": "💎 <b>อัปเกรดเป็นสมาชิก</b>\n\n✅ ดึงเนื้อหาได้ไม่จำกัด\n✅ ไม่มีข้อจำกัดโปรทดลอง\n\nชำระผ่านซองอั่งเปา TrueMoney แล้วเลือกแพ็กเกจด้านล่าง",
        "start_fetch": "🚀 เริ่มดึงเนื้อหา",
        "howto_btn": "📖 วิธีใช้งาน",
        "myplan_btn": "📋 สถานะของฉัน",
        "upgrade_btn": "💎 อัปเกรด",
        "language_btn": "🌐 ภาษา / Language",
        "help_btn": "🎧 ช่วยเหลือ",
        "trial": "🎁 โปรทดลองคงเหลือ: <b>{remaining}/2</b> รายการ",
        "member": "✅ <b>สมาชิกใช้งานได้</b>\n{expiry}\nใช้งานสำเร็จ: {jobs} ครั้ง",
        "nonmember": "📋 <b>สถานะของฉัน</b>\nยังไม่ได้เป็นสมาชิก\n{trial}\n\nกด “เริ่มดึงเนื้อหา” เพื่อใช้สิทธิ์ทดลอง หรืออัปเกรดเพื่อใช้งานไม่จำกัด",
        "trial_done": "🎉 ดึงสำเร็จแล้ว! เหลือสิทธิ์ทดลอง <b>{remaining}/2</b> รายการ",
        "trial_finished": "⛔ <b>คุณใช้สิทธิ์ทดลองครบ 2 รายการแล้ว</b>\n\nอัปเกรดเป็นสมาชิกเพื่อดึงเนื้อหาได้ไม่จำกัด",
        "not_understood": "❓ ไม่พบลิงก์โพสต์ Telegram\nกด “วิธีใช้งาน” เพื่อดูตัวอย่างลิงก์ที่ถูกต้อง",
        "payment": "💳 คุณเลือกแพ็กเกจ <b>{label} — {price} บาท</b>\n\nส่ง <b>ลิงก์ซองอั่งเปา TrueMoney</b> มูลค่า {price} บาทเข้ามาได้เลย",
        "fetching": "📥 กำลังดึงเนื้อหา…",
        "not_ready": "⚠️ ระบบยังไม่พร้อม กรุณาติดต่อแอดมิน",
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
        "howto": "📖 <b>How to use</b>\n\n1️⃣ Open the Telegram post you want\n2️⃣ Tap <b>Copy Link</b>\n3️⃣ Return here and tap <b>Start fetching</b>\n4️⃣ Paste and send the link\n\nExample:\n<code>https://t.me/channel_name/123</code>\n\n🎁 You get 2 trial items per account.\n💎 Upgrade after that for unlimited use.\n\n<b>Note:</b> The system can only retrieve posts the owner account is allowed to access.",
        "ready": "📎 <b>Ready!</b>\nSend the Telegram post link you want to fetch.\n\nExample: <code>https://t.me/channel_name/123</code>",
        "upgrade": "💎 <b>Upgrade your membership</b>\n\n✅ Unlimited content retrieval\n✅ No trial limit\n\nPay with a TrueMoney gift voucher, then choose a plan below.",
        "start_fetch": "🚀 Start fetching",
        "howto_btn": "📖 How to use",
        "myplan_btn": "📋 My status",
        "upgrade_btn": "💎 Upgrade",
        "language_btn": "🌐 Language / ภาษา",
        "help_btn": "🎧 Help",
        "trial": "🎁 Trial remaining: <b>{remaining}/2</b> items",
        "member": "✅ <b>Active member</b>\n{expiry}\nCompleted: {jobs} items",
        "nonmember": "📋 <b>My status</b>\nNo active membership\n{trial}\n\nTap “Start fetching” to use your trial, or upgrade for unlimited access.",
        "trial_done": "🎉 Done! You have <b>{remaining}/2</b> trial items left.",
        "trial_finished": "⛔ <b>You have used all 2 trial items.</b>\n\nUpgrade for unlimited content retrieval.",
        "not_understood": "❓ I couldn't find a Telegram post link.\nTap “How to use” to see a valid example.",
        "payment": "💳 You selected <b>{label} — {price} THB</b>\n\nSend a <b>TrueMoney gift voucher link</b> worth {price} THB.",
        "fetching": "📥 Fetching content…",
        "not_ready": "⚠️ The system is not ready. Please contact support.",
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


def plan_keyboard(lang: str = "th") -> InlineKeyboardMarkup:
    rows = []
    for key, plan in config.PLANS.items():
        rows.append([
            InlineKeyboardButton(
                f"📅 {plan['label']} — {plan['price']}฿",
                callback_data=f"buy:{key}",
            )
        ])
    rows.append([InlineKeyboardButton(tr(lang, "help_btn"), url=_support_url())])
    return InlineKeyboardMarkup(rows)


def main_keyboard(lang: str = "th") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "start_fetch"), callback_data="fetch")],
        [InlineKeyboardButton(tr(lang, "howto_btn"), callback_data="howto")],
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
            txt = tr(
                lang, "member",
                expiry=_fmt_expiry(int(u.get("expires_at", 0))),
                jobs=u.get("total_jobs", 0),
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
                "1) <code>/login +66xxxxxxxxx</code> เพื่อรับรหัส\n"
                "2) <code>/code 12345</code> กรอกรหัสที่ได้รับ\n"
                "3) ถ้ามี 2FA ใช้ <code>/twofa รหัสผ่าน</code>"
            )
            return
        phone = parts[1].strip()
        res = await user_client.send_code(phone)
        if res.get("ok"):
            _pending_plan[m.from_user.id] = f"login:{phone}"
            await m.reply_text("📲 ส่งรหัสไปที่ Telegram แล้ว — ใช้ /code <รหัส>")
        else:
            await m.reply_text(f"❌ {res.get('error')}")

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
            await m.reply_text("ใช้: <code>/code 12345</code>")
            return
        res = await user_client.sign_in(phone, parts[1].strip())
        if res.get("ok"):
            _pending_plan.pop(m.from_user.id, None)
            await m.reply_text("✅ ล็อกอินบัญชีเจ้าของสำเร็จ! บอทพร้อมดึงเนื้อหาแล้ว")
        elif res.get("need_2fa"):
            await m.reply_text("🔐 บัญชีเปิด 2FA — ใช้ <code>/twofa รหัสผ่าน</code>")
        else:
            await m.reply_text(f"❌ {res.get('error')}")

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
            await cq.message.reply_text(tr(lang, "ready"), reply_markup=main_keyboard(lang))
            await cq.answer()
        elif data == "howto":
            await cq.message.reply_text(tr(lang, "howto"), reply_markup=main_keyboard(lang))
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
                tr(lang, "payment", label=plan["label"], price=plan["price"])
            )
            await cq.answer()
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

        # 2) Telegram content link?
        try:
            parse_link(text)
        except ValueError:
            lang = await get_lang(uid)
            await m.reply_text(tr(lang, "not_understood"), reply_markup=main_keyboard(lang))
            return

        await _handle_content(m, uid, text)

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
        exp = await db.finalize_and_grant(code, uid, amount, plan["days"])
        _pending_plan.pop(uid, None)
        await status.edit_text(
            f"🎉 ชำระเงินสำเร็จ! เปิดสมาชิก <b>{plan['label']}</b> แล้ว\n"
            f"อายุสมาชิก: {_fmt_expiry(exp)}\n\n"
            "ส่งลิงก์โพสต์ Telegram เข้ามาเพื่อเริ่มดึงเนื้อหาได้เลย 🚀"
        )
        await notify_admin(
            f"💰 ชำระเงินใหม่: {amount:.2f}฿ → {plan['label']}\n"
            f"ผู้ใช้: {uid} (@{m.from_user.username})"
        )

    async def _handle_content(m: Message, uid: int, link: str):
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

        status = await m.reply_text(tr(lang, "fetching"))
        try:
            delivered = await _fetch_and_deliver(m, uid, link, status, lang)
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
        except Exception as e:
            logger.exception("fetch failed")
            await status.edit_text(f"❌ ดึงเนื้อหาไม่สำเร็จ: {e}")

    async def _fetch_and_deliver(
        m: Message, uid: int, link: str, status, lang: str
    ) -> bool:
        """Fetch content and deliver via the bot. Returns True only if the
        customer actually received content (so usage is counted only then)."""
        chat_id, msg_id = parse_link(link)
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
