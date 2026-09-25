import asyncio
import json

import httpx
import pytest

from magpie.lidarr import Lidarr, LidarrError, is_complete


def make(handler) -> Lidarr:
    lidarr = Lidarr("http://lidarr", "key")
    lidarr._client = httpx.AsyncClient(base_url="http://lidarr/api/v1",
                                       transport=httpx.MockTransport(handler))
    return lidarr


def test_http_errors_become_lidarr_errors():
    lidarr = make(lambda req: httpx.Response(401))
    with pytest.raises(LidarrError, match="LIDARR_API_KEY"):
        asyncio.run(lidarr.status())

    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(LidarrError, match="unreachable"):
        asyncio.run(make(boom).status())


def test_empty_body_is_accepted():
    lidarr = make(lambda req: httpx.Response(202))
    assert asyncio.run(lidarr._send("PUT", "/album/monitor", {})) == {}


def test_is_complete():
    assert is_complete({"statistics": {"trackCount": 10, "trackFileCount": 10}})
    assert not is_complete({"statistics": {"trackCount": 10, "trackFileCount": 3}})
    assert not is_complete({"statistics": {"trackCount": 0, "trackFileCount": 0}})
    assert not is_complete({})


def test_existing_album_is_updated_from_stored_resource():
    calls = []
    stored = {"id": 7, "title": "Discovery", "monitored": False, "anyField": "keep",
              "statistics": {"trackCount": 14, "trackFileCount": 0}}

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path.endswith("/album/lookup"):
            return httpx.Response(200, json=[{"id": 7, "title": "Discovery",
                                              "artist": {"artistName": "Daft Punk"}}])
        if req.url.path.endswith("/album/7") and req.method == "GET":
            return httpx.Response(200, json=stored)
        return httpx.Response(200, json={})

    status, title, album_id = asyncio.run(make(handler).add_and_search("rg"))
    assert (status, title, album_id) == ("exists", "Daft Punk – Discovery", 7)
    put = next(c for c in calls if c[0] == "PUT")
    assert put[2]["anyField"] == "keep" and put[2]["monitored"] is True
    assert calls[-1][2] == {"name": "AlbumSearch", "albumIds": [7]}


def test_complete_album_is_not_searched_again():
    def handler(req: httpx.Request):
        if req.url.path.endswith("/album/lookup"):
            return httpx.Response(200, json=[{"id": 7, "title": "D", "artist": {"artistName": "A"}}])
        if req.method == "GET":
            return httpx.Response(200, json={"id": 7, "monitored": True,
                                             "statistics": {"trackCount": 2, "trackFileCount": 2}})
        raise AssertionError(f"unexpected {req.method} {req.url}")

    assert asyncio.run(make(handler).add_and_search("rg"))[0] == "complete"


def test_wait_for_refresh_ignores_other_artists(monkeypatch):
    async def fast_sleep(_):
        return None

    monkeypatch.setattr("magpie.lidarr.asyncio.sleep", fast_sleep)
    commands = [
        {"name": "RefreshArtist", "status": "started", "body": {"artistIds": []}},
        {"name": "RefreshArtist", "status": "started", "body": {"artistId": 99}},
    ]
    lidarr = make(lambda req: httpx.Response(200, json=commands))
    asyncio.run(lidarr._wait_for_refresh(5, timeout=5))  # returns at once


def test_pick_unknown_profile_is_reported():
    def handler(req: httpx.Request):
        return httpx.Response(200, json={
            "/api/v1/rootfolder": [{"path": "/music"}],
            "/api/v1/qualityprofile": [{"id": 1, "name": "Any"}],
            "/api/v1/metadataprofile": [{"id": 1, "name": "Standard"}],
        }[req.url.path])

    lidarr = Lidarr("http://lidarr", "key", quality_profile="Lossless")
    lidarr._client = httpx.AsyncClient(base_url="http://lidarr/api/v1",
                                       transport=httpx.MockTransport(handler))
    with pytest.raises(LidarrError, match="Lossless"):
        asyncio.run(lidarr.validate())
