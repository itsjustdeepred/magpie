# Messages marked "HTML" are sent with parse_mode="HTML": every value
# interpolated into them must be passed through html.escape() first.
MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "start": (
            "🎵 Send me a YouTube / Shazam / Spotify / Deezer / Apple Music / "
            "Bandcamp link or type «Artist - Title»:\n"
            "I'll find the album and search it with your Lidarr indexers.\n"
            "Album and artist links work too.\n\n"
            "/add <link or text> search from a group\n"
            "/queue shows Lidarr's download queue\n"
            "/status shows Lidarr's status\n"
            "/id shows this chat's id\n"
            "/allow <id> authorizes a chat (admin)\n"
            "/deny <id> removes the authorization (admin)\n"
            "/chats lists the authorized chats (admin)"
        ),
        "chat_id": "This chat's ID: <code>{chat_id}</code>",  # HTML
        "chat_allowed": "✅ Chat {chat_id} authorized.",
        "chat_denied": "🚫 Chat {chat_id} removed.",
        "chat_usage": "Usage: /{command} [chat id] — the id must be a number, e.g. -1001234567890",
        "chat_list": "Authorized chats:\n{chats}",
        "chat_list_empty": "(none)",
        "not_allowed": "Chat not authorized. ID: <code>{chat_id}</code> — the admin can use /allow {chat_id}",  # HTML
        "not_authorized": "Not authorized",
        "not_your_request": "Only whoever sent this request can pick an option.",
        "add_usage": "Usage: /add <link or Artist - Title>",
        "searching": "🔍 Searching…",
        "cant_parse": "⚠️ I couldn't make sense of that message.",
        "mb_unavailable": "⚠️ MusicBrainz is not responding right now, try again in a minute.",
        "no_results": ("😕 No MusicBrainz results for: {query}\n"
                       "Lidarr can only add albums that exist on MusicBrainz."),
        "no_results_artist_known": (
            "😕 {artist} is on MusicBrainz, but this track is not.\n"
            "Lidarr can only add albums that exist on MusicBrainz — you can "
            "contribute the release at musicbrainz.org and try again later."),
        "recognized": "🎶 Recognized ({source}): <b>{track}</b>\nPick what to add:",  # HTML
        "album_mode": "💿 Album ({source}): <b>{album}</b>\nPick what to add:",  # HTML
        "tracklist": "📀 <b>{album}</b>:",  # HTML
        "artist_mode": "👤 Artist: <b>{artist}</b>\nPick an album or the entire discography:",  # HTML
        "track_missing_artist_found": (  # HTML
            "😕 This track is not on MusicBrainz (so Lidarr can't grab it), "
            "but <b>{artist}</b> is.\nHere is what's available instead:"),
        "album_missing_artist_found": (  # HTML
            "😕 This album is not on MusicBrainz (so Lidarr can't grab it), "
            "but <b>{artist}</b> is.\nHere is what's available instead:"),
        "cmd_add": "Search a link or «Artist - Title»",
        "cmd_queue": "Show Lidarr's download queue",
        "cmd_status": "Show Lidarr's status",
        "cmd_id": "Show this chat's id",
        "other_albums": "💿 Discography of {artist}:",  # HTML
        "legend": "✅ already in the library · 📥 in Lidarr, still missing",
        "all_button": "⬇️ Entire discography",
        "adding_artist": "⏳ Adding the entire discography of {artist}…",
        "artist_added": "✅ {artist}: discography added and monitored, searching every album on your indexers.",
        "artist_exists": "🔎 {artist} already in the library: all albums monitored, search started.",
        "cancel": "❌ Cancel",
        "cancelled": "Cancelled.",
        "expired": "⌛ Request expired, send the link again.",
        "adding": "⏳ Adding «{label}» to Lidarr…",
        "album_added": "✅ «{title}» added and monitored: search started on your indexers.",
        "album_exists": "🔎 «{title}» already in the library: search started on your indexers.",
        "album_complete": "✅ «{title}» is already in the library with every track, nothing to do.",
        "will_notify": "🔔 I'll post here when it has been imported.",
        "lidarr_error": "⚠️ Lidarr error: {error}",
        "unexpected_error": "⚠️ Unexpected error, check the bot logs.",
        "queue_empty": "📭 Lidarr's download queue is empty.",
        "queue_header": "📥 Download queue ({count}):",
        "status": "🟢 Lidarr {version}\n📥 Queue: {queue}\n🔔 Imports being tracked: {watches}",
        "health_ok": "✅ No health issues.",
        "health_issues": "⚠️ Health issues:",
        "imported": "🎉 «{title}» has been imported into Lidarr.",
        "import_partial": ("🎧 «{title}»: {have}/{total} tracks imported after {days} days. "
                           "I'll stop tracking it here."),
        "import_timeout": ("⌛ «{title}» still hasn't been downloaded after {days} days. "
                           "Lidarr will keep looking; I'll stop tracking it here."),
    },
    "it": {
        "start": (
            "🎵 Mandami un link YouTube / Shazam / Spotify / Deezer / Apple Music / "
            "Bandcamp o scrivi «Artista - Titolo»:\n"
            "trovo l'album e lo cerco con gli indexer di Lidarr.\n"
            "Funzionano anche i link ad album e artisti.\n\n"
            "/add <link o testo> cerca da un gruppo\n"
            "/queue mostra la coda di download di Lidarr\n"
            "/status mostra lo stato di Lidarr\n"
            "/id mostra l'id di questa chat\n"
            "/allow <id> autorizza una chat (admin)\n"
            "/deny <id> rimuove l'autorizzazione (admin)\n"
            "/chats elenca le chat autorizzate (admin)"
        ),
        "chat_id": "ID di questa chat: <code>{chat_id}</code>",
        "chat_allowed": "✅ Chat {chat_id} autorizzata.",
        "chat_denied": "🚫 Chat {chat_id} rimossa.",
        "chat_usage": "Uso: /{command} [id chat] — l'id deve essere un numero, es. -1001234567890",
        "chat_list": "Chat autorizzate:\n{chats}",
        "chat_list_empty": "(nessuna)",
        "not_allowed": "Chat non autorizzata. ID: <code>{chat_id}</code> — l'admin può usare /allow {chat_id}",
        "not_authorized": "Non autorizzato",
        "not_your_request": "Solo chi ha inviato la richiesta può scegliere.",
        "add_usage": "Uso: /add <link o Artista - Titolo>",
        "searching": "🔍 Cerco…",
        "cant_parse": "⚠️ Non sono riuscito a interpretare il messaggio.",
        "mb_unavailable": "⚠️ MusicBrainz non risponde in questo momento, riprova tra un minuto.",
        "no_results": ("😕 Nessun risultato su MusicBrainz per: {query}\n"
                       "Lidarr può aggiungere solo album censiti su MusicBrainz."),
        "no_results_artist_known": (
            "😕 {artist} esiste su MusicBrainz, ma questo brano non è censito.\n"
            "Lidarr può aggiungere solo album presenti su MusicBrainz — puoi "
            "inserire la release su musicbrainz.org e riprovare più avanti."),
        "recognized": "🎶 Riconosciuto ({source}): <b>{track}</b>\nScegli cosa aggiungere:",
        "album_mode": "💿 Album ({source}): <b>{album}</b>\nScegli cosa aggiungere:",
        "tracklist": "📀 <b>{album}</b>:",
        "artist_mode": "👤 Artista: <b>{artist}</b>\nScegli un album o tutta la discografia:",
        "track_missing_artist_found": (
            "😕 Questo brano non è censito su MusicBrainz (quindi Lidarr non può "
            "prenderlo), ma <b>{artist}</b> sì.\nEcco cosa c'è di suo:"),
        "album_missing_artist_found": (
            "😕 Questo album non è censito su MusicBrainz (quindi Lidarr non può "
            "prenderlo), ma <b>{artist}</b> sì.\nEcco cosa c'è di suo:"),
        "cmd_add": "Cerca un link o «Artista - Titolo»",
        "cmd_queue": "Mostra la coda di download di Lidarr",
        "cmd_status": "Mostra lo stato di Lidarr",
        "cmd_id": "Mostra l'id di questa chat",
        "other_albums": "💿 Discografia di {artist}:",
        "legend": "✅ già in libreria · 📥 in Lidarr, ancora mancante",
        "all_button": "⬇️ Tutta la discografia",
        "adding_artist": "⏳ Aggiungo tutta la discografia di {artist}…",
        "artist_added": "✅ {artist}: discografia aggiunta e monitorata, ricerca di tutti gli album sugli indexer.",
        "artist_exists": "🔎 {artist} già in libreria: tutti gli album monitorati, ricerca avviata.",
        "cancel": "❌ Annulla",
        "cancelled": "Annullato.",
        "expired": "⌛ Richiesta scaduta, rimanda il link.",
        "adding": "⏳ Aggiungo «{label}» a Lidarr…",
        "album_added": "✅ «{title}» aggiunto e monitorato: ricerca avviata sugli indexer.",
        "album_exists": "🔎 «{title}» già in libreria: ricerca avviata sugli indexer.",
        "album_complete": "✅ «{title}» è già in libreria con tutte le tracce, niente da fare.",
        "will_notify": "🔔 Ti avviso qui quando è stato importato.",
        "lidarr_error": "⚠️ Errore Lidarr: {error}",
        "unexpected_error": "⚠️ Errore inatteso, guarda i log del bot.",
        "queue_empty": "📭 La coda di download di Lidarr è vuota.",
        "queue_header": "📥 Coda di download ({count}):",
        "status": "🟢 Lidarr {version}\n📥 In coda: {queue}\n🔔 Import monitorati: {watches}",
        "health_ok": "✅ Nessun problema segnalato.",
        "health_issues": "⚠️ Problemi segnalati:",
        "imported": "🎉 «{title}» è stato importato in Lidarr.",
        "import_partial": ("🎧 «{title}»: {have}/{total} tracce importate dopo {days} giorni. "
                           "Smetto di seguirlo qui."),
        "import_timeout": ("⌛ «{title}» non è ancora stato scaricato dopo {days} giorni. "
                           "Lidarr continuerà a cercarlo; smetto di seguirlo qui."),
    },
}

DEFAULT_LANG = "en"
_lang = DEFAULT_LANG


def set_language(lang: str) -> str:
    global _lang
    _lang = lang.lower() if lang and lang.lower() in MESSAGES else DEFAULT_LANG
    return _lang


def t(key: str, **kwargs) -> str:
    text = MESSAGES[_lang].get(key) or MESSAGES[DEFAULT_LANG][key]
    return text.format(**kwargs) if kwargs else text
