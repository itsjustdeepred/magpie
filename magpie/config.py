import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
ALLOWED_CHATS_FILE = DATA_DIR / "allowed_chats.json"
WATCHES_FILE = DATA_DIR / "watches.json"

GROUP_TRIGGERS = ("smart", "all")


def _int_env(name: str, default: int | None = None, minimum: int | None = None) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from None
    if minimum is not None and value < minimum:
        raise SystemExit(f"{name} must be >= {minimum}, got {value}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise SystemExit(f"{name} must be true/false, got {raw!r}")


def parse_chat_ids(raw: str) -> set[int]:
    ids = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            raise SystemExit(f"ALLOWED_CHAT_IDS contains a non-numeric id: {chunk!r}") from None
    return ids


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
    group_trigger: str = "smart"
    notify: bool = True
    notify_days: int = 7
    notify_interval: int = 120
    allowed_chats: set[int] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        url = os.environ.get("LIDARR_URL", "http://localhost:8686").strip().rstrip("/")
        api_key = os.environ.get("LIDARR_API_KEY", "").strip()
        if not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is missing (see .env.example)")
        if not api_key:
            raise SystemExit("LIDARR_API_KEY is missing (see .env.example)")
        if not url.startswith(("http://", "https://")):
            raise SystemExit(f"LIDARR_URL must start with http:// or https://, got {url!r}")

        trigger = (os.environ.get("GROUP_TRIGGER") or "smart").strip().lower()
        if trigger not in GROUP_TRIGGERS:
            raise SystemExit(f"GROUP_TRIGGER must be one of {GROUP_TRIGGERS}, got {trigger!r}")

        cfg = cls(
            telegram_token=token,
            lidarr_url=url,
            lidarr_api_key=api_key,
            admin_user_id=_int_env("ADMIN_USER_ID"),
            root_folder=os.environ.get("LIDARR_ROOT_FOLDER") or None,
            quality_profile=os.environ.get("LIDARR_QUALITY_PROFILE") or None,
            metadata_profile=os.environ.get("LIDARR_METADATA_PROFILE") or None,
            language=os.environ.get("BOT_LANG", "en"),
            group_trigger=trigger,
            notify=_bool_env("NOTIFY_ON_IMPORT", True),
            notify_days=_int_env("NOTIFY_MAX_DAYS", 7, minimum=1),
            notify_interval=_int_env("NOTIFY_INTERVAL", 120, minimum=30),
        )
        cfg.allowed_chats = parse_chat_ids(os.environ.get("ALLOWED_CHAT_IDS", ""))
        cfg.allowed_chats |= _load_saved_chats()
        return cfg

    def is_admin(self, user_id: int | None) -> bool:
        return self.admin_user_id is not None and user_id == self.admin_user_id

    def is_allowed(self, chat_id: int, user_id: int | None = None) -> bool:
        return chat_id in self.allowed_chats or self.is_admin(user_id)

    def allow_chat(self, chat_id: int) -> None:
        self.allowed_chats.add(chat_id)
        _save_chats(self.allowed_chats)

    def deny_chat(self, chat_id: int) -> None:
        self.allowed_chats.discard(chat_id)
        _save_chats(self.allowed_chats)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable %s: %s", path, e)
        return default


def save_json(path: Path, data) -> None:
    """Write atomically, so a crash mid-write never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _load_saved_chats() -> set[int]:
    data = load_json(ALLOWED_CHATS_FILE, [])
    if not isinstance(data, list):
        log.warning("Ignoring %s: expected a JSON list", ALLOWED_CHATS_FILE)
        return set()
    return {c for c in data if isinstance(c, int)}


def _save_chats(chats: set[int]) -> None:
    save_json(ALLOWED_CHATS_FILE, sorted(chats))
