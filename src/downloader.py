import os
import re
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


def parse_link(link: str):
    link = link.strip()
    private = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
    if private:
        return int(f"-100{private.group(1)}"), int(private.group(2))
    public = re.match(r"https://t\.me/([^/?]+)/(\d+)", link)
    if public:
        return public.group(1), int(public.group(2))
    raise ValueError(f"Unrecognised link format: {link}")


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
        self.state["log"].append(entry)
        print(entry)

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

    # ── Batch download: sequential range ──────────────────────────────────────

    async def run(self, link: str, count: int, start_offset: int = 0,
                  forwarder: Optional[BotForwarder] = None):
        self.state.update({
            "running": True, "total": count, "current": 0,
            "downloaded": 0, "skipped": 0,
            "current_file": "", "current_progress": 0,
            "log": [], "new_files": [],
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
            "log": [], "new_files": [],
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
                        else:
                            self._log(f"[{msg_id}] send failed ({err}) — kept: {filename}")
                            self.state["skipped"] += 1
                            self.state["new_files"].append(filename)
                    else:
                        self._log(f"[{msg_id}] saved: {filename}")
                        self.state["downloaded"] += 1
                        self.state["new_files"].append(filename)
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

    def _finish(self):
        self.state["running"] = False
        self.state["current_file"] = ""
        self.state["current_progress"] = 0
