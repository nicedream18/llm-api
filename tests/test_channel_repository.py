from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.domain.entities import ApiKeyEntity, ChannelApiKeyEntity, ChannelEntity
from app.infrastructure.repositories.channel_repo import ChannelRepository


def _repository(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'channels.sqlite'}")

    @event.listens_for(engine, "connect")
    def register_mysql_compatibility_functions(connection, _record):
        connection.create_function("NOW", 0, lambda: datetime.now(UTC).isoformat())

    with engine.begin() as db:
        db.execute(text("""CREATE TABLE channels (
            id TEXT PRIMARY KEY, name TEXT, type TEXT, base_url TEXT, api_key TEXT,
            models TEXT, status INTEGER, priority INTEGER, weight INTEGER, config TEXT,
            model_mapping TEXT, last_test_at TEXT, last_test_ok INTEGER,
            created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE channel_api_keys (
            id TEXT PRIMARY KEY, channel_id TEXT, name TEXT, api_key TEXT, status INTEGER,
            weight INTEGER, last_error TEXT, cooldown_until TEXT, last_used_at TEXT,
            created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE api_keys (
            id TEXT PRIMARY KEY, name TEXT, `key` TEXT, status INTEGER, allowed_models TEXT,
            allowed_channels TEXT, quota_limit INTEGER, quota_used INTEGER, expires_at TEXT,
            created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE request_logs (
            id TEXT PRIMARY KEY, channel_id TEXT, api_key_id TEXT, status_code INTEGER,
            total_tokens INTEGER, duration_ms INTEGER
        )"""))
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def get_db():
        session = sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("app.infrastructure.repositories.channel_repo.get_db", get_db)
    return ChannelRepository(), engine


def test_channel_api_key_and_downstream_key_repository_lifecycle(monkeypatch, tmp_path):
    repo, engine = _repository(monkeypatch, tmp_path)
    channel = repo.create_channel(ChannelEntity(
        name="Primary", type="openai", base_url="https://upstream.example/v1",
        api_key="primary-secret", models=["model-a"], priority=5, weight=2,
        config={"organization": "org"}, model_mapping={"public": "model-a"},
        api_keys=[ChannelApiKeyEntity(name="extra", api_key="extra-secret", weight=3)],
    ))
    assert channel.id and channel.created_at and channel.updated_at
    fetched = repo.get_channel(channel.id)
    assert fetched is not None
    assert fetched.models == ["model-a"] and fetched.config == {"organization": "org"}
    assert fetched.model_mapping == {"public": "model-a"}
    assert [key.api_key for key in fetched.api_keys] == ["extra-secret"]
    assert repo.get_channel("missing") is None
    assert [item.id for item in repo.get_all_channels()] == [channel.id]
    assert [item.id for item in repo.get_enabled_channels()] == [channel.id]

    fetched.name = "Updated"
    fetched.status = 0
    fetched.api_keys = [ChannelApiKeyEntity(name="rotated", api_key="rotated-secret", weight=8)]
    assert repo.update_channel(fetched) is True
    assert repo.update_channel(ChannelEntity(id="missing")) is False
    assert repo.get_channel(channel.id).name == "Updated"
    assert repo.get_channel(channel.id).api_keys[0].name == "rotated"
    assert repo.get_enabled_channels() == []
    assert repo.toggle_channel_status(channel.id, 1) is True
    assert repo.update_test_result(channel.id, True) is True
    assert repo.get_channel(channel.id).last_test_ok == 1

    extra = repo.create_channel_api_key(ChannelApiKeyEntity(
        channel_id=channel.id, name="second", api_key="second-secret", weight=4,
    ))
    assert extra.id and extra.created_at and extra.updated_at
    listed_keys = repo.get_channel_api_keys(channel.id)
    assert {item.name for item in listed_keys} == {"rotated", "second"}
    extra.name = "second-updated"
    extra.status = 0
    assert repo.update_channel_api_key(extra) is True
    assert repo.update_channel_api_key(ChannelApiKeyEntity(id="missing", channel_id=channel.id)) is False
    assert repo.update_channel_api_key_result(extra.id, False, "rate limited", "later") is True
    assert repo.update_channel_api_key_result("missing", True) is False
    updated_key = next(item for item in repo.get_channel_api_keys(channel.id) if item.id == extra.id)
    assert updated_key.last_error == "rate limited" and updated_key.cooldown_until == "later"
    assert repo.delete_channel_api_key(channel.id, extra.id) is True
    assert repo.delete_channel_api_key(channel.id, extra.id) is False

    downstream = repo.create_api_key(ApiKeyEntity(
        name="client", key="client-secret", allowed_models=["model-a"],
        allowed_channels=[channel.id], quota_limit=500,
    ))
    assert downstream.id and downstream.created_at and downstream.updated_at
    with engine.begin() as db:
        db.execute(text("""INSERT INTO api_keys
            (id, name, `key`, status, allowed_models, allowed_channels, quota_limit, quota_used, created_at, updated_at)
            VALUES ('key-2', 'disabled client', 'disabled', 0, '[]', '[]', 0, 0, 'a', 'a')"""))
    assert repo.get_api_key(downstream.id).allowed_models == ["model-a"]
    assert repo.get_api_key("missing") is None
    assert repo.get_api_key_by_key("client-secret").id == downstream.id
    assert repo.get_api_key_by_key("disabled") is None
    assert {item.id for item in repo.get_all_api_keys()} == {downstream.id, "key-2"}
    downstream.name = "client-updated"
    assert repo.update_api_key(downstream) is True
    assert repo.update_api_key(ApiKeyEntity(id="missing")) is False
    assert repo.increment_quota_used(downstream.id, 15) is True
    downstream.quota_used = 0
    assert repo.update_api_key(downstream) is True
    assert repo.get_api_key(downstream.id).quota_used == 15
    assert repo.delete_api_key(downstream.id) is True
    assert repo.delete_api_key(downstream.id) is False

    repo.create_channel(ChannelEntity(id="fallback", name="Fallback", status=1))
    with engine.begin() as db:
        db.execute(text("""INSERT INTO request_logs VALUES
            ('log-1', :channel_id, 'key-2', 200, 20, 30),
            ('log-2', :channel_id, 'key-2', 503, 4, 50)"""), {"channel_id": channel.id})
    channel_stats = {item.channel_id: item for item in repo.get_channel_stats()}
    assert channel_stats[channel.id].total_calls == 2
    assert channel_stats[channel.id].success_calls == 1
    assert channel_stats[channel.id].failed_calls == 1
    assert channel_stats[channel.id].total_tokens == 24
    assert channel_stats["fallback"].total_calls == 0
    key_stats = repo.get_api_key_stats()[0]
    assert (key_stats.api_key_id, key_stats.total_calls, key_stats.failed_calls) == ("key-2", 2, 1)

    assert repo.delete_channel_api_key(channel.id, "missing") is False
    assert repo.delete_channel(channel.id) is True
    assert repo.delete_channel(channel.id) is False
    engine.dispose()
