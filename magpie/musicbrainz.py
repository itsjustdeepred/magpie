
import asyncio
import time
from dataclasses import dataclass

import httpx

from .resolver import USER_AGENT, TrackQuery

HEADERS = {"User-Agent": USER_AGENT}

API = "https://musicbrainz.org/ws/2/recording"

_throttle = asyncio.Lock()
_last_request = 0.0


async def _rate_limit() -> None:
    global _last_request
    async with _throttle:
        wait = 1.1 - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request = time.monotonic()

TYPE_BONUS = {"Album": 30, "EP": 15, "Single": 5}


@dataclass
class Candidate:
    artist: str
    artist_mbid: str
    track: str
    album: str
    rg_mbid: str
    rg_type: str
    score: int

    def label(self) -> str:
        kind = f" [{self.rg_type}]" if self.rg_type not in ("", "Album") else ""
        return f"{self.artist} – {self.album}{kind}"


async def fetch_cover(rg_mbid: str) -> bytes | None:
    url = f"https://coverartarchive.org/release-group/{rg_mbid}/front-250"
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS,
                                     follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                return r.content
    except httpx.HTTPError:
        pass
    return None


async def find_artist(name: str) -> tuple[str, str] | None:
    try:
        await _rate_limit()
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(
                "https://musicbrainz.org/ws/2/artist",
                params={"query": f'artist:"{_lucene_escape(name)}"',
                        "fmt": "json", "limit": 1},
            )
            r.raise_for_status()
            artists = r.json().get("artists", [])
    except httpx.HTTPError:
        return None
    if artists and int(artists[0].get("score", 0)) >= 95:
        return artists[0].get("name", name), artists[0]["id"]
    return None


async def fetch_discography(artist_mbid: str) -> list[tuple[str, str, str, str]]:
    try:
        await _rate_limit()
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(
                "https://musicbrainz.org/ws/2/release-group",
                params={"artist": artist_mbid, "fmt": "json", "limit": 100},
            )
            r.raise_for_status()
            groups = r.json().get("release-groups", [])
    except httpx.HTTPError:
        return []
    items = [
        (rg.get("title", "?"),
         (rg.get("first-release-date") or "")[:4],
         rg.get("primary-type") or "",
         rg.get("id", ""))
        for rg in groups
        if rg.get("primary-type") in ("Album", "EP", "Single")
        and not rg.get("secondary-types")
    ]
    return sorted(items, key=lambda x: x[1] or "9999")


async def fetch_tracklist(rg_mbid: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            await _rate_limit()
            r = await client.get(
                f"https://musicbrainz.org/ws/2/release-group/{rg_mbid}",
                params={"inc": "releases", "fmt": "json"},
            )
            r.raise_for_status()
            releases = r.json().get("releases", [])
            official = [x for x in releases if x.get("status") == "Official"]
            releases = official or releases
            if not releases:
                return []
            releases.sort(key=lambda x: x.get("date") or "9999")

            await _rate_limit()
            r = await client.get(
                f"https://musicbrainz.org/ws/2/release/{releases[0]['id']}",
                params={"inc": "recordings", "fmt": "json"},
            )
            r.raise_for_status()
            return [tr.get("title", "?")
                    for medium in r.json().get("media", [])
                    for tr in medium.get("tracks", [])]
    except httpx.HTTPError:
        return []


def _lucene_escape(s: str) -> str:
    return "".join("\\" + c if c in '+-&|!(){}[]^"~*?:\\/' else c for c in s)


ALBUM_FILTER = " AND primarytype:album AND status:official NOT secondarytype:*"


async def search(query: TrackQuery, limit: int = 4) -> list[Candidate]:
    if query.artist and query.title:
        base = f'artist:"{_lucene_escape(query.artist)}" AND recording:"{_lucene_escape(query.title)}"'
    else:
        base = _lucene_escape(query.raw)

    candidates = await _search_once(base + ALBUM_FILTER, query, limit)
    if not candidates:
        candidates = await _search_once(base, query, limit)
    return candidates


async def _search_once(q: str, query: TrackQuery, limit: int) -> list[Candidate]:
    await _rate_limit()
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        r = await client.get(API, params={"query": q, "fmt": "json", "limit": 25})
        r.raise_for_status()
        data = r.json()

    derivative = ("cover", "tribute", "karaoke", "instrumental", "remix", "mix",
                  "teaser", "demo", "made famous", "in the style of")
    wanted = (query.raw or "").lower()
    exact = (query.title or "").lower()

    seen: dict[str, Candidate] = {}
    for rec in data.get("recordings", []):
        credits = rec.get("artist-credit") or []
        if not credits:
            continue
        artist = credits[0].get("artist", {})
        rec_title = rec.get("title", "?")
        penalty = sum(
            40 for w in derivative
            if w in rec_title.lower() and w not in wanted
        )
        if exact and rec_title.lower() == exact:
            penalty -= 25
        artist_name = artist.get("name", "")
        if not query.artist and len(artist_name) > 2 and artist_name.lower() in wanted:
            penalty -= 50
        for rel in rec.get("releases", []):
            if rel.get("status") not in (None, "Official"):
                continue
            rg = rel.get("release-group") or {}
            rg_id = rg.get("id")
            if not rg_id:
                continue
            rg_type = rg.get("primary-type") or ""
            if rg.get("secondary-types"):
                continue
            year_bonus = 0
            date = rel.get("date") or ""
            if len(date) >= 4 and date[:4].isdigit():
                year_bonus = max(0, 2030 - int(date[:4])) // 2
            score = int(rec.get("score", 0)) + TYPE_BONUS.get(rg_type, 0) + year_bonus - penalty
            if rg_id in seen and seen[rg_id].score >= score:
                continue
            seen[rg_id] = Candidate(
                artist=artist.get("name", "?"),
                artist_mbid=artist.get("id", ""),
                track=rec_title,
                album=rg.get("title", rel.get("title", "?")),
                rg_mbid=rg_id,
                rg_type=rg_type,
                score=score,
            )

    ranked = sorted(seen.values(), key=lambda c: c.score, reverse=True)
    return ranked[:limit]
