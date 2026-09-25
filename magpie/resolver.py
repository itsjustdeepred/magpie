import asyncio
import html
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

URL_RE = re.compile(r"https?://\S+")

# Browser UA for pages that serve different markup to bots. Spotify is the
# exception: it only renders og-tags server side for link-preview crawlers.
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/138.0.7204.49 Safari/537.36")
CRAWLER_UA = "facebookexternalhit/1.1"
SHAZAM_UA = "Mozilla/5.0"

MAX_PAGE_BYTES = 1_000_000
MAX_REDIRECTS = 5

NOISE_RE = re.compile(
    r"[(\[][^)\]]*(?:official|video|audio|visualizer|lyric|remaster|version|"
    r"hd|4k|ufficiale|testo|explicit|hq)[^)\]]*[)\]]",
    re.IGNORECASE,
)

_NOISE_WORD = r"(?:official|music|video|audio|lyrics?|visualizer|videoclip|ufficiale|hd|4k|hq)"
TRAILING_NOISE_RE = re.compile(rf"(?:\s+{_NOISE_WORD})+\s*$", re.IGNORECASE)
RELEASE_SUFFIX_RE = re.compile(r"\s+-\s+(?:Single|EP)$")

YT_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([\w-]{11})")
SHAZAM_ID_RE = re.compile(r"/(?:song|track)/(\d+)")
SHAZAM_DESC_RE = re.compile(r"^Listen to (.+) by (.+?)\. See ")
BY_RE = re.compile(r"^(.+), by (.+)$")

# Share links that only redirect to a canonical URL we know how to handle.
SHORTENERS = ("spotify.link", "link.deezer.com", "deezer.page.link", "dzr.page.link")


class UnsafeURL(Exception):
    """The URL points to a non-public address (or redirects to one)."""


@dataclass
class TrackQuery:
    raw: str
    artist: str | None = None
    title: str | None = None
    source: str = "text"
    kind: str = "track"  # "track", "album" or "artist"
    isrc: str | None = None


def _clean(s: str) -> str:
    s = NOISE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -–—|")
    s = TRAILING_NOISE_RE.sub("", s)
    return s.strip()


def _split_dash(s: str) -> tuple[str | None, str | None]:
    parts = re.split(r"\s+[-–—]\s+", s)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None, None


def _query(source: str, kind: str = "track", artist: str | None = None,
           title: str | None = None, isrc: str | None = None) -> TrackQuery:
    artist = artist or None
    title = title or None
    raw = " ".join(p for p in (artist, title) if p)
    return TrackQuery(raw=raw, artist=artist, title=title, source=source, kind=kind, isrc=isrc)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _host_is(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _path_parts(url: str) -> list[str]:
    return [p for p in urlparse(url).path.split("/") if p]


_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(["'])(.*?)\2""", re.DOTALL)


def _meta_tags(html_text: str) -> dict[str, str]:
    """Map every <meta property|name=... content=...> to its content, e.g. 'og:title'."""
    tags: dict[str, str] = {}
    for m in _META_RE.finditer(html_text):
        attrs = {k.lower(): v for k, _, v in _ATTR_RE.findall(m.group(0))}
        key = attrs.get("property") or attrs.get("name")
        if key and "content" in attrs:
            tags.setdefault(key.lower(), html.unescape(attrs["content"]))
    return tags


def _clean_channel(name: str) -> str:
    name = re.sub(r"\s*-\s*Topic$", "", name).strip()
    if name.endswith("VEVO"):
        # "TaylorSwiftVEVO" -> "Taylor Swift"
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name[:-4]).strip()
    return name


async def _is_public(host: str) -> bool:
    if not host:
        return False
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except OSError:
            return False
        addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    return bool(addrs) and all(a.is_global for a in addrs)


async def _fetch(client: httpx.AsyncClient, url: str,
                 user_agent: str = BROWSER_UA) -> tuple[str, str]:
    """GET a user-supplied URL; returns (final_url, text).

    Every hop, redirects included, must resolve to a public address, so a
    link can't be used to make the bot probe the local network, and the body
    is capped at MAX_PAGE_BYTES.
    """
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise UnsafeURL(url)
        if not await _is_public(parsed.hostname or ""):
            raise UnsafeURL(url)
        async with client.stream("GET", url, headers={"User-Agent": user_agent},
                                 follow_redirects=False) as r:
            if r.is_redirect and "location" in r.headers:
                url = urljoin(url, r.headers["location"])
                continue
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) >= MAX_PAGE_BYTES:
                    break
            return url, body.decode(r.encoding or "utf-8", errors="replace")
    raise UnsafeURL(f"too many redirects: {url}")


