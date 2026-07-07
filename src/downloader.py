import os
import re
import asyncio
import base64
import datetime
import requests as _requests
from pathlib import Path
from typing import List, Optional

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)


class BotForwarder:
    """Sends downloaded files to a Telegram chat via Bot API, then deletes them."""

    def __init__(self, bot_token: str, target_chat_id: str):
        self.bot_token = bot_token.strip()
        self.target_chat_id = target_chat_id.strip()
        self._base = f"https://api.telegram.org/bot{self.bot_token}"

    def validate(self) -> tuple:
        """Check bot token is valid. Returns (ok: bool, username_or_error: str)."""
        try:
            r = _requests.get(f"{self._base}/getMe", timeout=10)
            data = r.json()
            if data.get("ok"):
                return True, data["result"].get("username", "bot")
            return False, data.get("description", "Invalid token")
        except Exception as e:
            return False, str(e)

    def send_file(self, file_path: Path, caption: str = "") -> tuple:
        """Upload file to target chat. Returns (ok: bool, error: str)."""
        ext = file_path.suffix.lower()
        if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            method, field = "sendVideo", "video"
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            method, field = "sendPhoto", "photo"
        elif ext == ".gif":
            method, field = "sendAnimation", "animation"
        else:
            method, field = "sendDocument", "document"
        try:
            with open(file_path, "rb") as f:
                resp = _requests.post(
                    f"{self._base}/{method}",
                    data={"chat_id": self.target_chat_id, "caption": caption[:1024]},
                    files={field: f},
                    timeout=600,
                )
            data = resp.json()
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "Unknown error")
        except Exception as e:
            return False, str(e)

    def send_album(self, items: list) -> tuple:
        """Send multiple files as a Telegram album (sendMediaGroup).

        items: list of dicts with keys: path (Path), caption (str), type (str)
        Returns (ok: bool, error: str).
        Max 10 items per album — caller must chunk if needed.
        """
        import json as _json

        media_json = []
        files_payload = {}

        for i, item in enumerate(items[:10]):
            path: Path = item["path"]
            caption: str = item.get("caption", "")
            ext = path.suffix.lower()

            if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                media_type = "video"
            elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                media_type = "photo"
            elif ext in (".mp3", ".ogg", ".m4a", ".flac", ".wav"):
                media_type = "audio"
            else:
                media_type = "document"

            attach_key = f"file{i}"
            entry = {"type": media_type, "media": f"attach://{attach_key}"}
            if caption and i == 0:
                entry["caption"] = caption[:1024]
            media_json.append(entry)
            files_payload[attach_key] = open(path, "rb")

        try:
            resp = _requests.post(
                f"{self._base}/sendMediaGroup",
                data={
                    "chat_id": self.target_chat_id,
                    "media": _json.dumps(media_json),
                },
                files=files_payload,
                timeout=600,
            )
            data = resp.json()
            return (True, "") if data.get("ok") else (False, data.get("description", "Unknown error"))
        except Exception as e:
            return False, str(e)
        finally:
            for f in files_payload.values():
                try:
                    f.close()
                except Exception:
                    pass

    def send_text(self, text: str) -> tuple:
        """Send a plain text message to target chat. Returns (ok: bool, error: str)."""
        try:
            resp = _requests.post(
                f"{self._base}/sendMessage",
                data={"chat_id": self.target_chat_id, "text": text[:4096]},
                timeout=30,
            )
            data = resp.json()
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "Unknown error")
        except Exception as e:
            return False, str(e)


def parse_link(link: str):
    link = link.strip()
    private = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
    if private:
        return int(f"-100{private.group(1)}"), int(private.group(2))
    public = re.match(r"https://t\.me/([^/?]+)/(\d+)", link)
    if public:
        return public.group(1), int(public.group(2))
    raise ValueError(f"Unrecognised link format: {link}")


