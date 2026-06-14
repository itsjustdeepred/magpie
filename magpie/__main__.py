import asyncio
import logging

from . import i18n
from .bot import build_app
from .config import Config
from .lidarr import Lidarr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("magpie")


async def _check_lidarr(cfg: Config) -> None:
    probe = Lidarr(cfg.lidarr_url, cfg.lidarr_api_key)
    try:
        info = await probe.status()
        log.info("Connected to Lidarr %s at %s", info.get("version"), cfg.lidarr_url)
    finally:
        await probe.close()


def main() -> None:
    cfg = Config.from_env()
    lang = i18n.set_language(cfg.language)
    log.info("Bot language: %s", lang)

    try:
        asyncio.run(_check_lidarr(cfg))
    except Exception as e:
        log.warning("Lidarr unreachable (%s): the bot starts anyway, "
                    "but adds will fail until it responds.", e)

    lidarr = Lidarr(
        cfg.lidarr_url, cfg.lidarr_api_key,
        cfg.root_folder, cfg.quality_profile, cfg.metadata_profile,
    )
    app = build_app(cfg, lidarr)
    log.info("Bot started. Allowed chats: %s", sorted(cfg.allowed_chats) or "none")
    app.run_polling(allowed_updates=["message", "channel_post", "callback_query"])


if __name__ == "__main__":
    main()
