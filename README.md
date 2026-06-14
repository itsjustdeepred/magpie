# Magpie

A Telegram bot that bridges to **Lidarr**: send it a YouTube / Shazam / Spotify
link (or simply `Artist - Title`) and it recognizes the track, finds the album
containing it on MusicBrainz, asks you to confirm with inline buttons and then
adds it to Lidarr, kicking off the search **with the indexers you already have
configured**.

When the album's tracklist is shown for confirmation, the track you sent is
highlighted in **bold** with a ▶️ marker, so you can see at a glance which song
the album was matched on — even if it sits far down the list.

> Note: Lidarr works with artists/albums, not individual tracks — that's why
> the bot adds the album containing the song.

## Flow

```
message/link → resolver (oEmbed / og-tags) → MusicBrainz (recording → release group)
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

## Run with Docker

The image is built from the included `Dockerfile`; `docker-compose.yml` wires up
the `.env` file and a persistent `./data` volume (the chat whitelist is stored
there).

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

## Authorizing chats and channels

The bot only replies to whitelisted chats:

- type `/id` in a chat (or add the bot to a group/channel) to discover its id;
- put it in `ALLOWED_CHAT_IDS` in `.env`, **or** set `ADMIN_USER_ID` and use
  `/allow <id>` directly from Telegram (`/deny` removes, `/chats` lists).

For **channels**: add the bot as a channel administrator; channel posts arrive
as `channel_post` updates and are handled normally.

## Language

User-facing messages are localized. Set `BOT_LANG` in `.env` (`en` or `it`,
default `en`). To contribute a new language, add a catalog to `magpie/i18n.py` —
missing keys automatically fall back to English.

## Supported sources

| Source | Method |
|---|---|
| YouTube / YouTube Music | oEmbed (title + channel) |
| Shazam | discovery API (track id from the URL) |
| Spotify | oEmbed + og-tags |
| Other links | page og:title |
| Free text | `Artist - Title` or free search |

## Commands

| Command | Description |
|---|---|
| `/start` | Usage help. |
| `/id` | Show the current chat's id. |
| `/allow <id>` | Authorize a chat (admin only). |
| `/deny <id>` | Remove an authorization (admin only). |
| `/chats` | List authorized chats (admin only). |
