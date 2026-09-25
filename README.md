# Magpie

[![Publish Docker image](https://github.com/itsjustdeepred/magpie/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/itsjustdeepred/magpie/actions/workflows/docker-publish.yml)

A Telegram bot that bridges to **Lidarr**: send it a YouTube / Shazam / Spotify /
Deezer / Apple Music / Bandcamp link (or simply `Artist - Title`) and it recognizes the track, finds the album
containing it on MusicBrainz, asks you to confirm with inline buttons and then
adds it to Lidarr, kicking off the search **with the indexers you already have
configured**.

When the album's tracklist is shown for confirmation, the track you sent is
highlighted in **bold** with a ▶️ marker, so you can see at a glance which song
the album was matched on — even if it sits far down the list.

Album and artist links work too: an album link goes straight to that album,
an artist link offers their albums or the whole discography.

Buttons for albums already in Lidarr are marked ✅ (complete) or 📥 (in
Lidarr but still missing files), and once an album you added has been imported
the bot posts a 🎉 notification in the same chat.

> Note: Lidarr works with artists/albums, not individual tracks — that's why
> the bot adds the album containing the song.

## Flow

```
message/link → resolver (oEmbed / APIs / og-tags) → MusicBrainz (ISRC or recording → release group)
            → Telegram confirmation → Lidarr API (album add + AlbumSearch) → indexers
```

The confirmation message shows the album cover (from the [Cover Art
Archive](https://coverartarchive.org)) when one is available.

## Requirements

- A running Lidarr instance with its API key, at least one root folder and the
  quality/metadata profiles configured.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- Docker (recommended) or Python 3.12+.

## Configuration

Copy the template and fill it in:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|:---:|---|
| `TELEGRAM_BOT_TOKEN` | yes | Token from @BotFather. |
| `LIDARR_URL` | yes | Base URL of your Lidarr, e.g. `http://localhost:8686`. |
| `LIDARR_API_KEY` | yes | Lidarr → Settings → General → Security. |
| `ALLOWED_CHAT_IDS` | no | Comma-separated whitelisted chat/channel ids. |
| `ADMIN_USER_ID` | no | Your Telegram user id; can manage the whitelist and DM the bot anywhere. |
| `BOT_LANG` | no | UI language, `en` or `it` (default `en`). |
| `LIDARR_ROOT_FOLDER` | no | Defaults to Lidarr's first root folder. |
| `LIDARR_QUALITY_PROFILE` | no | Defaults to Lidarr's first quality profile. |
| `LIDARR_METADATA_PROFILE` | no | Defaults to Lidarr's first metadata profile. |
| `GROUP_TRIGGER` | no | `smart` (default): in groups answer only links, @mentions, replies and `/add`. `all`: every message. |
| `NOTIFY_ON_IMPORT` | no | Post in the chat when an added album is imported (default `true`). |
| `NOTIFY_MAX_DAYS` | no | Stop tracking an import after this many days (default `7`). |
| `NOTIFY_INTERVAL` | no | Seconds between import checks (default `120`, min `30`). |
| `PUID` / `PGID` | no | Docker only: user/group the bot runs as (default `1000`). |
| `LOG_LEVEL` | no | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`. |

Root folder and profile names are checked at startup, so a typo shows up in
the logs right away instead of on the first add.

## Run with Docker

The image is built from the included `Dockerfile`; `docker-compose.yml` wires up
the `.env` file and a persistent `./data` volume (the chat whitelist and the
pending import notifications are stored there).

The container starts as root only to hand `/data` over to `PUID:PGID` (default
`1000:1000`), then drops privileges; `docker run --user …` is honored as-is.
A `HEALTHCHECK` reports the container unhealthy if the bot's event loop stalls.

```bash
# build and start in the background
docker compose up -d --build

# follow the logs
docker compose logs -f

# stop
docker compose down
```

To update after pulling new code, rebuild with `docker compose up -d --build`.

If your Lidarr runs in another Docker network, make sure `LIDARR_URL` is
reachable from this container (use the service name or host IP, not
`localhost`).

### Use the pre-built image

Every push to `main` triggers a GitHub Actions workflow that builds a
multi-architecture image (`linux/amd64` + `linux/arm64`) and publishes it to the
GitHub Container Registry, so you don't have to build anything yourself:

```bash
docker run -d --name magpie \
  --env-file .env \
  -v "$(pwd)/data:/data" \
  ghcr.io/itsjustdeepred/magpie:latest
```

Or with Compose — replace `build: .` in `docker-compose.yml` with:

```yaml
    image: ghcr.io/itsjustdeepred/magpie:latest
```

Available tags: `latest`, `main`, `sha-<commit>`, and `X.Y.Z` / `X.Y` for
released versions (pushing a `vX.Y.Z` git tag publishes them).

### Without Compose

```bash
docker build -t magpie .
docker run -d --name magpie \
  --env-file .env \
  -v "$(pwd)/data:/data" \
  magpie
```

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m magpie
```

### Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

CI runs both on every push and pull request; the Docker image is only
published when they pass.

## Authorizing chats and channels

The bot only replies to whitelisted chats:

- type `/id` in a chat (or add the bot to a group/channel) to discover its id;
- put it in `ALLOWED_CHAT_IDS` in `.env`, **or** set `ADMIN_USER_ID` and use
  `/allow <id>` directly from Telegram (`/deny` removes, `/chats` lists).

For **groups**: by default (`GROUP_TRIGGER=smart`) the bot ignores normal
conversation and only answers messages containing a link, mentioning it
(`@yourbot Artist - Title`), replying to it, or `/add <link or text>`. Buttons
can only be used by whoever made the request (and the admin).

For **channels**: add the bot as a channel administrator; channel posts arrive
as `channel_post` updates and are handled normally.

## Language

User-facing messages are localized. Set `BOT_LANG` in `.env` (`en` or `it`,
default `en`). To contribute a new language, add a catalog to `magpie/i18n.py` —
missing keys automatically fall back to English.

## Supported sources

| Source | Method |
|---|---|
| YouTube / YouTube Music (incl. Shorts, youtu.be) | oEmbed (title + channel) |
| Shazam | song page (og-tags) |
| Spotify — track / album / artist | oEmbed + og-tags |
| Deezer — track / album / artist | public API; tracks are matched by **ISRC** |
| Apple Music — song / album / artist | iTunes lookup API |
| Bandcamp — track / album | og-tags |
| Short share links (`spotify.link`, `link.deezer.com`, …) | followed, then as above |
| Other links | page og:title |
| Free text | `Artist - Title`, an artist name, or free search |

Links to private or local addresses (e.g. `http://localhost`, `192.168.x.x`)
are refused, redirects included.

## Commands

| Command | Description |
|---|---|
| `/start`, `/help` | Usage help. |
| `/add <link or text>` | Search explicitly (handy in groups). |
| `/queue` | Lidarr's download queue with progress. |
| `/status` | Lidarr version, queue size, health issues, imports being tracked. |
| `/id` | Show the current chat's id. |
| `/allow <id>` | Authorize a chat (admin only). |
| `/deny <id>` | Remove an authorization (admin only). |
| `/chats` | List authorized chats (admin only). |
