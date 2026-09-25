import asyncio
import html
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
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
from .notify import ImportWatcher

log = logging.getLogger(__name__)

MAX_PENDING = 200
PENDING_TTL = 3600
HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/magpie.heartbeat"))
HEARTBEAT_EVERY = 30

def _e(s: str) -> str:
    # Quotes need no escaping outside attributes; keeps "It's" readable.
    return html.escape(s, quote=False)


@dataclass
class Pending:
    candidates: list[musicbrainz.Candidate]
    owner: int | None  # user who asked; None (channel posts) means anyone in the chat
    created: float = field(default_factory=time.monotonic)


PENDING: OrderedDict[str, Pending] = OrderedDict()


def _store_pending(p: Pending) -> str:
    """Store a prompt, evicting the oldest ones instead of wiping everything."""
    now = time.monotonic()
    while PENDING and (len(PENDING) >= MAX_PENDING
                       or now - next(iter(PENDING.values())).created > PENDING_TTL):
        PENDING.popitem(last=False)
    token = uuid.uuid4().hex[:10]
    PENDING[token] = p
    return token


def _get_pending(token: str) -> Pending | None:
    p = PENDING.get(token)
    if p is not None and time.monotonic() - p.created > PENDING_TTL:
        del PENDING[token]
        return None
    return p


def build_app(cfg: Config, lidarr: Lidarr) -> Application:
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        # Adding an album can wait up to 90s on Lidarr: without this every
        # other chat would be stuck behind it.
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_stop(_post_stop)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["cfg"] = cfg
    app.bot_data["lidarr"] = lidarr

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("chats", cmd_chats))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED, on_message))
    app.add_error_handler(on_error)
    return app


async def _post_init(app: Application) -> None:
    cfg: Config = app.bot_data["cfg"]
    lidarr: Lidarr = app.bot_data["lidarr"]
    try:
        info = await lidarr.status()
        log.info("Connected to Lidarr %s at %s", info.get("version"), cfg.lidarr_url)
        d = await lidarr.validate()
        log.info("Lidarr defaults: root folder %s, quality profile #%s, metadata profile #%s",
                 d["root"], d["quality"], d["metadata"])
    except LidarrError as e:
        log.warning("Lidarr check failed (%s): the bot starts anyway, "
                    "but adds will fail until this is fixed.", e)

    try:
        await app.bot.set_my_commands([
            BotCommand(name, t(f"cmd_{name}")) for name in ("add", "queue", "status", "id")
        ])
    except TelegramError as e:
        log.warning("Could not register the command menu: %s", e)

    tasks = [asyncio.create_task(_heartbeat())]
    if cfg.notify:
        watcher = ImportWatcher(lidarr, app.bot, cfg.notify_interval, cfg.notify_days)
        app.bot_data["watcher"] = watcher
        tasks.append(asyncio.create_task(watcher.run()))
        log.info("Import notifications on (%d pending)", len(watcher))
    app.bot_data["tasks"] = tasks


async def _post_stop(app: Application) -> None:
    for task in app.bot_data.get("tasks", []):
        task.cancel()


async def _post_shutdown(app: Application) -> None:
    await app.bot_data["lidarr"].close()
    await musicbrainz.close()


async def _heartbeat() -> None:
    """Touch a file regularly so the Docker HEALTHCHECK can tell the loop is alive."""
    while True:
        try:
            HEARTBEAT_FILE.touch()
        except OSError as e:
            log.debug("Heartbeat: %s", e)
        await asyncio.sleep(HEARTBEAT_EVERY)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error while processing %s", update, exc_info=ctx.error)


def _ids(update: Update) -> tuple[int, int | None]:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    return chat_id, user_id


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
        title = _e(tracks[i])
        if i == hit:
            lines.append(f"▶️ <b>{i + 1}. {title}</b>")
        else:
            lines.append(f"{i + 1}. {title}")
    if len(tracks) > len(shown):
        lines.append(f"… +{len(tracks) - len(shown)}")
    return "\n".join(lines)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _truncate(text: str, limit: int) -> str:
    """Cut at a line boundary: tags never span lines, so the HTML stays valid."""
    if len(text) <= limit:
        return text
    return text[:limit - 24].rsplit("\n", 1)[0] + "\n…"


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


