import os
import asyncio
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")


class UserClient:
    def __init__(self):
        self.client = Client(
            "mysession",
            api_id=API_ID,
            api_hash=API_HASH,
            no_updates=True,
        )
        self.is_authorized = False
        self._phone_code_hash = None

    async def connect(self):
        await self.client.connect()
        try:
            self.is_authorized = await self.client.storage.is_user_authorized()
        except Exception:
            self.is_authorized = False

    async def send_code(self, phone: str) -> dict:
        try:
            sent = await self.client.send_code(phone)
            self._phone_code_hash = sent.phone_code_hash
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def sign_in(self, phone: str, code: str, password: str = "") -> dict:
        try:
            await self.client.sign_in(phone, self._phone_code_hash, code)
            self.is_authorized = True
            return {"ok": True}
        except SessionPasswordNeeded:
            if not password:
                return {"ok": False, "need_2fa": True}
            try:
                await self.client.check_password(password)
                self.is_authorized = True
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": f"2FA failed: {e}"}
        except (PhoneCodeInvalid, PhoneCodeExpired) as e:
            return {"ok": False, "error": "Invalid or expired code. Please try again."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_me(self) -> dict:
        try:
            me = await self.client.get_me()
            name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            return {"name": name, "username": me.username, "phone": me.phone_number}
        except Exception:
            return {}
