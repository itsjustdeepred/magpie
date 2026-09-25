import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import date

import httpx

from . import __version__
from .resolver import TrackQuery

log = logging.getLogger(__name__)

# MusicBrainz asks clients to identify themselves with a meaningful
# User-Agent: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
USER_AGENT = f"Magpie/{__version__} ( https://github.com/itsjustdeepred/magpie )"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

WS = "https://musicbrainz.org/ws/2"
RETRIES = 4
MAX_DISCOGRAPHY = 500

_throttle = asyncio.Lock()
_last_request = 0.0
_client: httpx.AsyncClient | None = None


class MusicBrainzUnavailable(Exception):
    pass


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True)
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


async def _rate_limit() -> None:
    global _last_request
    async with _throttle:
        wait = 1.1 - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request = time.monotonic()


async def _ws_get(path: str, **params) -> dict:
    """Rate-limited MusicBrainz GET, retrying on 503 (MusicBrainz's "slow down")."""
    params["fmt"] = "json"
    for attempt in range(RETRIES):
        await _rate_limit()
        try:
            r = await _get_client().get(f"{WS}/{path}", params=params)
        except httpx.HTTPError as e:
            log.warning("MusicBrainz %s: %s", path, e)
        else:
            if r.status_code not in (502, 503, 504):
                r.raise_for_status()
                return r.json()
            log.warning("MusicBrainz %s answered %s", path, r.status_code)
        await asyncio.sleep(2 * (attempt + 1))
    raise MusicBrainzUnavailable(path)


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
    library: str | None = None  # Lidarr state: "complete", "missing" or None

    def label(self) -> str:
        kind = f" [{self.rg_type}]" if self.rg_type not in ("", "Album") else ""
        mark = {"complete": "✅ ", "missing": "📥 "}.get(self.library or "", "")
        return f"{mark}{self.artist} – {self.album}{kind}"


async def fetch_cover(rg_mbid: str) -> bytes | None:
    url = f"https://coverartarchive.org/release-group/{rg_mbid}/front-250"
    try:
        r = await _get_client().get(url)
        if r.status_code == 200 and r.content:
            return r.content
    except httpx.HTTPError:
        pass
    return None


async def find_artist(name: str) -> tuple[str, str] | None:
    try:
        data = await _ws_get("artist", query=f'artist:"{_lucene_escape(name)}"', limit=1)
    except (httpx.HTTPError, MusicBrainzUnavailable):
        return None
    artists = data.get("artists", [])
    if artists and int(artists[0].get("score", 0)) >= 95:
        return artists[0].get("name", name), artists[0]["id"]
    return None


async def fetch_discography(artist_mbid: str) -> list[tuple[str, str, str, str]]:
    groups: list[dict] = []
    try:
        while len(groups) < MAX_DISCOGRAPHY:
            data = await _ws_get("release-group", artist=artist_mbid, type="album|ep|single",
                                 limit=100, offset=len(groups))
            page = data.get("release-groups", [])
            groups += page
            if not page or len(groups) >= data.get("release-group-count", 0):
                break
    except (httpx.HTTPError, MusicBrainzUnavailable):
        if not groups:
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
        data = await _ws_get(f"release-group/{rg_mbid}", inc="releases")
        releases = data.get("releases", [])
        official = [x for x in releases if x.get("status") == "Official"]
        releases = official or releases
        if not releases:
            return []
        releases.sort(key=lambda x: x.get("date") or "9999")
        data = await _ws_get(f"release/{releases[0]['id']}", inc="recordings")
    except (httpx.HTTPError, MusicBrainzUnavailable):
        return []
    return [tr.get("title", "?")
            for medium in data.get("media", [])
            for tr in medium.get("tracks", [])]


def _lucene_escape(s: str) -> str:
    return "".join("\\" + c if c in '+-&|!(){}[]^"~*?:\\/' else c for c in s)


def _phrase(s: str) -> str:
    # Quoting also neutralizes words like AND / OR / NOT typed by the user.
    return f'"{_lucene_escape(s)}"'


# A clean match scores ~100 (search) + 30 (album) + age bonus; derivative or
# live takes drop below this, and then a broader search is worth the request.
GOOD_SCORE = 100
# No "NOT secondarytype:*" here: it drops every recording that also appears on
# a compilation, i.e. precisely the original take of any well-known song.
# Compilations are skipped per release group in rank() instead.
ALBUM_FILTER = " AND primarytype:album AND status:official"
# Popular songs have hundreds of score-100 recordings (radio edits, DJ mixes):
# a wide page makes it likely the canonical one is among them.
SEARCH_LIMIT = 100


