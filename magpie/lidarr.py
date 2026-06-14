import asyncio
import logging

import httpx

log = logging.getLogger(__name__)


class LidarrError(Exception):
    pass


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

    async def _get(self, path: str, **params) -> dict | list:
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def _send(self, method: str, path: str, payload: dict) -> dict:
        r = await self._client.request(method, path, json=payload)
        if r.status_code >= 400:
            raise LidarrError(f"Lidarr {r.status_code} on {path}: {r.text[:300]}")
        return r.json()

    async def status(self) -> dict:
        return await self._get("/system/status")

    async def _get_defaults(self) -> dict:
        if self._defaults is None:
            roots = await self._get("/rootfolder")
            quals = await self._get("/qualityprofile")
            metas = await self._get("/metadataprofile")
            if not roots:
                raise LidarrError("No root folder configured in Lidarr")

            def pick(items: list, name: str | None, key: str) -> dict:
                if name:
                    for it in items:
                        if it.get(key, "").lower() == name.lower():
                            return it
                    raise LidarrError(f"'{name}' not found among {[i.get(key) for i in items]}")
                return items[0]

            self._defaults = {
                "root": pick(roots, self._root_folder_name, "path")["path"],
                "quality": pick(quals, self._quality_name, "name")["id"],
                "metadata": pick(metas, self._metadata_name, "name")["id"],
            }
        return self._defaults

    async def add_and_search(self, rg_mbid: str) -> tuple[str, str]:
        results = await self._get("/album/lookup", term=f"lidarr:{rg_mbid}")
        if not results:
            raise LidarrError("Album not found in Lidarr's metadata database")
        album = results[0]
        title = f"{album['artist']['artistName']} – {album['title']}"

        if album.get("id"):
            if not album.get("monitored"):
                album["monitored"] = True
                await self._send("PUT", f"/album/{album['id']}", album)
            await self._send("POST", "/command",
                             {"name": "AlbumSearch", "albumIds": [album["id"]]})
            return "exists", title

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

        await self._wait_for_refresh()

        fresh = await self._get(f"/album/{album_id}")
        if not fresh.get("monitored"):
            fresh["monitored"] = True
            await self._send("PUT", f"/album/{album_id}", fresh)

        await self._send("POST", "/command",
                         {"name": "AlbumSearch", "albumIds": [album_id]})
        return "added", title

    async def add_artist_and_search(self, artist_mbid: str) -> tuple[str, str]:
        results = await self._get("/artist/lookup", term=f"lidarr:{artist_mbid}")
        if not results:
            raise LidarrError("Artist not found in Lidarr's metadata database")
        artist = results[0]
        name = artist.get("artistName", "?")

        if artist.get("id"):
            artist["monitored"] = True
            await self._send("PUT", f"/artist/{artist['id']}", artist)
            albums = await self._get("/album", artistId=artist["id"])
            ids = [a["id"] for a in albums]
            if ids:
                await self._send("PUT", "/album/monitor",
                                 {"albumIds": ids, "monitored": True})
            await self._send("POST", "/command",
                             {"name": "ArtistSearch", "artistId": artist["id"]})
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

    async def _wait_for_refresh(self, timeout: float = 90) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            commands = await self._get("/command")
            busy = [c for c in commands
                    if c.get("name") in ("RefreshArtist", "RefreshAlbum")
                    and c.get("status") in ("queued", "started")]
            if not busy:
                return
            await asyncio.sleep(2)
        log.warning("Refresh still running after %ss, searching anyway", timeout)
