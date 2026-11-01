from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.entities import RequestLogEntity
from app.infrastructure.repositories.log_repo import LogRepository


def _database(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE channels (id TEXT PRIMARY KEY, status INTEGER)"))
        db.execute(text("CREATE TABLE api_keys (id TEXT PRIMARY KEY, status INTEGER)"))
        db.execute(text("""CREATE TABLE request_logs (
            id TEXT PRIMARY KEY, seq INTEGER, api_key_id TEXT, api_key_name TEXT,
            channel_id TEXT, channel_name TEXT, model TEXT, upstream_model TEXT,
            mode TEXT, protocol_type TEXT, is_stream INTEGER, is_retry INTEGER,
            status_code INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER,
            total_tokens INTEGER, duration_ms INTEGER, request_id TEXT, endpoint TEXT,
            attempt_count INTEGER, final_attempt INTEGER, stream_status TEXT,
            usage_source TEXT, client_disconnect INTEGER, truncated INTEGER,
            risk_level TEXT, risk_score INTEGER, risk_summary TEXT, security_action TEXT,
            sanitized INTEGER, blocked_reason TEXT, client_ip TEXT, error_message TEXT,
            request_body TEXT, response_choices TEXT, trace_id TEXT, created_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE gateway_attempts (
            id TEXT PRIMARY KEY, request_id TEXT, attempt_no INTEGER, channel_id TEXT,
            channel_name TEXT, status_code INTEGER, error_type TEXT, error_message TEXT,
            duration_ms INTEGER, succeeded INTEGER, created_at TEXT
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

    monkeypatch.setattr("app.infrastructure.repositories.log_repo.get_db", get_db)
    return engine


def test_log_repository_persistence_filters_aggregates_and_cleanup(monkeypatch):
    engine = _database(monkeypatch)
    repo = LogRepository()
    now = datetime.now(UTC)
    older = (now - timedelta(days=2)).isoformat()
    newer = (now - timedelta(days=1)).isoformat()
    with engine.begin() as db:
        db.execute(text("INSERT INTO channels VALUES ('channel-a', 1), ('channel-b', 0)"))
        db.execute(text("INSERT INTO api_keys VALUES ('key-a', 1), ('key-b', 0)"))

    repo.insert_log(RequestLogEntity(
        id="log-a", api_key_id="key-a", api_key_name="client-a", channel_id="channel-a",
        channel_name="Primary", model="model-a", upstream_model="upstream-a", mode="chat",
        protocol_type="openai", stream=True, retry=True, status_code=200,
        prompt_tokens=10, completion_tokens=5, total_tokens=15, duration_ms=25,
        risk_level="Clean", risk_score=0, security_action="Allow", sanitized=True,
        client_ip="127.0.0.1", request_body="{}", response_choices='{"ok":true}',
        trace_id="trace-a", created_at=older, seq=1, request_id="request-a",
        endpoint="/v1/chat/completions", attempt_count=2, final_attempt=2,
        stream_status="completed", usage_source="upstream", client_disconnect=False,
        truncated=False,
    ))
    repo.insert_log(RequestLogEntity(
        id="log-b", api_key_id="key-b", api_key_name="client-b", channel_id="channel-b",
        channel_name="Fallback", model="model-b", mode="chat", protocol_type="openai",
        status_code=503, prompt_tokens=3, completion_tokens=0, total_tokens=3,
        duration_ms=50, risk_level="High", risk_score=80, security_action="Block",
        error_message="upstream failed", trace_id="trace-b", created_at=newer,
        seq=2, request_id="request-b", endpoint="/v1/responses",
    ))
    repo.insert_attempt("request-a", SimpleNamespace(
        attempt_no=1, channel_id="channel-a", channel_name="Primary", status_code=503,
        error_type="upstream_error", error_message="retryable", duration_ms=5,
        succeeded=False,
    ))

    found = repo.get_log_by_id("log-a")
    assert found is not None
    assert (found.request_id, found.endpoint, found.attempt_count, found.final_attempt) == (
        "request-a", "/v1/chat/completions", 2, 2,
    )
    assert found.stream is True and found.retry is True and found.sanitized is True
    assert repo.get_log_by_id("missing") is None
    assert [row.id for row in repo.query_logs(0, 10, api_key_id="key-a", channel_id="channel-a", model="model-a", risk_level="Clean", start_time=older, end_time=newer)] == ["log-a"]
    assert [row.id for row in repo.search_logs(0, 10, keyword="failed", api_key_name="client-b", channel_name="Fallback", model="model-b", date_from=newer, date_to=newer, trace_id="trace-b")] == ["log-b"]
    assert [row.id for row in repo.search_logs(0, 10, trace_id="trace-a")] == ["log-a"]

    stats = repo.get_dashboard_stats()
    assert (stats.total_requests, stats.total_tokens, stats.total_errors) == (2, 18, 1)
    assert (stats.active_channels, stats.active_api_keys) == (1, 1)
    model_stats = {row["model"]: row for row in repo.model_stats()}
    assert model_stats == {
        "model-a": {"model": "model-a", "requests": 1, "total_tokens": 15, "errors": 0},
        "model-b": {"model": "model-b", "requests": 1, "total_tokens": 3, "errors": 1},
    }
    assert repo.token_trend(0)[0]["total_tokens"] == 3
    assert sum(row["total_tokens"] for row in repo.token_trend(30)) == 18
    assert repo.token_trend(1000)[0]["day"] == newer[:10]
    assert len(repo.route_flow()) == 2
    options = repo.filter_options()
    assert options["models"] == ["model-a", "model-b"]
    assert options["channels"] == [
        {"channel_id": "channel-b", "channel_name": "Fallback"},
        {"channel_id": "channel-a", "channel_name": "Primary"},
    ]
    assert options["risk_levels"] == ["Clean", "High"]
    assert repo.attempts("request-a")[0]["succeeded"] == 0

    assert repo.delete_before(newer) == 1
    repo.clear_stats()
    with engine.connect() as db:
        assert db.execute(text("SELECT total_tokens FROM request_logs WHERE id='log-b'")).scalar_one() == 0
    assert repo.delete_by_channel("channel-b") == 1
    assert repo.delete_log("log-a") is False
    repo.insert_log(RequestLogEntity(id="log-c", model="model-c", created_at=newer))
    assert repo.delete_log("log-c") is True
    assert repo.delete_all_logs() is True
    assert repo.query_logs(0, 10) == []
    engine.dispose()
