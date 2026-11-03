from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api.controllers import desktop_routes
from app.api.middleware.auth import ApiKeyAuthMiddleware


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    with engine.begin() as db:
        db.execute(text('CREATE TABLE request_logs (id TEXT, created_at TEXT, channel_id TEXT, channel_name TEXT, api_key_id TEXT, api_key_name TEXT, model TEXT, status_code INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, duration_ms INTEGER, error_message TEXT, trace_id TEXT)'))
        for table in ['channels', 'api_keys', 'provider_accounts', 'kb_knowledge_bases', 'kb_documents', 'kb_chunks', 'wiki_projects', 'wiki_pages']:
            db.execute(text('CREATE TABLE ' + table + ' (id TEXT, status TEXT)'))
        now = datetime.now(UTC).isoformat()
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        for row in [('a', now.replace('T', ' '), 200, 10, 20), ('b', now, 500, 30, 40), ('c', old, 200, 50, 60)]:
            db.execute(text("INSERT INTO request_logs VALUES (:id,:created,'channel-1','Main','key-1','Client','model-a',:status,:input,:output,:total,100,'',:id)"), dict(zip(['id', 'created', 'status', 'input', 'output'], row), total=row[3] + row[4]))
        db.execute(text("INSERT INTO channels VALUES ('channel-1','1')"))
    @contextmanager
    def get_db():
        with engine.connect() as db:
            yield db
    monkeypatch.setattr(desktop_routes, 'get_db', get_db)
    app = FastAPI()
    app.include_router(desktop_routes.router)
    yield TestClient(app)
    engine.dispose()


def data(response):
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_overview_uses_real_counts_and_daily_tokens(client):
    stats = data(client.get('/api/v1/desktop/overview'))
    assert stats['total_requests'] == 3
    assert stats['today_requests'] == 2
    assert stats['today_total_tokens'] == 100
    assert stats['total_tokens'] == 210
    assert stats['active_channels'] == 1
    assert 'total_cached_tokens' not in stats


def test_daily_and_route_flow_limit_date_and_preserve_failures(client):
    daily = data(client.get('/api/v1/desktop/daily-tokens?days=2'))
    assert len(daily) == 1
    assert daily[0]['request_count'] == 2
    assert daily[0]['total_tokens'] == 100
    flow = data(client.get('/api/v1/desktop/route-flow?hours=24'))
    assert flow[0]['request_count'] == 2
    assert flow[0]['fail_count'] == 1
    trend = data(client.get('/api/v1/desktop/tokens?hours=24'))
    assert sum(row['input_tokens'] for row in trend) == 40
    assert len(trend) == 1
    assert trend[0]['hour'].endswith(':00:00Z')
    assert 'T' in trend[0]['hour']


def test_logs_filters_pagination_and_sql_injection_are_safe(client):
    logs = data(client.get('/api/v1/desktop/logs?limit=1&offset=1&channel_name=Main'))
    assert logs['total'] == 3
    assert len(logs['items']) == 1
    assert data(client.get('/api/v1/desktop/logs', params={'model': "' OR 1=1 --"}))['total'] == 0
    assert data(client.get('/api/v1/desktop/logs?count_only=true')) == {'items': [], 'total': 3}
    assert client.get('/api/v1/desktop/logs?client_name=unknown').status_code == 422
    assert client.get('/api/v1/desktop/logs?limit=0').status_code == 422
    assert data(client.get('/api/v1/desktop/log-filters'))['channels'] == [{'name': 'Main', 'count': 2}]


def test_stats_keep_input_output_and_error_counts(client):
    stats = data(client.get('/api/v1/desktop/stats/api_key'))[0]
    assert stats['success_calls'] == 2
    assert stats['failed_calls'] == 1
    assert stats['input_tokens'] == 90
    assert stats['output_tokens'] == 120
    assert client.get('/api/v1/desktop/stats/unsafe').status_code == 404


def test_secrets_are_only_returned_on_explicit_request_with_no_store(client, monkeypatch):
    repo = SimpleNamespace(get_channel=lambda _: SimpleNamespace(api_key='secret'), get_api_key=lambda _: None)
    monkeypatch.setattr(desktop_routes, 'get_container', lambda: SimpleNamespace(channel_repo=repo))
    response = client.get('/api/v1/desktop/secret/channel/a')
    assert data(response) == 'secret'
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/desktop/secret/api-key/missing').status_code == 404


def test_desktop_routes_require_admin_authentication(monkeypatch):
    app = FastAPI()
    app.include_router(desktop_routes.router)
    app.add_middleware(ApiKeyAuthMiddleware)
    monkeypatch.setattr('app.api.middleware.auth.get_container', lambda: SimpleNamespace(channel_repo=object()))
    assert TestClient(app).get('/api/v1/desktop/overview').status_code == 401
    assert TestClient(app).get('/api/v1/desktop/secret/channel/a').status_code == 401
