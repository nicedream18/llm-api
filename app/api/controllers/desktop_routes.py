"""Authenticated read contracts required by the transplanted desktop frontend."""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import config
from app.container import get_container
from app.infrastructure.database.connection import get_db

router = APIRouter(prefix="/api/v1/desktop", tags=["Desktop"])


@router.get('/overview')
def overview():
    today = datetime.now(UTC).date().isoformat()
    with get_db() as db:
        row = dict(db.execute(text("""SELECT COUNT(*) AS total_requests,
            COALESCE(SUM(total_tokens),0) AS total_tokens,
            COALESCE(SUM(prompt_tokens),0) AS total_prompt_tokens,
            COALESCE(AVG(duration_ms),0) AS avg_latency_ms,
            COALESCE(SUM(CASE WHEN SUBSTRING(created_at,1,10)=:today THEN 1 ELSE 0 END),0) AS today_requests,
            COALESCE(SUM(CASE WHEN SUBSTRING(created_at,1,10)=:today THEN total_tokens ELSE 0 END),0) AS today_total_tokens,
            COALESCE(SUM(CASE WHEN SUBSTRING(created_at,1,10)=:today THEN prompt_tokens ELSE 0 END),0) AS today_prompt_tokens
            FROM request_logs"""), {'today': today}).mappings().one())
        # Identifiers below are fixed application tables, never user input.
        for table, name in [('channels', 'channels'), ('api_keys', 'api_keys'),
                            ('provider_accounts', 'auth_accounts'), ('kb_knowledge_bases', 'knowledge_bases'),
                            ('kb_documents', 'kb_documents'), ('kb_chunks', 'kb_chunks'),
                            ('wiki_projects', 'wiki_projects'), ('wiki_pages', 'wiki_pages')]:
            row['total_' + name] = db.execute(text('SELECT COUNT(*) FROM ' + table)).scalar_one()
        row['active_channels'] = db.execute(text('SELECT COUNT(*) FROM channels WHERE status=1')).scalar_one()
        row['active_auth_accounts'] = db.execute(text("SELECT COUNT(*) FROM provider_accounts WHERE status='active'")).scalar_one()
    # Python does not persist cached-token/TTFT accounting. The UI hides these metrics.
    return {'code': '0000', 'info': '成功', 'data': row}


