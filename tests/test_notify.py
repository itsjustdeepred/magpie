import asyncio

from magpie import notify


class FakeLidarr:
    def __init__(self, albums):
        self._albums = albums

    async def albums(self, ids):
        return [a for a in self._albums if a["id"] in ids]


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_parameters=None):
        self.sent.append((chat_id, text))


def test_watcher_notifies_once_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(notify, "WATCHES_FILE", tmp_path / "watches.json")
    albums = [
        {"id": 1, "statistics": {"trackCount": 2, "trackFileCount": 2}},
        {"id": 2, "statistics": {"trackCount": 2, "trackFileCount": 0}},
    ]
    bot = FakeBot()
    watcher = notify.ImportWatcher(FakeLidarr(albums), bot, interval=60, max_days=7)
    watcher.add(1, 100, "A – Done", reply_to=5)
    watcher.add(2, 100, "A – Pending", reply_to=None)

    asyncio.run(watcher.check())
    assert len(bot.sent) == 1 and "Done" in bot.sent[0][1]
    assert len(watcher) == 1

    reloaded = notify.ImportWatcher(FakeLidarr(albums), bot, interval=60, max_days=7)
    assert len(reloaded) == 1


def test_watcher_gives_up_after_max_days(monkeypatch, tmp_path):
    monkeypatch.setattr(notify, "WATCHES_FILE", tmp_path / "watches.json")
    albums = [{"id": 3, "statistics": {"trackCount": 10, "trackFileCount": 4}}]
    bot = FakeBot()
    watcher = notify.ImportWatcher(FakeLidarr(albums), bot, interval=60, max_days=1)
    watcher.add(3, 100, "A – Slow", reply_to=None)
    watcher._watches["3:100"]["since"] -= 2 * 86400
    asyncio.run(watcher.check())
    assert "4/10" in bot.sent[0][1]
    assert len(watcher) == 0
