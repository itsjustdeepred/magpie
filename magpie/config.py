import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
ALLOWED_CHATS_FILE = DATA_DIR / "allowed_chats.json"


@dataclass
class Config:
    telegram_token: str
    lidarr_url: str
    lidarr_api_key: str
    admin_user_id: int | None
    root_folder: str | None
    quality_profile: str | None
    metadata_profile: str | None
    language: str = "en"
    allowed_chats: set[int] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        url = os.environ.get("LIDARR_URL", "http://localhost:8686").rstrip("/")
        api_key = os.environ.get("LIDARR_API_KEY", "")
        if not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is missing (see .env.example)")
        if not api_key:
            raise SystemExit("LIDARR_API_KEY is missing (see .env.example)")

        admin = os.environ.get("ADMIN_USER_ID")
        cfg = cls(
            telegram_token=token,
            lidarr_url=url,
            lidarr_api_key=api_key,
            admin_user_id=int(admin) if admin else None,
            root_folder=os.environ.get("LIDARR_ROOT_FOLDER") or None,
            quality_profile=os.environ.get("LIDARR_QUALITY_PROFILE") or None,
            metadata_profile=os.environ.get("LIDARR_METADATA_PROFILE") or None,
            language=os.environ.get("BOT_LANG", "en"),
        )
        env_chats = os.environ.get("ALLOWED_CHAT_IDS", "")
        cfg.allowed_chats = {int(c) for c in env_chats.split(",") if c.strip()}
        cfg.allowed_chats |= _load_saved_chats()
        return cfg

    def is_allowed(self, chat_id: int, user_id: int | None = None) -> bool:
        if chat_id in self.allowed_chats:
            return True
        return self.admin_user_id is not None and user_id == self.admin_user_id

    def allow_chat(self, chat_id: int) -> None:
        self.allowed_chats.add(chat_id)
        _save_chats(self.allowed_chats)

    def deny_chat(self, chat_id: int) -> None:
        self.allowed_chats.discard(chat_id)
        _save_chats(self.allowed_chats)


def _load_saved_chats() -> set[int]:
    try:
        return set(json.loads(ALLOWED_CHATS_FILE.read_text()))
    except (FileNotFoundError, ValueError):
        return set()


def _save_chats(chats: set[int]) -> None:
    ALLOWED_CHATS_FILE.write_text(json.dumps(sorted(chats)))
