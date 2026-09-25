import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

# Timeout for the quick library lookups done while building a prompt: a slow
# Lidarr must not hold up the reply.
QUICK_TIMEOUT = 5


class LidarrError(Exception):
    pass


def is_complete(album: dict) -> bool:
    stats = album.get("statistics") or {}
    total = stats.get("trackCount") or stats.get("totalTrackCount") or 0
    return total > 0 and stats.get("trackFileCount", 0) >= total


def _targets_artist(command: dict, artist_id: int) -> bool:
    body = command.get("body") or {}
    return body.get("artistId") == artist_id or artist_id in (body.get("artistIds") or [])


class Lidarr:
    def __init__(self, url: str, api_key: str,
                 root_folder: str | None = None,
                 quality_profile: str | None = None,
                 metadata_profile: str | None = None):
        self._client = httpx.AsyncClient(
            base_url=f"{url}/api/v1",
            headers={"X-Api-Key": api_key},
            timeout=60,
        )
        self._root_folder_name = root_folder
        self._quality_name = quality_profile
        self._metadata_name = metadata_profile
        self._defaults: dict | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       payload: dict | None = None,
                       timeout: float | None = None) -> dict | list:
        try:
            r = await self._client.request(
                method, path, params=params, json=payload,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.TimeoutException:
            raise LidarrError(f"timed out on {path}") from None
        except httpx.HTTPError as e:
            raise LidarrError(f"unreachable ({e.__class__.__name__}: {e})") from None
        if r.status_code == 401:
            raise LidarrError("401 Unauthorized, check LIDARR_API_KEY")
        if r.status_code >= 400:
            raise LidarrError(f"{r.status_code} on {path}: {r.text[:300]}")
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            raise LidarrError(f"non-JSON response on {path}") from None

    async def _get(self, path: str, timeout: float | None = None, **params) -> dict | list:
        return await self._request("GET", path, params=params, timeout=timeout)

    async def _send(self, method: str, path: str, payload: dict) -> dict:
        return await self._request(method, path, payload=payload)

    async def status(self) -> dict:
        return await self._get("/system/status")

    async def health(self) -> list[dict]:
        return await self._get("/health")

    async def queue(self, size: int = 15) -> dict:
        return await self._get("/queue", page=1, pageSize=size,
                               includeArtist="true", includeAlbum="true")

    async def albums(self, album_ids: list[int]) -> list[dict]:
        if not album_ids:
            return []
        return await self._get("/album", albumIds=album_ids)

    async def album_state(self, rg_mbid: str) -> str | None:
        """'complete', 'missing' (in Lidarr, files missing) or None (not in Lidarr)."""
        albums = await self._get("/album", timeout=QUICK_TIMEOUT, foreignAlbumId=rg_mbid)
        if not albums:
            return None
        return "complete" if is_complete(albums[0]) else "missing"

    async def validate(self) -> dict:
        """Resolve root folder and profiles now, so a typo shows up at startup."""
        return await self._get_defaults()

    async def _get_defaults(self) -> dict:
        if self._defaults is None:
            roots = await self._get("/rootfolder")
            quals = await self._get("/qualityprofile")
            metas = await self._get("/metadataprofile")
            if not roots:
                raise LidarrError("No root folder configured in Lidarr")
            if not quals or not metas:
                raise LidarrError("No quality or metadata profile configured in Lidarr")

            def pick(items: list, name: str | None, key: str) -> dict:
                if name:
                    for it in items:
                        if (it.get(key) or "").lower() == name.lower():
                            return it
                    raise LidarrError(f"'{name}' not found among {[i.get(key) for i in items]}")
                return items[0]

            self._defaults = {
                "root": pick(roots, self._root_folder_name, "path")["path"],
                "quality": pick(quals, self._quality_name, "name")["id"],
                "metadata": pick(metas, self._metadata_name, "name")["id"],
            }
        return self._defaults

    async def _search_album(self, album_id: int) -> None:
        await self._send("POST", "/command", {"name": "AlbumSearch", "albumIds": [album_id]})

    async def add_and_search(self, rg_mbid: str) -> tuple[str, str, int]:
        """Returns (status, title, album_id); status is 'added', 'exists' or 'complete'."""
        results = await self._get("/album/lookup", term=f"lidarr:{rg_mbid}")
        if not results:
            raise LidarrError("Album not found in Lidarr's metadata database")
        album = results[0]
        title = f"{album['artist']['artistName']} – {album['title']}"

        if album.get("id"):
            album_id = album["id"]
            # Update from the stored resource: a lookup result is not a
            # complete album and PUTting it back could clobber fields.
            stored = await self._get(f"/album/{album_id}")
            if is_complete(stored):
                return "complete", title, album_id
            if not stored.get("monitored"):
                stored["monitored"] = True
                await self._send("PUT", f"/album/{album_id}", stored)
            await self._search_album(album_id)
            return "exists", title, album_id

        d = await self._get_defaults()
        album["monitored"] = True
        artist = album["artist"]
        artist["rootFolderPath"] = d["root"]
        artist["qualityProfileId"] = d["quality"]
        artist["metadataProfileId"] = d["metadata"]
        artist.setdefault("addOptions", {
            "monitor": "unknown",
            "albumsToMonitor": [rg_mbid],
            "searchForMissingAlbums": False,
        })

        added = await self._send("POST", "/album", album)
        album_id = added.get("id")
        if not album_id:
            raise LidarrError("Lidarr did not return the id of the added album")
        log.info("Added album %s (id=%s)", title, album_id)

        await self._wait_for_refresh(added.get("artistId"))

        fresh = await self._get(f"/album/{album_id}")
        if not fresh.get("monitored"):
            fresh["monitored"] = True
            await self._send("PUT", f"/album/{album_id}", fresh)

        await self._search_album(album_id)
        return "added", title, album_id

    async def add_artist_and_search(self, artist_mbid: str) -> tuple[str, str]:
        results = await self._get("/artist/lookup", term=f"lidarr:{artist_mbid}")
        if not results:
            raise LidarrError("Artist not found in Lidarr's metadata database")
        artist = results[0]
        name = artist.get("artistName", "?")

        if artist.get("id"):
            artist_id = artist["id"]
            stored = await self._get(f"/artist/{artist_id}")
            if not stored.get("monitored"):
                stored["monitored"] = True
                await self._send("PUT", f"/artist/{artist_id}", stored)
            albums = await self._get("/album", artistId=artist_id)
            ids = [a["id"] for a in albums if not a.get("monitored")]
            if ids:
                await self._send("PUT", "/album/monitor", {"albumIds": ids, "monitored": True})
            await self._send("POST", "/command", {"name": "ArtistSearch", "artistId": artist_id})
            return "artist_exists", name

        d = await self._get_defaults()
        artist["monitored"] = True
        artist["rootFolderPath"] = d["root"]
        artist["qualityProfileId"] = d["quality"]
        artist["metadataProfileId"] = d["metadata"]
        artist["addOptions"] = {"monitor": "all", "searchForMissingAlbums": True}
        added = await self._send("POST", "/artist", artist)
        log.info("Added artist %s (id=%s)", name, added.get("id"))
        return "artist_added", name

    async def _wait_for_refresh(self, artist_id: int | None, timeout: float = 90) -> None:
        """Wait for the refresh Lidarr runs on a newly added artist.

        Only commands targeting that artist count: a library-wide scheduled
        refresh would otherwise make every add wait for the full timeout.
        """
        if artist_id is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        await asyncio.sleep(1)  # give Lidarr a moment to queue the refresh
        while loop.time() < deadline:
            commands = await self._get("/command")
            busy = [c for c in commands
                    if c.get("name") in ("RefreshArtist", "RefreshAlbum")
                    and c.get("status") in ("queued", "started")
                    and _targets_artist(c, artist_id)]
            if not busy:
                return
            await asyncio.sleep(2)
        log.warning("Refresh still running after %ss, searching anyway", timeout)
