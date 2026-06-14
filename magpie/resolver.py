import html
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

URL_RE = re.compile(r"https?://\S+")

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/138.0.7204.49 Safari/537.36")

NOISE_RE = re.compile(
    r"[(\[][^)\]]*(?:official|video|audio|visualizer|lyric|remaster|version|"
    r"hd|4k|ufficiale|testo|explicit|hq)[^)\]]*[)\]]",
    re.IGNORECASE,
)

_NOISE_WORD = r"(?:official|music|video|audio|lyrics?|visualizer|videoclip|ufficiale|hd|4k|hq)"
TRAILING_NOISE_RE = re.compile(rf"(?:\s+{_NOISE_WORD})+\s*$", re.IGNORECASE)


@dataclass
class TrackQuery:
    raw: str
    artist: str | None = None
    title: str | None = None
    source: str = "text"


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


async def _oembed(client: httpx.AsyncClient, endpoint: str, url: str) -> dict:
    r = await client.get(endpoint, params={"url": url, "format": "json"})
    r.raise_for_status()
    return r.json()


def _og_tags(html_text: str) -> dict[str, str]:
    tags = {}
    for m in re.finditer(
        r'<meta[^>]+(?:property|name)="og:(\w+)"[^>]+content="([^"]*)"', html_text
    ):
        tags[m.group(1)] = html.unescape(m.group(2))
    for m in re.finditer(
        r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="og:(\w+)"', html_text
    ):
        tags.setdefault(m.group(2), html.unescape(m.group(1)))
    return tags


async def resolve(text: str) -> TrackQuery:
    m = URL_RE.search(text)
    if not m:
        artist, title = _split_dash(_clean(text))
        return TrackQuery(raw=_clean(text), artist=artist, title=title, source="text")

    url = m.group(0).rstrip(").,")
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=15, headers=headers
    ) as client:
        if re.search(r"(youtube\.com|youtu\.be)", url):
            return await _resolve_youtube(client, url)
        if "shazam.com" in url:
            return await _resolve_shazam(client, url)
        if "open.spotify.com" in url:
            return await _resolve_spotify(client, url)
        return await _resolve_og_page(client, url, "link")


async def _resolve_youtube(client: httpx.AsyncClient, url: str) -> TrackQuery:
    data = await _oembed(client, "https://www.youtube.com/oembed", url)
    title = _clean(data.get("title", ""))
    channel = re.sub(r"\s*-\s*Topic$|VEVO$", "", data.get("author_name", "")).strip()
    artist, track = _split_dash(title)
    if artist and track:
        return TrackQuery(raw=title, artist=artist, title=track, source="youtube")
    raw = f"{channel} {title}".strip()
    return TrackQuery(raw=raw, artist=channel or None, title=title or None, source="youtube")


async def _resolve_shazam(client: httpx.AsyncClient, url: str) -> TrackQuery:
    m = re.search(r"shazam\.com/(?:[a-z-]+/)?(?:song|track)/(\d+)", url)
    if m:
        r = await client.get(
            f"https://www.shazam.com/discovery/v5/en-US/US/web/-/track/{m.group(1)}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            data = r.json()
            title = _clean(data.get("title", ""))
            artist = data.get("subtitle") or None
            if title:
                return TrackQuery(raw=f"{artist or ''} {title}".strip(),
                                  artist=artist, title=title, source="shazam")
    return await _resolve_og_page(client, url, "shazam")


async def _resolve_spotify(client: httpx.AsyncClient, url: str) -> TrackQuery:
    data = await _oembed(client, "https://open.spotify.com/oembed", url)
    title = _clean(data.get("title", ""))
    artist = None
    try:
        page = await client.get(url)
        og = _og_tags(page.text)
        desc = og.get("description", "")
        seg = [s.strip() for s in desc.split("·") if s.strip()]
        if seg:
            artist = seg[0] if seg[0].lower() != title.lower() else (seg[1] if len(seg) > 1 else None)
    except httpx.HTTPError:
        pass
    raw = f"{artist} {title}".strip() if artist else title
    return TrackQuery(raw=raw, artist=artist, title=title or None, source="spotify")


async def _resolve_og_page(client: httpx.AsyncClient, url: str, source: str) -> TrackQuery:
    page = await client.get(url)
    og = _og_tags(page.text)
    title = _clean(og.get("title", ""))
    if not title:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        title = _clean(unquote(slug).replace("-", " "))
    artist, track = _split_dash(title)
    return TrackQuery(raw=title, artist=artist, title=track, source=source)