async def _oembed(client: httpx.AsyncClient, endpoint: str, url: str) -> dict:
    r = await client.get(endpoint, params={"url": url, "format": "json"})
    r.raise_for_status()
    return r.json()


async def resolve(text: str) -> TrackQuery:
    m = URL_RE.search(text)
    if not m:
        cleaned = _clean(text)
        artist, title = _split_dash(cleaned)
        return TrackQuery(raw=cleaned, artist=artist, title=title, source="text")

    url = m.group(0).rstrip(").,>]!?")
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=15, headers={"User-Agent": BROWSER_UA}
    ) as client:
        return await _dispatch(client, url)


async def _dispatch(client: httpx.AsyncClient, url: str, depth: int = 0) -> TrackQuery:
    host = _host(url)
    if _host_is(host, *SHORTENERS) and depth == 0:
        final, _ = await _fetch(client, url)
        return await _dispatch(client, final, depth + 1)
    if _host_is(host, "youtube.com", "youtu.be"):
        return await _resolve_youtube(client, url)
    if _host_is(host, "shazam.com"):
        return await _resolve_shazam(client, url)
    if _host_is(host, "open.spotify.com"):
        return await _resolve_spotify(client, url)
    if _host_is(host, "deezer.com"):
        return await _resolve_deezer(client, url)
    if _host_is(host, "music.apple.com", "itunes.apple.com"):
        return await _resolve_apple(client, url)
    source = "bandcamp" if _host_is(host, "bandcamp.com") else "link"
    return await _resolve_og_page(client, url, source)


async def _resolve_youtube(client: httpx.AsyncClient, url: str) -> TrackQuery:
    # Normalize music.youtube.com / shorts / youtu.be links to a watch URL.
    m = YT_ID_RE.search(url)
    target = f"https://www.youtube.com/watch?v={m.group(1)}" if m else url
    data = await _oembed(client, "https://www.youtube.com/oembed", target)
    title = _clean(data.get("title", ""))
    channel = _clean_channel(data.get("author_name", ""))
    artist, track = _split_dash(title)
    if artist and track:
        return TrackQuery(raw=title, artist=artist, title=track, source="youtube")
    raw = f"{channel} {title}".strip()
    return TrackQuery(raw=raw, artist=channel or None, title=title or None, source="youtube")


async def _resolve_shazam(client: httpx.AsyncClient, url: str) -> TrackQuery:
    # Shazam answers 405 to a full browser UA, but serves og-tags to a bare one.
    _, page = await _fetch(client, url, SHAZAM_UA)
    tags = _meta_tags(page)
    # Unknown ids render some unrelated song: only trust the page when it is
    # about the id we asked for, otherwise fall back to the URL slug.
    wanted = SHAZAM_ID_RE.search(url)
    served = SHAZAM_ID_RE.search(tags.get("og:url", ""))
    if wanted and (not served or served.group(1) != wanted.group(1)):
        return _og_query({}, url, "shazam")
    m = SHAZAM_DESC_RE.match(tags.get("og:description", ""))
    if m:
        return _query("shazam", title=_clean(m.group(1)), artist=m.group(2).strip())
    # og:title is "Title - Artist: Song Lyrics, Music Videos & Concerts".
    og_title = re.sub(r":\s*Song Lyrics.*$", "", tags.get("og:title", ""))
    title, artist = _split_dash(og_title)
    if title and artist:
        return _query("shazam", title=_clean(title), artist=artist)
    return _og_query(tags, url, "shazam")


