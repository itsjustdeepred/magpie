from magpie.musicbrainz import Candidate, rank
from magpie.resolver import TrackQuery


def _rec(title, artist, score, releases):
    return {
        "title": title, "score": score,
        "artist-credit": [{"artist": {"name": artist, "id": f"id-{artist}"}}],
        "releases": releases,
    }


def _rel(rg_id, rg_title, kind="Album", date="2001", status="Official", secondary=None):
    rg = {"id": rg_id, "title": rg_title, "primary-type": kind}
    if secondary:
        rg["secondary-types"] = secondary
    return {"status": status, "date": date, "release-group": rg}


def test_rank_prefers_original_album_over_derivatives_and_compilations():
    data = {"recordings": [
        _rec("One More Time", "Daft Punk", 100, [
            _rel("rg-disc", "Discovery", date="2001"),
            _rel("rg-comp", "Hits", secondary=["Compilation"]),
            _rel("rg-single", "One More Time", kind="Single", date="2000"),
        ]),
        _rec("One More Time (karaoke version)", "Karaoke Band", 100, [_rel("rg-kar", "Karaoke")]),
    ]}
    q = TrackQuery(raw="Daft Punk One More Time", artist="Daft Punk", title="One More Time")
    ranked = rank(data, q, 4)
    ids = [c.rg_mbid for c in ranked]
    assert ids[0] == "rg-disc"
    assert "rg-comp" not in ids
    assert ids.index("rg-kar") > ids.index("rg-single")


def test_rank_dedupes_release_groups_and_skips_bootlegs():
    data = {"recordings": [
        _rec("Song", "A", 90, [_rel("rg1", "Album", date="2010"), _rel("rg1", "Album", date="2012")]),
        _rec("Song", "A", 90, [_rel("rg2", "Boot", status="Bootleg")]),
    ]}
    ranked = rank(data, TrackQuery(raw="A Song", artist="A", title="Song"), 4)
    assert [c.rg_mbid for c in ranked] == ["rg1"]


def test_label_marks_library_state():
    c = Candidate("A", "a", "t", "Album", "rg", "EP", 0)
    assert c.label() == "A – Album [EP]"
    c.library = "complete"
    assert c.label().startswith("✅ ")
    c.library = "missing"
    assert c.label().startswith("📥 ")


def test_rank_penalizes_live_takes_marked_only_in_disambiguation():
    live = _rec("Back in Black", "AC/DC", 100, [_rel("rg-live", "Stiff Upper Lip", date="2000")])
    live["disambiguation"] = "live, 1996-07-10: Madrid"
    studio = _rec("Back in Black", "AC/DC", 95, [_rel("rg-studio", "Back in Black", date="1980")])
    alive = _rec("Alive", "Pearl Jam", 100, [_rel("rg-ten", "Ten", date="1991")])
    q = TrackQuery(raw="AC/DC Back in Black", artist="AC/DC", title="Back in Black")
    assert rank({"recordings": [live, studio]}, q, 4)[0].rg_mbid == "rg-studio"
    # "Alive" is not a live take
    assert rank({"recordings": [alive]}, TrackQuery(raw="Alive"), 4)[0].score > 100
    # ...and live is fine when the user asked for it
    q_live = TrackQuery(raw="AC/DC Back in Black live", artist="AC/DC", title="Back in Black live")
    assert rank({"recordings": [live]}, q_live, 4)[0].score > 100


def test_weak_filtered_results_trigger_a_broad_search(monkeypatch):
    from magpie import musicbrainz

    remix = Candidate("TeeVex", "t", "One More Time (TeeVex remix)", "Y2K", "rg-remix", "Album", 56)
    original = Candidate("Daft Punk", "d", "One More Time", "Discovery", "rg-disc", "Album", 160)
    calls = []

    async def fake_search_once(q, query, limit):
        calls.append(q)
        return [remix] if q.endswith(musicbrainz.ALBUM_FILTER) else [original, remix]

    monkeypatch.setattr(musicbrainz, "_search_once", fake_search_once)
    q = TrackQuery(raw="Daft Punk One More Time", artist="Daft Punk", title="One More Time")
    import asyncio
    result = asyncio.run(musicbrainz.search(q))
    assert [c.rg_mbid for c in result] == ["rg-disc", "rg-remix"]
    assert len(calls) == 2
