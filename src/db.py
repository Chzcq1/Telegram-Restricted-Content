"""SQLite persistence for subscriptions, usage tracking, and redeemed vouchers.

Uses aiosqlite so all DB access is async and safe to run on the shared event
loop that also drives Pyrogram.
"""
import time
import aiosqlite
from pathlib import Path

DB_PATH = str(Path("data.db").absolute())


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                expires_at  INTEGER DEFAULT 0,   -- unix ts; 0 = no subscription
                plan_key    TEXT DEFAULT '',      -- last purchased plan (lite/medium/core)
                total_jobs  INTEGER DEFAULT 0,
                trial_used  INTEGER DEFAULT 0,
                language    TEXT DEFAULT 'th',
                created_at  INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS vouchers (
                code        TEXT PRIMARY KEY,
                user_id     INTEGER,
                amount      REAL,
                redeemed_at INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                user_id     INTEGER,
                used_at     INTEGER
            )
            """
        )
        # Safe migrations for databases created before trial/language support.
        cur = await db.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cur.fetchall()}
        if "trial_used" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0")
        if "language" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'th'")
        if "plan_key" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN plan_key TEXT DEFAULT ''")
        await db.commit()


async def ensure_user(user_id: int, username: str = ""):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username, now),
        )
        await db.commit()


async def set_language(user_id: int, language: str):
    """Persist the user's selected UI language."""
    if language not in {"th", "en"}:
        raise ValueError("unsupported language")
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET language=? WHERE user_id=?", (language, user_id)
        )
        await db.commit()


async def get_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {}


async def is_active(user_id: int) -> bool:
    u = await get_user(user_id)
    return bool(u) and int(u.get("expires_at", 0)) > int(time.time())


async def _extend_stmt(db, user_id: int, days: int, now: int, plan_key: str = None):
    """Atomically extend expiry within a single SQL statement.

    New expiry = MAX(current_expiry, now) + days. Because the computation reads
    the row's own value inside the UPDATE, concurrent extensions for the same
    user stack correctly instead of one overwriting the other. Upsert also covers
    first-time payers who never sent /start.

    If `plan_key` is given, it becomes the user's active plan tier (used to pick
    delivery speed/preview). Admin grants (plan_key=None) extend days without
    changing the tier.
    """
    delta = days * 86400
    if plan_key is not None:
        await db.execute(
            "INSERT INTO users (user_id, expires_at, plan_key, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "expires_at = MAX(users.expires_at, ?) + ?, plan_key = ?",
            (user_id, now + delta, plan_key, now, now, delta, plan_key),
        )
    else:
        await db.execute(
            "INSERT INTO users (user_id, expires_at, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "expires_at = MAX(users.expires_at, ?) + ?",
            (user_id, now + delta, now, now, delta),
        )


async def add_subscription(user_id: int, days: int) -> int:
    """Extend the user's subscription by `days` (admin grant; plan tier unchanged).
    Returns new expiry unix ts."""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await _extend_stmt(db, user_id, days, now)
        await db.commit()
        cur = await db.execute(
            "SELECT expires_at FROM users WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else now + days * 86400


async def finalize_and_grant(code: str, user_id: int, amount: float, days: int, plan_key: str) -> int:
    """Record the voucher amount AND extend the subscription in one transaction.

    Either both the voucher is finalized and the subscription granted, or neither
    is — so a paid voucher is never marked used without granting the entitlement.
    Sets the user's plan_key so delivery speed/preview match what they paid for.
    Returns the new expiry unix ts.
    """
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                "UPDATE vouchers SET amount=?, redeemed_at=? WHERE code=?",
                (amount, now, code),
            )
            await _extend_stmt(db, user_id, days, now, plan_key=plan_key)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        cur = await db.execute(
            "SELECT expires_at FROM users WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else now + days * 86400


async def voucher_used(code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM vouchers WHERE code=?", (code,))
        return await cur.fetchone() is not None


async def claim_voucher(code: str, user_id: int) -> bool:
    """Atomically claim a voucher code for processing.

    Relies on the PRIMARY KEY on `code`: the INSERT succeeds for exactly one
    caller even under concurrent submissions. Returns True only for the caller
    that won the claim; all others get False (already used / being processed).
    Amount is filled in later by finalize_voucher(); a claim with amount IS NULL
    means "in flight".
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                "INSERT INTO vouchers (code, user_id, amount, redeemed_at) "
                "VALUES (?, ?, NULL, ?)",
                (code, user_id, int(time.time())),
            )
            await db.commit()
            return cur.rowcount == 1
        except aiosqlite.IntegrityError:
            return False


async def finalize_voucher(code: str, amount: float):
    """Record the redeemed amount on a previously claimed voucher."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE vouchers SET amount=?, redeemed_at=? WHERE code=?",
            (amount, int(time.time()), code),
        )
        await db.commit()


async def release_voucher(code: str):
    """Release a claim that failed to redeem so the code can be retried."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM vouchers WHERE code=? AND amount IS NULL", (code,)
        )
        await db.commit()


async def record_usage(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO usage (user_id, used_at) VALUES (?, ?)",
            (user_id, int(time.time())),
        )
        await db.execute(
            "UPDATE users SET total_jobs = total_jobs + 1 WHERE user_id=?", (user_id,)
        )
        await db.commit()


async def record_trial_usage(user_id: int):
    """Atomically consume one trial item and count it as a completed job."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET trial_used = trial_used + 1, total_jobs = total_jobs + 1 "
            "WHERE user_id=?",
            (user_id,),
        )
        await db.execute(
            "INSERT INTO usage (user_id, used_at) VALUES (?, ?)",
            (user_id, int(time.time())),
        )
        await db.commit()


async def usage_today(user_id: int) -> int:
    day_start = int(time.time()) - 86400
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM usage WHERE user_id=? AND used_at>=?",
            (user_id, day_start),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def last_usage(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT MAX(used_at) FROM usage WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] else 0


async def stats() -> dict:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE expires_at>?", (now,)
        )
        active = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM vouchers WHERE amount IS NOT NULL"
        )
        revenue = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM vouchers WHERE amount IS NOT NULL"
        )
        voucher_count = (await cur.fetchone())[0]
    return {
        "total_users": total_users,
        "active": active,
        "revenue": revenue,
        "vouchers": voucher_count,
    }
