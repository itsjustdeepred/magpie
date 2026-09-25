import asyncio
import logging
import time

from telegram import Bot, ReplyParameters
from telegram.error import TelegramError

from .config import WATCHES_FILE, load_json, save_json
from .i18n import t
from .lidarr import Lidarr, LidarrError, is_complete

log = logging.getLogger(__name__)


class ImportWatcher:
    """Polls Lidarr for albums added from Telegram and posts in the originating
    chat once they have been imported. Watches are persisted in DATA_DIR, so
    they survive a restart."""

    def __init__(self, lidarr: Lidarr, bot: Bot, interval: int, max_days: int):
        self._lidarr = lidarr
        self._bot = bot
        self._interval = interval
        self._max_days = max_days
        data = load_json(WATCHES_FILE, {})
        self._watches: dict[str, dict] = data if isinstance(data, dict) else {}

    def __len__(self) -> int:
        return len(self._watches)

    def add(self, album_id: int, chat_id: int, title: str, reply_to: int | None) -> None:
        self._watches[f"{album_id}:{chat_id}"] = {
            "album_id": album_id, "chat_id": chat_id, "title": title,
            "reply_to": reply_to, "since": time.time(),
        }
        self._save()

    def _save(self) -> None:
        try:
            save_json(WATCHES_FILE, self._watches)
        except OSError as e:
            log.warning("Could not save %s: %s", WATCHES_FILE, e)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.check()
            except Exception:
                log.exception("Import check failed")

    async def check(self) -> None:
        if not self._watches:
            return
        ids = sorted({w["album_id"] for w in self._watches.values()})
        try:
            albums = {a["id"]: a for a in await self._lidarr.albums(ids)}
        except LidarrError as e:
            log.warning("Import check: %s", e)
            return

        now = time.time()
        done = []
        for key, w in self._watches.items():
            album = albums.get(w["album_id"])
            if album is None:
                done.append(key)  # removed from Lidarr in the meantime
            elif is_complete(album):
                await self._send(w, t("imported", title=w["title"]))
                done.append(key)
            elif now - w["since"] > self._max_days * 86400:
                stats = album.get("statistics") or {}
                have = stats.get("trackFileCount", 0)
                total = stats.get("trackCount") or stats.get("totalTrackCount") or 0
                if have:
                    text = t("import_partial", title=w["title"], have=have,
                             total=total, days=self._max_days)
                else:
                    text = t("import_timeout", title=w["title"], days=self._max_days)
                await self._send(w, text)
                done.append(key)
        if done:
            for key in done:
                self._watches.pop(key, None)
            self._save()

    async def _send(self, watch: dict, text: str) -> None:
        reply = (ReplyParameters(message_id=watch["reply_to"], allow_sending_without_reply=True)
                 if watch.get("reply_to") else None)
        try:
            await self._bot.send_message(watch["chat_id"], text, reply_parameters=reply)
        except TelegramError as e:
            log.warning("Could not notify chat %s: %s", watch["chat_id"], e)
