import time

from magpie import bot


def test_format_tracklist_highlights_and_escapes():
    tracks = [f"Track {i}" for i in range(1, 21)] + ["<Target> & Co"]
    out = bot._format_tracklist(tracks, "<target> & co", limit=5)
    lines = out.splitlines()
    assert lines[-2] == "▶️ <b>21. &lt;Target&gt; &amp; Co</b>"
    assert lines[-1] == "… +16"
    assert len(lines) == 6


def test_format_tracklist_without_target():
    assert "<b>" not in bot._format_tracklist(["a", "b"], "")


def test_truncate_cuts_on_line_boundary():
    text = "\n".join(f"<b>line {i}</b>" for i in range(200))
    out = bot._truncate(text, 1024)
    assert len(out) <= 1024
    assert out.endswith("\n…")
    assert out.count("<b>") == out.count("</b>")


def test_pending_evicts_oldest_not_everything(monkeypatch):
    monkeypatch.setattr(bot, "MAX_PENDING", 3)
    bot.PENDING.clear()
    tokens = [bot._store_pending(bot.Pending([], owner=1)) for _ in range(5)]
    assert list(bot.PENDING) == tokens[-3:]


def test_pending_expires():
    bot.PENDING.clear()
    token = bot._store_pending(bot.Pending([], owner=None))
    bot.PENDING[token].created = time.monotonic() - bot.PENDING_TTL - 1
    assert bot._get_pending(token) is None
    assert token not in bot.PENDING


def test_queue_line():
    line = bot._queue_line({
        "artist": {"artistName": "Daft Punk"}, "album": {"title": "Discovery"},
        "size": 200, "sizeleft": 50, "trackedDownloadState": "downloading", "timeleft": "00:05:00",
    })
    assert line == "• Daft Punk – Discovery · 75% · downloading · 00:05:00"
