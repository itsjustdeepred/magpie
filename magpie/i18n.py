MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "start": (
            "🎵 Send me a YouTube/Shazam/Spotify link or type «Artist - Title»:\n"
            "I'll find the album and search it with your Lidarr indexers.\n\n"
            "/id shows this chat's id\n"
            "/allow <id> authorizes a chat (admin)\n"
            "/deny <id> removes the authorization (admin)\n"
            "/chats lists the authorized chats (admin)"
        ),
        "chat_id": "This chat's ID: `{chat_id}`",
        "chat_allowed": "✅ Chat {chat_id} authorized.",
        "chat_denied": "🚫 Chat {chat_id} removed.",
        "chat_list": "Authorized chats:\n{chats}",
        "chat_list_empty": "(none)",
        "not_allowed": "Chat not authorized. ID: `{chat_id}` — the admin can use /allow {chat_id}",
        "not_authorized": "Not authorized",
        "searching": "🔍 Searching…",
        "cant_parse": "⚠️ I couldn't make sense of that message.",
        "no_results": ("😕 No MusicBrainz results for: {query}\n"
                       "Lidarr can only add albums that exist on MusicBrainz."),
        "no_results_artist_known": (
            "😕 {artist} is on MusicBrainz, but this track is not.\n"
            "Lidarr can only add albums that exist on MusicBrainz — you can "
            "contribute the release at musicbrainz.org and try again later."),
        "recognized": "🎶 Recognized ({source}): *{track}*\nPick what to add:",
        "tracklist": "📀 *{album}*:",
        "artist_mode": "👤 Artist: *{artist}*\nPick an album or the entire discography:",
        "track_missing_artist_found": (
            "😕 This track is not on MusicBrainz (so Lidarr can't grab it), "
            "but *{artist}* is.\nHere is what's available instead:"),
        "other_albums": "💿 Discography of {artist}:",
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
        "lidarr_error": "⚠️ Lidarr error: {error}",
        "unexpected_error": "⚠️ Unexpected error, check the bot logs.",
    },
    "it": {
        "start": (
            "🎵 Mandami un link YouTube/Shazam/Spotify o scrivi «Artista - Titolo»:\n"
            "trovo l'album e lo cerco con gli indexer di Lidarr.\n\n"
            "/id mostra l'id di questa chat\n"
            "/allow <id> autorizza una chat (admin)\n"
            "/deny <id> rimuove l'autorizzazione (admin)\n"
            "/chats elenca le chat autorizzate (admin)"
        ),
        "chat_id": "ID di questa chat: `{chat_id}`",
        "chat_allowed": "✅ Chat {chat_id} autorizzata.",
        "chat_denied": "🚫 Chat {chat_id} rimossa.",
        "chat_list": "Chat autorizzate:\n{chats}",
        "chat_list_empty": "(nessuna)",
        "not_allowed": "Chat non autorizzata. ID: `{chat_id}` — l'admin può usare /allow {chat_id}",
        "not_authorized": "Non autorizzato",
        "searching": "🔍 Cerco…",
        "cant_parse": "⚠️ Non sono riuscito a interpretare il messaggio.",
        "no_results": ("😕 Nessun risultato su MusicBrainz per: {query}\n"
                       "Lidarr può aggiungere solo album censiti su MusicBrainz."),
        "no_results_artist_known": (
            "😕 {artist} esiste su MusicBrainz, ma questo brano non è censito.\n"
            "Lidarr può aggiungere solo album presenti su MusicBrainz — puoi "
            "inserire la release su musicbrainz.org e riprovare più avanti."),
        "recognized": "🎶 Riconosciuto ({source}): *{track}*\nScegli cosa aggiungere:",
        "tracklist": "📀 *{album}*:",
        "artist_mode": "👤 Artista: *{artist}*\nScegli un album o tutta la discografia:",
        "track_missing_artist_found": (
            "😕 Questo brano non è censito su MusicBrainz (quindi Lidarr non può "
            "prenderlo), ma *{artist}* sì.\nEcco cosa c'è di suo:"),
        "other_albums": "💿 Discografia di {artist}:",
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
        "lidarr_error": "⚠️ Errore Lidarr: {error}",
        "unexpected_error": "⚠️ Errore inatteso, guarda i log del bot.",
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