def _chat_target(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int | None:
    if not ctx.args:
        return chat_id
    try:
        return int(ctx.args[0])
    except ValueError:
        return None


async def _safe_edit(message: Message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramError as e:
        log.warning("Could not edit message: %s", e)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(t("start"))


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, _ = _ids(update)
    await update.effective_message.reply_text(t("chat_id", chat_id=chat_id),
                                              parse_mode=ParseMode.HTML)


async def _cmd_chat_change(update: Update, ctx: ContextTypes.DEFAULT_TYPE, allow: bool) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    chat_id, user_id = _ids(update)
    if not cfg.is_admin(user_id):
        return
    target = _chat_target(ctx, chat_id)
    msg = update.effective_message
    if target is None:
        await msg.reply_text(t("chat_usage", command="allow" if allow else "deny"))
    elif allow:
        cfg.allow_chat(target)
        await msg.reply_text(t("chat_allowed", chat_id=target))
    else:
        cfg.deny_chat(target)
        await msg.reply_text(t("chat_denied", chat_id=target))


async def cmd_allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _cmd_chat_change(update, ctx, allow=True)


async def cmd_deny(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _cmd_chat_change(update, ctx, allow=False)


async def cmd_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    _, user_id = _ids(update)
    if not cfg.is_admin(user_id):
        return
    chats = "\n".join(str(c) for c in sorted(cfg.allowed_chats)) or t("chat_list_empty")
    await update.effective_message.reply_text(t("chat_list", chats=chats))


async def _check_allowed(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    cfg: Config = ctx.bot_data["cfg"]
    chat_id, user_id = _ids(update)
    if cfg.is_allowed(chat_id, user_id):
        return True
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(t("not_allowed", chat_id=chat_id),
                                                  parse_mode=ParseMode.HTML)
    return False


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update, ctx):
        return
    text = " ".join(ctx.args or []).strip()
    if not text:
        await update.effective_message.reply_text(t("add_usage"))
        return
    await _handle_query(update, ctx, text)


async def cmd_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update, ctx):
        return
    lidarr: Lidarr = ctx.bot_data["lidarr"]
    msg = update.effective_message
    try:
        data = await lidarr.queue()
    except LidarrError as e:
        await msg.reply_text(t("lidarr_error", error=e))
        return
    records = data.get("records") or []
    if not records:
        await msg.reply_text(t("queue_empty"))
        return
    lines = [t("queue_header", count=data.get("totalRecords", len(records)))]
    lines += [_queue_line(r) for r in records]
    await msg.reply_text(_truncate("\n".join(lines), 4096))


def _queue_line(record: dict) -> str:
    artist = (record.get("artist") or {}).get("artistName")
    album = (record.get("album") or {}).get("title")
    name = f"{artist} – {album}" if artist and album else record.get("title", "?")
    size = record.get("size") or 0
    left = record.get("sizeleft") or 0
    pct = int(100 * (size - left) / size) if size else 0
    state = record.get("trackedDownloadState") or record.get("status") or ""
    line = f"• {name[:80]} · {pct}% · {state}"
    if record.get("timeleft"):
        line += f" · {record['timeleft']}"
    return line


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_allowed(update, ctx):
        return
    lidarr: Lidarr = ctx.bot_data["lidarr"]
    watcher: ImportWatcher | None = ctx.bot_data.get("watcher")
    msg = update.effective_message
    try:
        info, queue, health = await asyncio.gather(
            lidarr.status(), lidarr.queue(size=1), lidarr.health())
    except LidarrError as e:
        await msg.reply_text(t("lidarr_error", error=e))
        return
    lines = [t("status", version=info.get("version", "?"),
               queue=queue.get("totalRecords", 0),
               watches=len(watcher) if watcher else 0)]
    if health:
        lines.append(t("health_issues"))
        lines += [f"• {h.get('type', '')}: {h.get('message', '')}" for h in health]
    else:
        lines.append(t("health_ok"))
    await msg.reply_text(_truncate("\n".join(lines), 4096))


def _should_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str) -> str | None:
    """In groups (GROUP_TRIGGER=smart) only react to links, @mentions and
    replies to the bot, so normal conversation is left alone. Returns the text
    to search, or None to stay silent."""
    cfg: Config = ctx.bot_data["cfg"]
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or cfg.group_trigger == "all":
        return text
    msg = update.effective_message
    mention = f"@{ctx.bot.username}" if ctx.bot.username else None
    if mention and mention.lower() in text.lower():
        return re.sub(re.escape(mention), "", text, flags=re.IGNORECASE).strip() or None
    reply = msg.reply_to_message
    if reply and reply.from_user and reply.from_user.id == ctx.bot.id:
        return text
    if resolver.URL_RE.search(text):
        return text
    return None


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or "").strip()
    if not text:
        return
    if not await _check_allowed(update, ctx):
        return
    text = _should_answer(update, ctx, text)
    if text:
        await _handle_query(update, ctx, text)


