"""TrueMoney gift-voucher (angpao) redemption via the configured gateway.

Redeeming a voucher deposits its balance into the wallet phone number set in
TRUEMONEY_WALLET_PHONE. This module never handles anyone else's credentials —
it only forwards the voucher code the customer sent to the bot.
"""
import re
import asyncio
import requests
from . import config

_CODE_RE = re.compile(r"(?:\?v=|/campaign/\?v=|v=)?([A-Za-z0-9]{18,})")


def extract_code(text: str) -> str | None:
    """Pull the voucher code out of a full URL or a bare code."""
    text = (text or "").strip()
    m = re.search(r"[?&]v=([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    # bare code (TrueMoney voucher codes are long alphanumeric strings)
    if re.fullmatch(r"[A-Za-z0-9]{18,}", text):
        return text
    return None


def _redeem_sync(code: str) -> dict:
    phone = config.TRUEMONEY_WALLET_PHONE
    url = f"{config.VOUCHER_GATEWAY}/{code}/{phone}/"
    try:
        r = requests.get(url, timeout=30)
        data = r.json()
    except Exception as e:
        return {"ok": False, "error": f"เชื่อมต่อระบบชำระเงินไม่สำเร็จ: {e}"}

    code_str = str(data.get("code", ""))
    if code_str == "200":
        amount = 0.0
        try:
            amount = float((data.get("data") or {}).get("amount", 0))
        except (TypeError, ValueError):
            amount = 0.0
        return {"ok": True, "amount": amount, "raw": data}

    return {
        "ok": False,
        "error": data.get("message") or "ไม่สามารถรับซองได้",
        "error_en": data.get("message_en", ""),
        "raw": data,
    }


async def redeem_voucher(code: str) -> dict:
    """Async wrapper — runs the blocking HTTP call in a thread."""
    return await asyncio.to_thread(_redeem_sync, code)
