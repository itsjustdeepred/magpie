
import logging
import re
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import musicbrainz, resolver
from .config import Config
from .i18n import t
from .lidarr import Lidarr, LidarrError

log = logging.getLogger(__name__)

PENDING: dict[str, list[musicbrainz.Candidate]] = {}
MAX_PENDING = 200


def build_app(cfg: Config, lidarr: Lidarr) -> Application:
    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["lidarr"] = lidarr

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("chats", cmd_chats))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED, on_message))
    return app


def _ids(update: Update) -> tuple[int, int | None]:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    return chat_id, user_id


def _is_admin(cfg: Config, user_id: int | None) -> bool:
    return cfg.admin_user_id is None or user_id == cfg.admin_user_id


def _md_escape(s: str) -> str:
    return re.sub(r"([_*`\[])", r"\\\1", s)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _format_tracklist(tracks: list[str], target: str, limit: int = 14) -> str:
    nt = _norm(target)
    hit = None
    if nt:
        hit = next((i for i, tr in enumerate(tracks) if _norm(tr) == nt), None)
        if hit is None:
            hit = next((i for i, tr in enumerate(tracks) if nt in _norm(tr)), None)

    shown = list(range(min(len(tracks), limit)))
    if hit is not None and hit not in shown:
        shown = shown[:limit - 1] + [hit]

    lines = []
    for i in shown:
        title = _md_escape(tracks[i])
        if i == hit:
            lines.append(f"▶️ *{i + 1}. {title}*")
        else:
            lines.append(f"{i + 1}. {title}")
    if len(tracks) > len(shown):
        lines.append(f"… +{len(tracks) - len(shown)}")
    return "\n".join(lines)