async def search(query: TrackQuery, limit: int = 4) -> list[Candidate]:
    """Raises MusicBrainzUnavailable when MusicBrainz keeps failing."""
    if query.kind == "album" and query.title:
        return await search_album(query, limit)

    if query.isrc:
        candidates = await _search_filtered_then_broad(
            f"isrc:{_lucene_escape(query.isrc)}", query, limit)
        if candidates:
            return candidates

    if query.artist and query.title:
        base = f"artist:{_phrase(query.artist)} AND recording:{_phrase(query.title)}"
    else:
        # Lowercase and/or/not are plain terms to Lucene, not operators.
        base = " ".join(_lucene_escape(w.lower() if w in ("AND", "OR", "NOT") else w)
                        for w in query.raw.split())
    if not base.strip():
        return []
    return await _search_filtered_then_broad(base, query, limit)


async def _search_filtered_then_broad(base: str, query: TrackQuery, limit: int) -> list[Candidate]:
    """Search official albums first; if that only yields weak matches (say, a
    lone remix), widen the search and merge, so the original can still win."""
    filtered = await _search_once(base + ALBUM_FILTER, query, limit)
    if filtered and filtered[0].score >= GOOD_SCORE:
        return filtered
    broad = await _search_once(base, query, limit)
    best: dict[str, Candidate] = {}
    for c in filtered + broad:
        if c.rg_mbid not in best or best[c.rg_mbid].score < c.score:
            best[c.rg_mbid] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:limit]


async def search_album(query: TrackQuery, limit: int = 4) -> list[Candidate]:
    q = f"releasegroup:{_phrase(query.title or query.raw)}"
    if query.artist:
        q += f" AND artist:{_phrase(query.artist)}"
    data = await _ws_get("release-group", query=q, limit=10)
    out: list[Candidate] = []
    for rg in data.get("release-groups", []):
        credits = rg.get("artist-credit") or []
        if not credits or rg.get("secondary-types"):
            continue
        artist = credits[0].get("artist", {})
        rg_type = rg.get("primary-type") or ""
        out.append(Candidate(
            artist=artist.get("name", "?"),
            artist_mbid=artist.get("id", ""),
            track=rg.get("title", "?"),
            album=rg.get("title", "?"),
            rg_mbid=rg.get("id", ""),
            rg_type=rg_type,
            score=int(rg.get("score", 0)) + TYPE_BONUS.get(rg_type, 0),
        ))
    out.sort(key=lambda c: c.score, reverse=True)
    return out[:limit]


async def _search_once(q: str, query: TrackQuery, limit: int) -> list[Candidate]:
    data = await _ws_get("recording", query=q, limit=SEARCH_LIMIT)
    return rank(data, query, limit)


LIVE_RE = re.compile(r"\blive\b")
DERIVATIVE = ("cover", "tribute", "karaoke", "instrumental", "remix", "mix",
              "teaser", "demo", "made famous", "in the style of")


def rank(data: dict, query: TrackQuery, limit: int) -> list[Candidate]:
    """Score recording-search results, keeping the best one per release group."""
    wanted = (query.raw or "").lower()
    exact = (query.title or "").lower()
    # Older releases get a bonus, so the original album wins over later reissues.
    this_year = date.today().year

    seen: dict[str, Candidate] = {}
    for rec in data.get("recordings", []):
        credits = rec.get("artist-credit") or []
        if not credits:
            continue
        artist = credits[0].get("artist", {})
        rec_title = rec.get("title", "?")
        penalty = sum(
            40 for w in DERIVATIVE
            if w in rec_title.lower() and w not in wanted
        )
        # Live takes are often only marked in the disambiguation, and "live"
        # must match as a word ("Alive", "Deliver" are fine).
        details = f"{rec_title} {rec.get('disambiguation', '')}".lower()
        if LIVE_RE.search(details) and not LIVE_RE.search(wanted):
            penalty += 40
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
            rel_date = rel.get("date") or ""
            if len(rel_date) >= 4 and rel_date[:4].isdigit():
                year_bonus = max(0, this_year + 4 - int(rel_date[:4])) // 2
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