def parse_target_chat(to_chat_id: str):
    """Parse target chat ID, supporting 'chatid_threadid' format for forum topics.
    Returns (chat_id: int|str, thread_id: int|None).
    Examples:
      '-1001234567890'     → (-1001234567890, None)
      '-1001234567890_5'   → (-1001234567890, 5)
      '@mychannel'         → ('@mychannel', None)
    """
    s = to_chat_id.strip()
    if "_" in s:
        parts = s.rsplit("_", 1)
        if parts[1].isdigit():
            chat_part = parts[0]
            thread_id = int(parts[1])
            chat_id = int(chat_part) if chat_part.lstrip("-").isdigit() else chat_part
            return chat_id, thread_id
    chat_id = int(s) if s.lstrip("-").isdigit() else s
    return chat_id, None


def _fmt_size(size: int) -> str:
    if size >= 1_073_741_824:
        return f"{size / 1_073_741_824:.1f} GB"
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


class BatchDownloader:
    def __init__(self, tg_client, state: dict):
        self.tg = tg_client
        self.state = state

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        log = self.state["log"]
        log.append(entry)
        # Keep only the most recent 300 entries to prevent memory bloat
        # and huge JSON payloads on every status poll.
        if len(log) > 300:
            del log[:-300]
        print(entry)

    @staticmethod
    def _make_link(chat_id, msg_id: int) -> str:
        """Reconstruct a t.me link from a chat_id and message ID."""
        if isinstance(chat_id, int):
            # chat_id is like -1001234567890; strip the "-100" prefix for t.me/c/
            return f"https://t.me/c/{str(chat_id)[4:]}/{msg_id}"
        return f"https://t.me/{chat_id}/{msg_id}"

    # ── Thumbnail Scanner ──────────────────────────────────────────────────────

    async def scan_thumbnails(self, link: str, count: int, start_offset: int = 0) -> list:
        """Scan up to `count` messages and return thumbnail + metadata for each."""
        chat_id, base_id = parse_link(link)
        start_id = base_id + start_offset
        limit = min(count, 24)
        results = []

        for i in range(limit):
            msg_id = start_id + i
            entry = {"msg_id": msg_id, "has_media": False, "thumb": None,
                     "type": None, "size": None, "duration": None, "error": None}
            try:
                msg = await self.tg.client.get_messages(chat_id, msg_id)
                if not msg or not msg.media:
                    results.append(entry)
                    continue

                entry["has_media"] = True

                # Determine type + metadata
                if msg.video:
                    entry["type"] = "video"
                    entry["size"] = _fmt_size(msg.video.file_size or 0)
                    entry["duration"] = msg.video.duration or 0
                    thumbs = getattr(msg.video, "thumbs", None)
                elif msg.document:
                    entry["type"] = "document"
                    entry["size"] = _fmt_size(msg.document.file_size or 0)
                    thumbs = getattr(msg.document, "thumbs", None)
                elif msg.photo:
                    entry["type"] = "photo"
                    thumbs = None  # we'll download the photo itself at low res
                elif msg.animation:
                    entry["type"] = "animation"
                    entry["size"] = _fmt_size(msg.animation.file_size or 0)
                    thumbs = getattr(msg.animation, "thumbs", None)
                else:
                    entry["type"] = str(msg.media).split(".")[-1]
                    thumbs = None

                # Fetch thumbnail bytes
                try:
                    if thumbs:
                        raw = await self.tg.client.download_media(thumbs[-1], in_memory=True)
                    elif msg.photo:
                        raw = await self.tg.client.download_media(
                            msg.photo.thumbs[-1] if msg.photo.thumbs else msg,
                            in_memory=True
                        )
                    else:
                        raw = None

                    if raw:
                        data = bytes(raw.getvalue()) if hasattr(raw, "getvalue") else bytes(raw)
                        entry["thumb"] = base64.b64encode(data).decode()
                except Exception:
                    pass  # thumbnail optional

            except Exception as e:
                entry["error"] = str(e)

            results.append(entry)

        return results

    # ── Copy via user account (server-side, no file size limit) ──────────────

    async def copy_to_chat(self, link: str, count: int, start_offset: int = 0,
                           to_chat_id: str = ""):
        """Server-side copy (copy_message) — no download, no file-size limit."""
        target, thread_id = parse_target_chat(to_chat_id)
        self.state.update({
            "running": True, "total": count, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": True,
        })
        try:
            chat_id, base_id = parse_link(link)
            start_id = base_id + start_offset
            self._log(
                f"Copy via account — {chat_id} [{start_id}→{start_id+count-1}] → {target}"
                + (f" (topic {thread_id})" if thread_id else "")
            )
            await self._resolve_peer(target)
            await self._copy_ids(chat_id, list(range(start_id, start_id + count)), target, thread_id)
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    async def copy_specific_to_chat(self, link: str, msg_ids: List[int],
                                    to_chat_id: str = ""):
        """Server-side copy of specific message IDs — no download, no file-size limit."""
        target, thread_id = parse_target_chat(to_chat_id)
        self.state.update({
            "running": True, "total": len(msg_ids), "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": True,
        })
        try:
            chat_id, _ = parse_link(link)
            self._log(
                f"Copy via account — {len(msg_ids)} msgs from {chat_id} → {target}"
                + (f" (topic {thread_id})" if thread_id else "")
            )
            await self._resolve_peer(target)
            await self._copy_ids(chat_id, msg_ids, target, thread_id)
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    async def _safe_copy(self, to_chat, from_chat, msg_id: int,
                         thread_id=None, max_retries: int = 5) -> bool:
        """Server-side copy via copy_message() — no download/upload.
        Telegram re-creates the message on its own servers so video/audio
        always plays correctly, with no file-size limit.
        Retries automatically on FloodWait. Returns True on success."""
        from pyrogram.errors import FloodWait
        kw = {}
        if thread_id:
            kw["message_thread_id"] = thread_id
        for attempt in range(max_retries):
            try:
                await self.tg.client.copy_message(
                    chat_id=to_chat,
                    from_chat_id=from_chat,
                    message_id=msg_id,
                    **kw,
                )
                return True
            except FloodWait as e:
                wait = e.value + 1
                self._log(f"⏳ FloodWait {wait}s — รอ Telegram อนุญาตก่อน…")
                for remaining in range(wait, 0, -1):
                    if not self.state["running"]:
                        break
                    self.state["current_file"] = f"⏳ FloodWait — รอ {remaining}s…"
                    await asyncio.sleep(1)
            except Exception as e:
                self._log(f"⚠️ [{msg_id}] copy error: {e}")
                return False
        self._log(f"⚠️ [{msg_id}] หมด retry")
        return False

    async def _resolve_peer(self, chat_id):
        """Ensure the peer is in the session cache to avoid PEER_ID_INVALID."""
        try:
            await self.tg.client.get_chat(chat_id)
        except Exception:
            pass  # best-effort — error will surface later if peer truly unreachable

    async def _copy_ids(self, from_chat, msg_ids: List[int], to_chat, thread_id=None):
        """Server-side copy loop using copy_message()."""
        total = len(msg_ids)
        for i, msg_id in enumerate(msg_ids):
            if not self.state["running"]:
                self._log("หยุดแล้ว")
                break
            self.state["current"] = i + 1
            self.state["current_progress"] = 0
            self.state["current_file"] = f"#{i+1}/{total} — กำลัง copy…"
            try:
                msg = await self.tg.client.get_messages(from_chat, msg_id)
                if not msg or (not msg.media and not (msg.text and msg.text.strip())):
                    self.state["skipped"] += 1
                    continue

                ok = await self._safe_copy(to_chat, from_chat, msg_id, thread_id)
                if ok:
                    label = str(msg.media).split(".")[-1] if msg.media else "text"
                    self._log(f"✅ #{i+1}/{total} ({label})")
                    self.state["downloaded"] += 1
                    self.state["current_progress"] = 100
                    self.state["last_link"] = self._make_link(from_chat, msg_id)
                else:
                    self.state["skipped"] += 1

            except Exception as e:
                self._log(f"⚠️ #{i+1} error: {e}")
                self.state["skipped"] += 1

        ok_n = self.state["downloaded"]
        sk_n = self.state["skipped"]
        self._log(f"🏁 เสร็จแล้ว — ✅ {ok_n} | ข้าม {sk_n}")

    async def clone_topic_user(self, link: str, to_chat_id: str, max_gap: int = 30):
        """Clone entire topic using server-side copy_message() — no download needed."""
        target, thread_id = parse_target_chat(to_chat_id)

        self.state.update({
            "running": True, "total": 0, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": True,
        })
        try:
            chat_id, base_id = parse_link(link)
            self._log(
                f"Clone via account — {chat_id} msg {base_id} → {target}"
                + (f" (topic {thread_id})" if thread_id else "")
            )
            await self._resolve_peer(target)
            self._log(f"สแกน forward (หยุดเมื่อว่าง {max_gap} อัน)…")

            msg_id = base_id
            consecutive_empty = 0

            while self.state["running"]:
                batch_ids = list(range(msg_id, msg_id + 50))
                try:
                    messages = await self.tg.client.get_messages(chat_id, batch_ids)
                except Exception as e:
                    self._log(f"Fetch error at {msg_id}: {e}")
                    break

                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    if not self.state["running"]:
                        self._log("Cancelled.")
                        return

                    has_content = bool(msg and (msg.media or (msg.text and msg.text.strip())))

                    if not has_content:
                        consecutive_empty += 1
                        if consecutive_empty >= max_gap:
                            self._log(f"ไม่พบข้อความ {max_gap} อันติดกัน — สิ้นสุด Topic")
                            self.state["running"] = False
                            break
                        continue

                    consecutive_empty = 0
                    self.state["total"] = max(self.state["total"], msg.id - base_id + 1)
                    self.state["current"] = msg.id - base_id + 1
                    self.state["current_file"] = f"msg {msg.id}"

                    self.state["current_progress"] = 0
                    self.state["current_file"] = f"[{msg.id}] กำลัง copy…"
                    ok = await self._safe_copy(target, chat_id, msg.id, thread_id)
                    if ok:
                        label = str(msg.media).split(".")[-1] if msg.media else "text"
                        self._log(f"✅ [{msg.id}] ({label})")
                        self.state["downloaded"] += 1
                        self.state["current_progress"] = 100
                        self.state["last_link"] = self._make_link(chat_id, msg.id)
                    else:
                        self.state["skipped"] += 1

                if not self.state["running"]:
                    break
                msg_id += 50

            self._log(
                f"Clone done — {self.state['downloaded']} ส่งสำเร็จ, "
                f"{self.state['skipped']} skipped."
            )
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    # ── Batch download: sequential range ──────────────────────────────────────

    async def run(self, link: str, count: int, start_offset: int = 0,
                  forwarder: Optional[BotForwarder] = None):
        self.state.update({
            "running": True, "total": count, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": forwarder is not None,
        })
        try:
            chat_id, base_id = parse_link(link)
            start_id = base_id + start_offset
            self._log(f"Batch started — chat: {chat_id}, IDs: {start_id} to {start_id + count - 1}")
            await self._download_ids(chat_id, list(range(start_id, start_id + count)), forwarder)
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    # ── Batch download: specific message IDs ──────────────────────────────────

    async def run_specific(self, link: str, msg_ids: List[int],
                           forwarder: Optional[BotForwarder] = None):
        count = len(msg_ids)
        self.state.update({
            "running": True, "total": count, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": forwarder is not None,
        })
        try:
            chat_id, _ = parse_link(link)
            self._log(f"Downloading {count} selected item(s) from chat {chat_id}")
            await self._download_ids(chat_id, msg_ids, forwarder)
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    # ── Shared download loop ───────────────────────────────────────────────────

    async def _download_ids(self, chat_id, msg_ids: List[int],
                            forwarder: Optional[BotForwarder] = None):
        for i, msg_id in enumerate(msg_ids):
            if not self.state["running"]:
                self._log("Cancelled.")
                break

            self.state["current"] = i + 1
            self.state["current_progress"] = 0

            try:
                msg = await self.tg.client.get_messages(chat_id, msg_id)
                if not msg or not msg.media:
                    self._log(f"[{msg_id}] No media — skipped")
                    self.state["skipped"] += 1
                    continue

                media_label = str(msg.media).split(".")[-1]
                action = "forwarding" if forwarder else "downloading"
                self._log(f"[{msg_id}] {media_label} — {action}…")
                self.state["current_file"] = f"msg {msg_id}"

                def make_progress(mid):
                    def _cb(cur, tot):
                        if tot:
                            self.state["current_progress"] = int(cur * 100 / tot)
                            self.state["current_file"] = f"msg {mid}  {self.state['current_progress']}%"
                    return _cb

                path = await self.tg.client.download_media(
                    msg,
                    file_name=str(DOWNLOADS_DIR) + "/",
                    progress=make_progress(msg_id),
                )

                if path:
                    filename = os.path.basename(path)
                    if forwarder:
                        self.state["current_file"] = f"msg {msg_id} — sending to bot…"
                        caption = getattr(msg, "caption", "") or ""
                        ok, err = forwarder.send_file(Path(path), caption=caption)
                        if ok:
                            Path(path).unlink(missing_ok=True)
                            self._log(f"[{msg_id}] forwarded & deleted: {filename}")
                            self.state["downloaded"] += 1
                            self.state["last_link"] = self._make_link(chat_id, msg_id)
                        else:
                            self._log(f"[{msg_id}] send failed ({err}) — kept: {filename}")
                            self.state["skipped"] += 1
                            self.state["new_files"].append(filename)
                    else:
                        self._log(f"[{msg_id}] saved: {filename}")
                        self.state["downloaded"] += 1
                        self.state["new_files"].append(filename)
                        self.state["last_link"] = self._make_link(chat_id, msg_id)
                else:
                    self._log(f"[{msg_id}] no output path — skipped")
                    self.state["skipped"] += 1

            except Exception as e:
                self._log(f"[{msg_id}] error: {e}")
                self.state["skipped"] += 1

        self._log(
            f"Done — {self.state['downloaded']} {'forwarded' if forwarder else 'downloaded'}, "
            f"{self.state['skipped']} skipped."
        )

    # ── Clone entire topic ────────────────────────────────────────────────────

    async def clone_topic(self, link: str, forwarder: BotForwarder, max_gap: int = 30):
        """Scan all messages forward from the given link and forward them via bot.

        Messages belonging to the same media album (media_group_id) are buffered
        and sent together as a single sendMediaGroup call.
        """
        self.state.update({
            "running": True, "total": 0, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [], "last_link": "",
            "forward_mode": True,
        })

        # Album buffer: list of {path, caption, msg_id}
        album_buffer: list = []
        current_album_id: Optional[str] = None

        async def flush_album():
            """Send buffered album items as a media group, then delete files."""
            nonlocal album_buffer, current_album_id
            if not album_buffer:
                return
            ids_str = ",".join(str(it["msg_id"]) for it in album_buffer)
            self._log(f"[album {ids_str}] ส่งเป็น album ({len(album_buffer)} ไฟล์)…")
            self.state["current_file"] = f"album [{ids_str}] — sending…"

            # sendMediaGroup supports max 10 items — chunk if needed
            chunks = [album_buffer[i:i+10] for i in range(0, len(album_buffer), 10)]
            all_ok = True
            for chunk in chunks:
                ok, err = forwarder.send_album(chunk)
                if ok:
                    for it in chunk:
                        Path(it["path"]).unlink(missing_ok=True)
                    self.state["downloaded"] += len(chunk)
                    self._log(f"  ✓ {len(chunk)} ไฟล์ส่งสำเร็จ & ลบแล้ว")
                else:
                    self._log(f"  ✗ album send failed ({err}) — ลองส่งทีละไฟล์…")
                    # Fallback: send individually
                    for it in chunk:
                        p = Path(it["path"])
                        fok, ferr = forwarder.send_file(p, caption=it.get("caption", ""))
                        if fok:
                            p.unlink(missing_ok=True)
                            self.state["downloaded"] += 1
                        else:
                            self._log(f"  ✗ [{it['msg_id']}] fallback failed ({ferr})")
                            self.state["skipped"] += 1
                            all_ok = False

            album_buffer.clear()
            current_album_id = None

        try:
            chat_id, base_id = parse_link(link)
            self._log(f"Clone started — chat: {chat_id}, from msg {base_id}")
            self._log(f"Scanning forward (หยุดเมื่อไม่เจอข้อความ {max_gap} อันติดกัน)…")

            msg_id = base_id
            consecutive_empty = 0

            while self.state["running"]:
                batch_ids = list(range(msg_id, msg_id + 50))
                try:
                    messages = await self.tg.client.get_messages(chat_id, batch_ids)
                except Exception as e:
                    self._log(f"Fetch error at {msg_id}: {e}")
                    break

                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    if not self.state["running"]:
                        self._log("Cancelled.")
                        await flush_album()
                        return

                    has_media = bool(msg and msg.media)
                    has_text  = bool(msg and msg.text and msg.text.strip())

                    if not has_media and not has_text:
                        # Empty message — flush pending album before counting gaps
                        await flush_album()
                        consecutive_empty += 1
                        if consecutive_empty >= max_gap:
                            self._log(f"ไม่พบข้อความ {max_gap} อันติดกัน — สิ้นสุด Topic")
                            self.state["running"] = False
                            break
                        continue

                    consecutive_empty = 0
                    self.state["total"] = max(self.state["total"], msg.id - base_id + 1)
                    self.state["current"] = msg.id - base_id + 1

                    if has_media:
                        group_id = getattr(msg, "media_group_id", None)

                        # If message belongs to a different album, flush the old one first
                        if group_id != current_album_id:
                            await flush_album()
                            current_album_id = group_id

                        media_label = str(msg.media).split(".")[-1]
                        self._log(f"[{msg.id}] {media_label} — downloading…")
                        self.state["current_file"] = f"msg {msg.id}"

                        def make_progress(mid):
                            def _cb(cur, tot):
                                if tot:
                                    self.state["current_progress"] = int(cur * 100 / tot)
                                    self.state["current_file"] = f"msg {mid}  {self.state['current_progress']}%"
                            return _cb

                        try:
                            path = await self.tg.client.download_media(
                                msg,
                                file_name=str(DOWNLOADS_DIR) + "/",
                                progress=make_progress(msg.id),
                            )
                            if path:
                                caption = getattr(msg, "caption", "") or ""
                                if group_id:
                                    # Buffer for album send
                                    album_buffer.append({
                                        "path": path,
                                        "caption": caption,
                                        "msg_id": msg.id,
                                    })
                                    self._log(f"[{msg.id}] ✓ downloaded — รอส่งพร้อม album")
                                else:
                                    # Single file — send immediately
                                    self.state["current_file"] = f"msg {msg.id} — sending…"
                                    ok, err = forwarder.send_file(Path(path), caption=caption)
                                    if ok:
                                        Path(path).unlink(missing_ok=True)
                                        self._log(f"[{msg.id}] ✓ forwarded & deleted")
                                        self.state["downloaded"] += 1
                                        self.state["last_link"] = self._make_link(chat_id, msg.id)
                                    else:
                                        self._log(f"[{msg.id}] ✗ send failed ({err}) — kept on server")
                                        self.state["skipped"] += 1
                                        self.state["new_files"].append(os.path.basename(path))
                            else:
                                self._log(f"[{msg.id}] ไม่สามารถโหลดไฟล์ได้ — skipped")
                                self.state["skipped"] += 1
                        except Exception as e:
                            self._log(f"[{msg.id}] error: {e}")
                            self.state["skipped"] += 1

                    elif has_text:
                        # Text message — flush any pending album first
                        await flush_album()
                        self._log(f"[{msg.id}] text — sending…")
                        ok, err = forwarder.send_text(msg.text)
                        if ok:
                            self._log(f"[{msg.id}] ✓ text sent")
                            self.state["downloaded"] += 1
                            self.state["last_link"] = self._make_link(chat_id, msg.id)
                        else:
                            self._log(f"[{msg.id}] ✗ text failed ({err})")
                            self.state["skipped"] += 1

                if not self.state["running"]:
                    break

                msg_id += 50

            # Flush any remaining album at end
            await flush_album()

            self._log(
                f"Clone done — {self.state['downloaded']} forwarded, "
                f"{self.state['skipped']} skipped."
            )
        except Exception as e:
            self._log(f"Fatal error: {e}")
        finally:
            self._finish()

    def _finish(self):
        self.state["running"] = False
        self.state["current_file"] = ""
        self.state["current_progress"] = 0
