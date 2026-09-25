import asyncio

import pytest

from magpie import resolver
from magpie.resolver import _clean, _clean_channel, _meta_tags, _og_query, _split_dash


@pytest.mark.parametrize("raw, expected", [
    ("Daft Punk - One More Time (Official Video)", "Daft Punk - One More Time"),
    ("Artist - Song [HD]", "Artist - Song"),
    ("Artist - Song official music video", "Artist - Song"),
    ("  Artist  -  Song | ", "Artist - Song"),
])
def test_clean(raw, expected):
    assert _clean(raw) == expected


def test_split_dash():
    assert _split_dash("Daft Punk – Around the World") == ("Daft Punk", "Around the World")
    assert _split_dash("no dash here") == (None, None)
    assert _split_dash("a - b - c") == (None, None)
    assert _split_dash("Jay-Z - Song") == ("Jay-Z", "Song")


def test_clean_channel():
    assert _clean_channel("Daft Punk - Topic") == "Daft Punk"
    assert _clean_channel("TaylorSwiftVEVO") == "Taylor Swift"
    assert _clean_channel("Radiohead") == "Radiohead"


def test_meta_tags_attribute_order_and_quotes():
    page = """
      <meta property="og:title" content="Don't Stop Me Now"/>
      <meta content='Queen · Jazz · Song · 1978' property='og:description'>
      <meta name="music:musician_description" content="Queen &amp; friends"/>
    """
    tags = _meta_tags(page)
    assert tags["og:title"] == "Don't Stop Me Now"
    assert tags["og:description"] == "Queen · Jazz · Song · 1978"
    assert tags["music:musician_description"] == "Queen & friends"


def test_og_query_bandcamp():
    q = _og_query({"og:title": "In Rainbows, by Radiohead", "og:type": "album"}, "https://x", "bandcamp")
    assert (q.artist, q.title, q.kind) == ("Radiohead", "In Rainbows", "album")
    q = _og_query({"og:title": "15 Step, by Radiohead", "og:type": "song"}, "https://x", "bandcamp")
    assert (q.artist, q.title, q.kind) == ("Radiohead", "15 Step", "track")


def test_og_query_slug_fallback():
    q = _og_query({}, "https://example.com/music/daft-punk---one-more-time", "link")
    assert q.raw


def test_host_matching_is_not_a_substring_match():
    assert resolver._host_is("open.spotify.com", "open.spotify.com")
    assert resolver._host_is("www.deezer.com", "deezer.com")
    assert not resolver._host_is("evil.example", "open.spotify.com")
    assert not resolver._host_is(resolver._host("http://evil.example/?open.spotify.com"),
                                 "open.spotify.com")
    assert not resolver._host_is("notdeezer.com", "deezer.com")


@pytest.mark.parametrize("url, video_id", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
])
def test_youtube_id(url, video_id):
    assert resolver.YT_ID_RE.search(url).group(1) == video_id


def test_shazam_description():
    m = resolver.SHAZAM_DESC_RE.match(
        "Listen to Stand by Me by Ben E. King. See lyrics and music videos, find...")
    assert m.groups() == ("Stand by Me", "Ben E. King")


@pytest.mark.parametrize("host, public", [
    ("127.0.0.1", False),
    ("10.0.0.5", False),
    ("192.168.1.10", False),
    ("169.254.169.254", False),
    ("::1", False),
    ("", False),
    ("8.8.8.8", True),
])
def test_is_public(host, public):
    assert asyncio.run(resolver._is_public(host)) is public


def test_fetch_refuses_private_addresses():
    async def go():
        async with resolver.httpx.AsyncClient() as client:
            await resolver._fetch(client, "http://127.0.0.1:8686/api")

    with pytest.raises(resolver.UnsafeURL):
        asyncio.run(go())


def test_fetch_refuses_non_http_schemes():
    async def go():
        async with resolver.httpx.AsyncClient() as client:
            await resolver._fetch(client, "file:///etc/passwd")

    with pytest.raises(resolver.UnsafeURL):
        asyncio.run(go())


def test_resolve_plain_text():
    q = asyncio.run(resolver.resolve("Daft Punk - One More Time (Official Video)"))
    assert (q.artist, q.title, q.source, q.kind) == ("Daft Punk", "One More Time", "text", "track")


def test_shazam_id():
    m = resolver.SHAZAM_ID_RE.search("https://www.shazam.com/song/1836226731/loser")
    assert m.group(1) == "1836226731"
    assert resolver.SHAZAM_ID_RE.search("https://www.shazam.com/track/20066955/x").group(1) == "20066955"