async def _resolve_spotify(client: httpx.AsyncClient, url: str) -> TrackQuery:
    parts = _path_parts(url)
    if parts and parts[0].startswith("intl-"):
        parts = parts[1:]
    kind = parts[0] if parts else "track"

    data = await _oembed(client, "https://open.spotify.com/oembed", url)
    name = _clean(data.get("title", ""))
    if kind == "artist":
        return _query("spotify", "artist", artist=name)

    artist = None
    try:
        _, page = await _fetch(client, url, CRAWLER_UA)
        tags = _meta_tags(page)
        # Track: "Artist · Album · Song · 1987"; album: "Artist · album · 1973 · 10 songs"
        seg = [s.strip() for s in tags.get("og:description", "").split("·") if s.strip()]
        artist = tags.get("music:musician_description") or (seg[0] if seg else None)
        if artist and artist.lower() == name.lower():
            artist = seg[1] if len(seg) > 1 else None
    except (httpx.HTTPError, UnsafeURL):
        pass
    return _query("spotify", "album" if kind == "album" else "track", artist=artist, title=name)


async def _resolve_deezer(client: httpx.AsyncClient, url: str) -> TrackQuery:
    m = re.search(r"/(track|album|artist)/(\d+)", urlparse(url).path)
    if not m:
        return await _resolve_og_page(client, url, "deezer")
    kind, item_id = m.groups()
    r = await client.get(f"https://api.deezer.com/{kind}/{item_id}")
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        return await _resolve_og_page(client, url, "deezer")
    if kind == "artist":
        return _query("deezer", "artist", artist=data.get("name"))
    artist = (data.get("artist") or {}).get("name")
    title = _clean(data.get("title", ""))
    if kind == "album":
        return _query("deezer", "album", artist=artist, title=title)
    return _query("deezer", artist=artist, title=title, isrc=data.get("isrc") or None)


async def _resolve_apple(client: httpx.AsyncClient, url: str) -> TrackQuery:
    parsed = urlparse(url)
    parts = _path_parts(url)
    country = parts[0] if parts and len(parts[0]) == 2 else "us"
    track_id = parse_qs(parsed.query).get("i", [None])[0]
    ids = [p for p in parts if p.lstrip("id").isdigit()]
    if track_id:
        kind, item_id = "track", track_id
    elif ids and "song" in parts:
        kind, item_id = "track", ids[-1]
    elif ids and "album" in parts:
        kind, item_id = "album", ids[-1]
    elif ids and "artist" in parts:
        kind, item_id = "artist", ids[-1]
    else:
        return await _resolve_og_page(client, url, "apple")

    r = await client.get("https://itunes.apple.com/lookup",
                         params={"id": item_id.lstrip("id"), "country": country})
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        return await _resolve_og_page(client, url, "apple")
    item = results[0]
    artist = item.get("artistName")
    if kind == "artist":
        return _query("apple", "artist", artist=artist)
    if kind == "album":
        album = RELEASE_SUFFIX_RE.sub("", item.get("collectionName", ""))
        return _query("apple", "album", artist=artist, title=_clean(album))
    return _query("apple", artist=artist, title=_clean(item.get("trackName", "")))


def _og_query(tags: dict[str, str], url: str, source: str) -> TrackQuery:
    title = tags.get("og:title", "")
    og_type = tags.get("og:type", "")
    kind = "album" if og_type in ("album", "music.album") else "track"

    # Bandcamp style: "Title, by Artist"
    m = BY_RE.match(title)
    if m:
        return _query(source, kind, artist=m.group(2).strip(), title=_clean(m.group(1)))

    title = _clean(title)
    if not title:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        title = _clean(unquote(slug).replace("-", " "))
    artist, track = _split_dash(title)
    return TrackQuery(raw=title, artist=artist, title=track, source=source, kind=kind)


async def _resolve_og_page(client: httpx.AsyncClient, url: str, source: str) -> TrackQuery:
    final, page = await _fetch(client, url)
    return _og_query(_meta_tags(page), final, source)
