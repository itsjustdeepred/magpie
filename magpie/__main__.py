import logging
import os

from . import __version__, i18n
from .bot import build_app
from .config import Config
from .lidarr import Lidarr

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("magpie")


def main() -> None:
    cfg = Config.from_env()
    lang = i18n.set_language(cfg.language)
    log.info("Magpie %s, bot language: %s", __version__, lang)

    lidarr = Lidarr(
        cfg.lidarr_url, cfg.lidarr_api_key,
        cfg.root_folder, cfg.quality_profile, cfg.metadata_profile,
    )
    app = build_app(cfg, lidarr)
    log.info("Bot started. Allowed chats: %s", sorted(cfg.allowed_chats) or "none")
    app.run_polling(allowed_updates=["message", "channel_post", "callback_query"])


if __name__ == "__main__":
    main()