@router.get('/tokens')
def tokens(hours: int = Query(24, ge=1, le=8784)):
    since = (datetime.now(UTC) - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as db:
        rows = db.execute(text("""SELECT SUBSTRING(REPLACE(created_at,'T',' '),1,13) AS hour, model,
            SUM(prompt_tokens) AS input_tokens, SUM(completion_tokens) AS output_tokens,
            SUM(total_tokens) AS total_tokens, COUNT(*) AS request_count
            FROM request_logs WHERE REPLACE(created_at,'T',' ')>=:since
            GROUP BY SUBSTRING(REPLACE(created_at,'T',' '),1,13), model ORDER BY hour, model"""), {'since': since}).mappings()
        result = [dict(row, hour=row['hour'].replace(' ', 'T') + ':00:00Z', cached_tokens=0) for row in rows]
    return {'code': '0000', 'info': '成功', 'data': result}


@router.get('/logs')
def logs(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
         keyword: str | None = None, model: str | None = None,
         api_key_name: str | None = None, channel_name: str | None = None,
         date_from: str | None = None, date_to: str | None = None, trace_id: str | None = None,
         count_only: bool = False, client_name: str | None = None, upstream_type: str | None = None):
    if client_name or upstream_type:
        raise HTTPException(422, 'Python 暂未提供调用来源和上游类型筛选')
    predicates, params = [], {}
    for column, value in [('model', model), ('api_key_name', api_key_name),
                          ('channel_name', channel_name), ('trace_id', trace_id)]:
        if value:
            predicates.append(column + '=:' + column)
            params[column] = value
    if keyword:
        predicates.append('(model LIKE :keyword OR error_message LIKE :keyword)')
        params['keyword'] = '%' + keyword + '%'
    for name, operator, value in [('date_from', '>=', date_from), ('date_to', '<=', date_to)]:
        if value:
            predicates.append("REPLACE(created_at,'T',' ')" + operator + ':' + name)
            params[name] = value.replace('T', ' ')
    where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
    with get_db() as db:
        total = db.execute(text('SELECT COUNT(*) FROM request_logs' + where), params).scalar_one()
        items = [] if count_only else [dict(row) for row in db.execute(text(
            'SELECT * FROM request_logs' + where + ' ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset'
        ), {**params, 'limit': limit, 'offset': offset}).mappings()]
    return {'code': '0000', 'info': '成功', 'data': {'items': items, 'total': total}}


@router.get('/daily-tokens')
def daily_tokens(days: int = Query(385, ge=1, le=730)):
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    with get_db() as db:
        result = [dict(row) for row in db.execute(text("""SELECT SUBSTRING(created_at,1,10) AS day,
            COALESCE(SUM(total_tokens),0) AS total_tokens, COUNT(*) AS request_count
            FROM request_logs WHERE created_at>=:since
            GROUP BY SUBSTRING(created_at,1,10) ORDER BY day"""), {'since': since}).mappings()]
    return {'code': '0000', 'info': '成功', 'data': result}


@router.get('/log-filters')
def log_filters():
    since = (datetime.now(UTC) - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as db:
        channels = [dict(row) for row in db.execute(text("""SELECT channel_name AS name, COUNT(*) AS count
            FROM request_logs WHERE REPLACE(created_at,'T',' ')>=:since
            AND channel_name IS NOT NULL AND channel_name<>''
            GROUP BY channel_name ORDER BY count DESC, channel_name"""), {'since': since}).mappings()]
    return {'code': '0000', 'info': '成功', 'data': {'clients': [], 'channels': channels}}


@router.get('/route-flow')
def route_flow(hours: int = Query(24, ge=1, le=8784)):
    since = (datetime.now(UTC) - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as db:
        result = [dict(row, avg_ttft_ms=0) for row in db.execute(text("""SELECT channel_id,
            MAX(channel_name) AS channel_name, COUNT(*) AS request_count,
            SUM(CASE WHEN status_code>=400 THEN 1 ELSE 0 END) AS fail_count,
            COALESCE(SUM(total_tokens),0) AS total_tokens, MAX(created_at) AS last_at
            FROM request_logs WHERE REPLACE(created_at,'T',' ')>=:since
            GROUP BY channel_id ORDER BY request_count DESC"""), {'since': since}).mappings()]
    return {'code': '0000', 'info': '成功', 'data': result}


@router.get('/stats/{kind}')
def stats(kind: str):
    if kind not in {'channel', 'api_key', 'model'}:
        raise HTTPException(404, 'Unknown statistics kind')
    column = {'channel': 'channel_id', 'api_key': 'api_key_id', 'model': 'model'}[kind]
    with get_db() as db:
        result = [dict(row) for row in db.execute(text(
            'SELECT ' + column + ', COUNT(*) AS total_calls, '
            'SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) AS success_calls, '
            'SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS failed_calls, '
            'SUM(prompt_tokens) AS input_tokens, SUM(completion_tokens) AS output_tokens, '
            'SUM(total_tokens) AS total_tokens, AVG(duration_ms) AS avg_latency_ms, '
            'MAX(created_at) AS last_call_at FROM request_logs GROUP BY ' + column
        )).mappings()]
    return {'code': '0000', 'info': '成功', 'data': result}


@router.get('/secret/{kind}/{item_id}')
def secret(kind: str, item_id: str):
    repository = get_container().channel_repo
    if kind == 'channel':
        entity = repository.get_channel(item_id)
        value = entity.api_key if entity else None
    elif kind == 'api-key':
        entity = repository.get_api_key(item_id)
        value = entity.key if entity else None
    else:
        raise HTTPException(404, 'Unknown secret kind')
    if entity is None:
        raise HTTPException(404, 'Not found')
    return JSONResponse({'code': '0000', 'info': '成功', 'data': value or ''},
                        headers={'Cache-Control': 'no-store'})


@router.get('/runtime')
def runtime():
    return {'code': '0000', 'info': '成功', 'data': {
        'server_port': config.server_port, 'retry_enabled': config.gateway.retry_times > 0,
        'retry_times': config.gateway.retry_times,
    }}
