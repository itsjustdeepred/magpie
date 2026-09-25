import pytest

from magpie import config
from magpie.config import Config, parse_chat_ids


def test_parse_chat_ids():
    assert parse_chat_ids(" 1, -100123 ,,") == {1, -100123}
    with pytest.raises(SystemExit, match="non-numeric"):
        parse_chat_ids("1,abc")


def _env(monkeypatch, **values):
    base = {"TELEGRAM_BOT_TOKEN": "t", "LIDARR_API_KEY": "k"}
    base.update(values)
    for key in ("ADMIN_USER_ID", "ALLOWED_CHAT_IDS", "GROUP_TRIGGER", "NOTIFY_ON_IMPORT",
                "NOTIFY_MAX_DAYS", "NOTIFY_INTERVAL", "LIDARR_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in base.items():
        monkeypatch.setenv(key, value)


def test_invalid_admin_id_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOWED_CHATS_FILE", tmp_path / "chats.json")
    _env(monkeypatch, ADMIN_USER_ID="me")
    with pytest.raises(SystemExit, match="ADMIN_USER_ID"):
        Config.from_env()


def test_admin_is_closed_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOWED_CHATS_FILE", tmp_path / "chats.json")
    _env(monkeypatch)
    cfg = Config.from_env()
    assert not cfg.is_admin(None)
    assert not cfg.is_allowed(1, None)


def test_allow_persists_atomically(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "chats.json"
    monkeypatch.setattr(config, "ALLOWED_CHATS_FILE", path)
    _env(monkeypatch, ALLOWED_CHAT_IDS="5")
    cfg = Config.from_env()
    cfg.allow_chat(-100)
    assert path.read_text() == "[-100, 5]"
    assert not path.with_name("chats.json.tmp").exists()
    assert Config.from_env().allowed_chats == {5, -100}


def test_corrupt_whitelist_is_ignored(monkeypatch, tmp_path):
    path = tmp_path / "chats.json"
    path.write_text("{not json")
    monkeypatch.setattr(config, "ALLOWED_CHATS_FILE", path)
    _env(monkeypatch)
    assert Config.from_env().allowed_chats == set()