async def _handle_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    note = await update.effective_message.reply_text(t("searching"))
    try:
        await _search_and_prompt(update, ctx, note, text)
    except musicbrainz.MusicBrainzUnavailable:
        await _safe_edit(note, t("mb_unavailable"))
    except Exception:
        log.exception("Failed to handle %r", text)
        await _safe_edit(note, t("unexpected_error"))


async def _mark_library(lidarr: Lidarr, candidates: list[musicbrainz.Candidate]) -> None:
    async def one(c: musicbrainz.Candidate) -> None:
        try:
            c.library = await lidarr.album_state(c.rg_mbid)
        except LidarrError as e:
            log.debug("Library lookup for %s: %s", c.rg_mbid, e)

    await asyncio.gather(*(one(c) for c in candidates if c.rg_mbid))


async def _search_and_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             note: Message, text: str) -> None:
    msg = update.effective_message
    chat_id, user_id = _ids(update)
    try:
        query = await resolver.resolve(text)
    except resolver.UnsafeURL as e:
        log.warning("Refused to fetch non-public URL %s", e)
        await _safe_edit(note, t("cant_parse"))
        return
    except Exception:
        log.exception("Failed to resolve %r", text)
        await _safe_edit(note, t("cant_parse"))
        return
    log.info("Query from %s (%s): %r", chat_id, query.source, query)
    if not query.raw:
        await _safe_edit(note, t("cant_parse"))
        return

    artist_hit = None
    missing = False
    artist_known = False
    disco: list[tuple[str, str, str, str]] = []
    candidates: list[musicbrainz.Candidate] = []
    if query.kind == "artist" and query.artist:
        artist_hit = await musicbrainz.find_artist(query.artist)
    elif query.source == "text" and not query.artist:
        artist_hit = await musicbrainz.find_artist(query.raw)
    if artist_hit:
        disco = await musicbrainz.fetch_discography(artist_hit[1])
        candidates = _artist_candidates(*artist_hit, disco)
    if not candidates and query.kind != "artist":
        artist_hit = None
        disco = []
        candidates = await musicbrainz.search(query)
        if not candidates and query.artist:
            artist_hit = await musicbrainz.find_artist(query.artist)
            artist_known = artist_hit is not None
            if artist_hit:
                disco = await musicbrainz.fetch_discography(artist_hit[1])
                candidates = _artist_candidates(*artist_hit, disco)
                missing = bool(candidates)

    log.info("Candidates for %r: %s", query.raw, [c.label() for c in candidates])
    if not candidates:
        if artist_known:
            await _safe_edit(note, t("no_results_artist_known", artist=query.artist))
        else:
            await _safe_edit(note, t("no_results", query=query.raw))
        return

    await _mark_library(ctx.bot_data["lidarr"], candidates)
    token = _store_pending(Pending(candidates, owner=user_id))

    keyboard = [
        [InlineKeyboardButton(c.label()[:60], callback_data=f"a:{token}:{i}")]
        for i, c in enumerate(candidates)
    ]
    keyboard.append([InlineKeyboardButton(t("all_button"), callback_data=f"l:{token}")])
    keyboard.append([InlineKeyboardButton(t("cancel"), callback_data=f"x:{token}")])
    markup = InlineKeyboardMarkup(keyboard)

    first = candidates[0]
    if artist_hit and missing:
        key = "album_missing_artist_found" if query.kind == "album" else "track_missing_artist_found"
        caption = t(key, artist=_e(artist_hit[0]))
    elif artist_hit:
        caption = t("artist_mode", artist=_e(artist_hit[0]))
    elif query.kind == "album":
        caption = t("album_mode", source=_e(query.source), album=_e(first.album))
    else:
        caption = t("recognized", source=_e(query.source), track=_e(first.track))
    if any(c.library for c in candidates):
        caption += "\n" + t("legend")

    if not artist_hit:
        tracks = await musicbrainz.fetch_tracklist(first.rg_mbid)
        if tracks:
            target = "" if query.kind == "album" else first.track
            caption += ("\n\n" + t("tracklist", album=_e(first.album))
                        + "\n" + _format_tracklist(tracks, target))

    if not disco:
        disco = await musicbrainz.fetch_discography(first.artist_mbid)
    shown = _disco_main(disco)
    if shown:
        lines = [
            f"• {_e(title)} ({year})" + (f" [{kind}]" if kind != "Album" else "")
            for title, year, kind, _ in shown[:8]
        ]
        if len(shown) > 8:
            lines.append(f"… +{len(shown) - 8}")
        caption += ("\n\n" + t("other_albums", artist=_e(first.artist))
                    + "\n" + "\n".join(lines))

    cover = await musicbrainz.fetch_cover(first.rg_mbid)
    if cover:
        try:
            await msg.reply_photo(photo=cover, caption=_truncate(caption, 1024),
                                  parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest as e:
            log.warning("Could not send the cover (%s), falling back to text", e)
        else:
            # Only now: deleting first would leave the user with nothing if
            # the photo failed.
            try:
                await note.delete()
            except TelegramError:
                pass
            return
    await note.edit_text(_truncate(caption, 4096), parse_mode=ParseMode.HTML,
                         reply_markup=markup)


async def _update_prompt(q, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        if q.message and q.message.photo:
            await q.edit_message_caption(caption=text, reply_markup=markup)
        else:
            await q.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = ctx.bot_data["cfg"]
    lidarr: Lidarr = ctx.bot_data["lidarr"]
    q = update.callback_query
    chat_id, user_id = _ids(update)
    if not cfg.is_allowed(chat_id, user_id):
        await q.answer(t("not_authorized"), show_alert=True)
        return

    parts = (q.data or "").split(":")
    if len(parts) < 2:
        await q.answer()
        return
    action, token = parts[0], parts[1]
    pending = _get_pending(token)
    if pending is None:
        await q.answer()
        await _update_prompt(q, t("expired"))
        return
    if (pending.owner is not None and user_id != pending.owner
            and not cfg.is_admin(user_id)):
        await q.answer(t("not_your_request"), show_alert=True)
        return
    await q.answer()
    # Pop before the slow Lidarr call so a double tap can't add twice.
    PENDING.pop(token, None)
    keyboard = q.message.reply_markup if q.message else None

    if action == "x":
        await _update_prompt(q, t("cancelled"))
        return

    if action == "l":
        cand = pending.candidates[0]
        await _update_prompt(q, t("adding_artist", artist=cand.artist))
        try:
            status, name = await lidarr.add_artist_and_search(cand.artist_mbid)
        except Exception as e:
            await _add_failed(q, token, pending, keyboard, e, cand.artist_mbid)
            return
        await _update_prompt(q, t(status, artist=name))
        return

    try:
        cand = pending.candidates[int(parts[2])]
    except (IndexError, ValueError):
        await _update_prompt(q, t("expired"))
        return
    await _update_prompt(q, t("adding", label=cand.label()))
    try:
        status, title, album_id = await lidarr.add_and_search(cand.rg_mbid)
    except Exception as e:
        await _add_failed(q, token, pending, keyboard, e, cand.rg_mbid)
        return

    text = t({"complete": "album_complete", "exists": "album_exists"}.get(status, "album_added"),
             title=title)
    watcher: ImportWatcher | None = ctx.bot_data.get("watcher")
    if watcher is not None and status != "complete":
        watcher.add(album_id, chat_id, title, q.message.message_id if q.message else None)
        text += "\n" + t("will_notify")
    await _update_prompt(q, text)


async def _add_failed(q, token: str, pending: Pending, keyboard, error: Exception,
                      mbid: str) -> None:
    """Show the error but keep the buttons, so the user can simply retry."""
    if isinstance(error, LidarrError):
        log.error("Lidarr: %s", error)
        text = t("lidarr_error", error=error)
    else:
        log.error("Unexpected error while adding %s", mbid, exc_info=error)
        text = t("unexpected_error")
    pending.created = time.monotonic()
    PENDING[token] = pending
    await _update_prompt(q, text, keyboard)