def _disco_main(disco: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    main = [d for d in disco if d[2] in ("Album", "EP")]
    return main if len(main) >= 3 else main + [d for d in disco if d[2] == "Single"]


def _artist_candidates(name: str, mbid: str,
                       disco: list[tuple[str, str, str, str]]) -> list[musicbrainz.Candidate]:
    main = _disco_main(disco)
    albums = [d for d in main if d[2] == "Album"] or main
    return [
        musicbrainz.Candidate(
            artist=name, artist_mbid=mbid, track=name,
            album=f"{title} ({year})" if year else title,
            rg_mbid=rg_mbid, rg_type=kind, score=0,
        )
        for title, year, kind, rg_mbid in albums[:3]
    ]


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(t("start"))


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, _ = _ids(update)
    await update.effective_message.reply_text(t("chat_id", chat_id=chat_id),
                                              parse_mode="Markdown")


async def cmd_allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    chat_id, user_id = _ids(update)
    if not _is_admin(cfg, user_id):
        return
    target = int(ctx.args[0]) if ctx.args else chat_id
    cfg.allow_chat(target)
    await update.effective_message.reply_text(t("chat_allowed", chat_id=target))


async def cmd_deny(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    chat_id, user_id = _ids(update)
    if not _is_admin(cfg, user_id):
        return
    target = int(ctx.args[0]) if ctx.args else chat_id
    cfg.deny_chat(target)
    await update.effective_message.reply_text(t("chat_denied", chat_id=target))


async def cmd_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    _, user_id = _ids(update)
    if not _is_admin(cfg, user_id):
        return
    chats = "\n".join(str(c) for c in sorted(cfg.allowed_chats)) or t("chat_list_empty")
    await update.effective_message.reply_text(t("chat_list", chats=chats))


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    msg = update.effective_message
    chat_id, user_id = _ids(update)
    if not cfg.is_allowed(chat_id, user_id):
        if update.effective_chat.type == "private":
            await msg.reply_text(t("not_allowed", chat_id=chat_id),
                                 parse_mode="Markdown")
        return

    text = (msg.text or "").strip()
    if not text:
        return

    note = await msg.reply_text(t("searching"))
    try:
        query = await resolver.resolve(text)
        log.info("Query from %s (%s): %r", chat_id, query.source, query)

        artist_hit = None
        track_missing = False
        disco = []
        candidates = []
        if query.source == "text" and not query.artist:
            artist_hit = await musicbrainz.find_artist(query.raw)
        if artist_hit:
            disco = await musicbrainz.fetch_discography(artist_hit[1])
            candidates = _artist_candidates(*artist_hit, disco)
        if not candidates:
            artist_hit = None
            disco = []
            candidates = await musicbrainz.search(query)
        if not candidates and query.artist:
            artist_hit = await musicbrainz.find_artist(query.artist)
            if artist_hit:
                disco = await musicbrainz.fetch_discography(artist_hit[1])
                candidates = _artist_candidates(*artist_hit, disco)
                track_missing = bool(candidates)
    except Exception:
        log.exception("Failed to resolve %r", text)
        await note.edit_text(t("cant_parse"))
        return

    log.info("Candidates for %r: %s", query.raw, [c.label() for c in candidates])
    if not candidates:
        if query.artist and await musicbrainz.find_artist(query.artist):
            await note.edit_text(t("no_results_artist_known", artist=query.artist))
        else:
            await note.edit_text(t("no_results", query=query.raw))
        return

    token = uuid.uuid4().hex[:10]
    if len(PENDING) > MAX_PENDING:
        PENDING.clear()
    PENDING[token] = candidates

    keyboard = [
        [InlineKeyboardButton(c.label()[:60], callback_data=f"a:{token}:{i}")]
        for i, c in enumerate(candidates)
    ]
    keyboard.append([InlineKeyboardButton(t("all_button"), callback_data=f"l:{token}")])
    keyboard.append([InlineKeyboardButton(t("cancel"), callback_data=f"x:{token}")])
    if artist_hit and track_missing:
        caption = t("track_missing_artist_found", artist=_md_escape(artist_hit[0]))
    elif artist_hit:
        caption = t("artist_mode", artist=_md_escape(artist_hit[0]))
    else:
        caption = t("recognized", source=query.source, track=_md_escape(candidates[0].track))
    markup = InlineKeyboardMarkup(keyboard)

    if not artist_hit:
        tracks = await musicbrainz.fetch_tracklist(candidates[0].rg_mbid)
        if tracks:
            listing = _format_tracklist(tracks, candidates[0].track)
            caption += ("\n\n" + t("tracklist", album=_md_escape(candidates[0].album))
                        + "\n" + listing)

    if not disco:
        disco = await musicbrainz.fetch_discography(candidates[0].artist_mbid)
    shown = _disco_main(disco)
    if shown:
        lines = [
            f"• {_md_escape(title)} ({year})" + (f" [{kind}]" if kind != "Album" else "")
            for title, year, kind, _ in shown[:8]
        ]
        if len(shown) > 8:
            lines.append(f"… +{len(shown) - 8}")
        caption += ("\n\n" + t("other_albums", artist=_md_escape(candidates[0].artist))
                    + "\n" + "\n".join(lines))

    if len(caption) > 1024:
        caption = caption[:1000].rsplit("\n", 1)[0] + "\n…"

    cover = await musicbrainz.fetch_cover(candidates[0].rg_mbid)
    if cover:
        await note.delete()
        await msg.reply_photo(photo=cover, caption=caption,
                              parse_mode="Markdown", reply_markup=markup)
    else:
        await note.edit_text(caption, parse_mode="Markdown", reply_markup=markup)


async def _update_prompt(q, text: str) -> None:
    if q.message and q.message.photo:
        await q.edit_message_caption(caption=text)
    else:
        await q.edit_message_text(text)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    lidarr: Lidarr = ctx.bot_data["lidarr"]
    q = update.callback_query
    chat_id, user_id = _ids(update)
    if not cfg.is_allowed(chat_id, user_id):
        await q.answer(t("not_authorized"), show_alert=True)
        return

    parts = q.data.split(":")
    await q.answer()
    if parts[0] == "x":
        PENDING.pop(parts[1], None)
        await _update_prompt(q, t("cancelled"))
        return

    candidates = PENDING.pop(parts[1], None)
    if candidates is None:
        await _update_prompt(q, t("expired"))
        return

    if parts[0] == "l":
        cand = candidates[0]
        await _update_prompt(q, t("adding_artist", artist=cand.artist))
        try:
            status, name = await lidarr.add_artist_and_search(cand.artist_mbid)
        except LidarrError as e:
            log.error("Lidarr: %s", e)
            await _update_prompt(q, t("lidarr_error", error=e))
            return
        except Exception:
            log.exception("Unexpected error while adding artist %s", cand.artist_mbid)
            await _update_prompt(q, t("unexpected_error"))
            return
        await _update_prompt(q, t(status, artist=name))
        return

    cand = candidates[int(parts[2])]
    await _update_prompt(q, t("adding", label=cand.label()))
    try:
        status, title = await lidarr.add_and_search(cand.rg_mbid)
    except LidarrError as e:
        log.error("Lidarr: %s", e)
        await _update_prompt(q, t("lidarr_error", error=e))
        return
    except Exception:
        log.exception("Unexpected error while adding %s", cand.rg_mbid)
        await _update_prompt(q, t("unexpected_error"))
        return
    await _update_prompt(
        q,
        t("album_exists", title=title) if status == "exists" else t("album_added", title=title),
    )
