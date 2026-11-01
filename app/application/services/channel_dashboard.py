"""Application services orchestrating domain services and repositories."""
import logging
import uuid
from datetime import UTC, datetime

from app.domain.entities import (
    ApiKeyEntity,
    ChannelApiKeyEntity,
    ChannelEntity,
)
from app.types.models import (
    ApiKeyDTO,
    ChannelApiKeyDTO,
    ChannelDTO,
    DashboardStatsDTO,
    RequestLogDTO,
    TestChannelResultDTO,
)

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(UTC).isoformat()


def _mask_secret(value: str | None) -> str | None:
    """Return a stable display value without exposing a stored credential."""
    if not value:
        return value
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"


def _is_masked_secret(value: str | None) -> bool:
    return bool(value and "*" in value)


class ChannelService:
    def __init__(self, channel_repository, gateway_service):
        self.repo = channel_repository
        self.gateway = gateway_service

    def list_channels(self):
        return [self._to_dto(e) for e in self.repo.get_all_channels()]

    def get_channel(self, channel_id):
        return self._to_dto(self.repo.get_channel(channel_id))

    def create_channel(self, dto: ChannelDTO):
        entity = self._to_entity(dto)
        if not entity.id:
            entity.id = str(uuid.uuid4())
        created = self.repo.create_channel(entity)
        return self._to_dto(created)

    def update_channel(self, dto: ChannelDTO):
        existing = self.repo.get_channel(dto.id) if dto.id else None
        return self.repo.update_channel(self._to_entity(dto, existing))

    def delete_channel(self, channel_id):
        return self.repo.delete_channel(channel_id)

    def test_channel(self, channel_id):
        entity = self.repo.get_channel(channel_id)
        if not entity:
            return TestChannelResultDTO(channel_id=channel_id, success=False, message="Channel not found")
        success = self.gateway.test_channel(entity)
        self.repo.update_test_result(channel_id, success)
        return TestChannelResultDTO(channel_id=channel_id, success=success,
                                    message="OK" if success else "Test failed", duration_ms=0)

    def clone_channel(self, channel_id):
        source = self.repo.get_channel(channel_id)
        if not source:
            return None
        clone = ChannelEntity(
            name=f"{source.name} (copy)", type=source.type, base_url=source.base_url,
            api_key=source.api_key, models=list(source.models or []), status=source.status,
            priority=source.priority, weight=source.weight,
            config=dict(source.config or {}), model_mapping=dict(source.model_mapping or {}),
            api_keys=[ChannelApiKeyEntity(name=key.name, api_key=key.api_key, status=key.status, weight=key.weight)
                      for key in (source.api_keys or [])],
        )
        return self._to_dto(self.repo.create_channel(clone))

    def test_draft_channel(self, dto: ChannelDTO):
        entity = self._to_entity(dto)
        success = self.gateway.test_channel(entity)
        return TestChannelResultDTO(channel_id="draft", success=success,
                                    message="OK" if success else "Test failed", duration_ms=0)

    def sync_models(self, channel_id):
        entity = self.repo.get_channel(channel_id)
        if not entity:
            return None
        models = self.gateway.sync_models(entity)
        entity.models = models
        self.repo.update_channel(entity)
        return self._to_dto(entity)

    def list_channel_api_keys(self, channel_id):
        return [self._to_channel_key_dto(key) for key in self.repo.get_channel_api_keys(channel_id)]

    def create_channel_api_key(self, channel_id, dto: ChannelApiKeyDTO):
        entity = self._to_channel_key_entity(channel_id, dto)
        return self._to_channel_key_dto(self.repo.create_channel_api_key(entity), expose_secret=True)

    def update_channel_api_key(self, channel_id, key_id, dto: ChannelApiKeyDTO):
        entity = self._to_channel_key_entity(channel_id, dto)
        entity.id = key_id
        return self.repo.update_channel_api_key(entity)

    def delete_channel_api_key(self, channel_id, key_id):
        return self.repo.delete_channel_api_key(channel_id, key_id)

    def list_api_keys(self):
        return [self._to_apikey_dto(e) for e in self.repo.get_all_api_keys()]

    def get_api_key(self, key_id):
        return self._to_apikey_dto(self.repo.get_api_key(key_id))

    def create_api_key(self, dto: ApiKeyDTO):
        entity = self._to_apikey_entity(dto)
        if not entity.id:
            entity.id = str(uuid.uuid4())
        if not entity.key:
            entity.key = "sk-waliapi-" + str(uuid.uuid4()).replace("-", "")
        created = self.repo.create_api_key(entity)
        return self._to_apikey_dto(created, expose_secret=True)

    def update_api_key(self, dto: ApiKeyDTO):
        existing = self.repo.get_api_key(dto.id) if dto.id else None
        return self.repo.update_api_key(self._to_apikey_entity(dto, existing))

    def delete_api_key(self, key_id):
        return self.repo.delete_api_key(key_id)

    def _to_dto(self, e):
        if not e: return None
        return ChannelDTO(id=e.id, name=e.name, type=e.type, base_url=e.base_url, api_key=_mask_secret(e.api_key),
                          models=e.models or [], status=e.status, priority=e.priority, weight=e.weight,
                          config=e.config, model_mapping=e.model_mapping, last_test_at=e.last_test_at,
                          last_test_ok=e.last_test_ok, created_at=e.created_at, updated_at=e.updated_at,
                          api_keys=[self._to_channel_key_dto(key) for key in (e.api_keys or [])])

    def _to_entity(self, dto, existing=None):
        api_key = dto.api_key
        if existing and (api_key is None or _is_masked_secret(api_key)):
            api_key = existing.api_key
        api_keys = existing.api_keys if existing and dto.api_keys is None else [self._to_channel_key_entity(dto.id, key) for key in (dto.api_keys or [])]
        return ChannelEntity(id=dto.id, name=dto.name, type=dto.type, base_url=dto.base_url,
                             api_key=api_key, models=dto.models, status=dto.status,
                             priority=dto.priority, weight=dto.weight, config=dto.config,
                             model_mapping=dto.model_mapping, last_test_at=dto.last_test_at,
                             last_test_ok=dto.last_test_ok, created_at=dto.created_at, updated_at=dto.updated_at,
                             api_keys=api_keys)

    def _to_channel_key_dto(self, entity, expose_secret=False):
        return ChannelApiKeyDTO(
            id=entity.id, channel_id=entity.channel_id, name=entity.name,
            api_key=entity.api_key if expose_secret else _mask_secret(entity.api_key),
            status=entity.status, weight=entity.weight, last_error=entity.last_error,
            cooldown_until=entity.cooldown_until, last_used_at=entity.last_used_at,
            created_at=entity.created_at, updated_at=entity.updated_at,
        )

    def _to_channel_key_entity(self, channel_id, dto):
        secret = dto.api_key
        existing = None
        if dto.id and hasattr(self.repo, "get_channel_api_keys"):
            existing = next((key for key in self.repo.get_channel_api_keys(channel_id) if key.id == dto.id), None)
        if existing and (secret is None or _is_masked_secret(secret)):
            secret = existing.api_key
        if not secret:
            raise ValueError("Upstream API key is required")
        return ChannelApiKeyEntity(
            id=dto.id, channel_id=channel_id, name=dto.name, api_key=secret,
            status=dto.status, weight=dto.weight, last_error=dto.last_error,
            cooldown_until=dto.cooldown_until, last_used_at=dto.last_used_at,
            created_at=dto.created_at, updated_at=dto.updated_at,
        )

    def _to_apikey_dto(self, e, expose_secret=False):
        if not e: return None
        return ApiKeyDTO(id=e.id, name=e.name, key=e.key if expose_secret else _mask_secret(e.key), status=e.status,
                         allowed_models=e.allowed_models or [], allowed_channels=e.allowed_channels or [],
                         quota_limit=e.quota_limit, quota_used=e.quota_used, expires_at=e.expires_at,
                         created_at=e.created_at, updated_at=e.updated_at)

    def _to_apikey_entity(self, dto, existing=None):
        key = dto.key
        if existing and (key is None or _is_masked_secret(key)):
            key = existing.key
        return ApiKeyEntity(id=dto.id, name=dto.name, key=key, status=dto.status,
                            allowed_models=dto.allowed_models, allowed_channels=dto.allowed_channels,
                            quota_limit=dto.quota_limit, quota_used=dto.quota_used, expires_at=dto.expires_at,
                            created_at=dto.created_at, updated_at=dto.updated_at)


class DashboardService:
    def __init__(self, log_repository, stats_repository):
        self.log_repo = log_repository
        self.stats_repo = stats_repository

    def dashboard(self):
        stats = self.stats_repo.get_dashboard_stats()
        health_score, health_badge = self._calculate_health_score(stats)
        return DashboardStatsDTO(
            total_requests=stats.total_requests, total_tokens=stats.total_tokens,
            total_errors=stats.total_errors, avg_duration_ms=stats.avg_duration_ms,
            active_channels=stats.active_channels, active_api_keys=stats.active_api_keys,
            health_score=health_score,
            health_badge=health_badge,
        )

    def logs(self, api_key_id=None, channel_id=None, model=None, risk_level=None,
             start_time=None, end_time=None, keyword=None, page=1, size=20, limit=None):
        if limit:
            size = limit
            if not page or page == 1:
                page = 1
        if not page: page = 1
        if not size: size = 20
        offset = (page - 1) * size
        if keyword:
            logs = self.log_repo.search_logs(offset, size, keyword=keyword, model=model, date_from=start_time, date_to=end_time)
        else:
            logs = self.log_repo.query_logs(offset, size, api_key_id, channel_id, model, risk_level, start_time, end_time)
        return [self._to_dto(l) for l in logs]

    def get_log(self, log_id):
        return self._to_dto(self.log_repo.get_log_by_id(log_id))

    def delete_log(self, log_id):
        return self.log_repo.delete_log(log_id)

    def delete_all_logs(self):
        return self.log_repo.delete_all_logs()

    def _to_dto(self, e):
        if not e: return None
        return RequestLogDTO(id=e.id, seq=e.seq, api_key_id=e.api_key_id, api_key_name=e.api_key_name,
                             channel_id=e.channel_id, channel_name=e.channel_name, model=e.model,
                             upstream_model=e.upstream_model, mode=e.mode, status_code=e.status_code,
                             prompt_tokens=e.prompt_tokens, completion_tokens=e.completion_tokens,
                             total_tokens=e.total_tokens, duration_ms=e.duration_ms,
                             error_message=e.error_message, is_stream=e.stream, is_retry=e.retry,
                             request_body=e.request_body, response_choices=e.response_choices,
                             risk_level=e.risk_level, risk_score=e.risk_score, risk_summary=e.risk_summary,
                             security_action=e.security_action, sanitized=e.sanitized,
                             blocked_reason=e.blocked_reason, trace_id=e.trace_id, created_at=e.created_at)

    def _calculate_health_score(self, stats):
        """Calculate health score aligned with Java StatsService logic.
        - score = 100
        - errorRate > 5%  → score -= 30
        - errorRate > 20% → score = 40
        - avgDurationMs > 5000 → score -= 20
        - activeChannels == 0 → score = 0
        - badge: >=90 healthy, >=70 warning, otherwise critical
        """
        score = 100
        total_requests = stats.total_requests or 0
        total_errors = stats.total_errors or 0
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

        if stats.active_channels == 0:
            score = 0
        else:
            if error_rate > 20:
                score = 40
            elif error_rate > 5:
                score -= 30
            if (stats.avg_duration_ms or 0) > 5000:
                score -= 20

        score = max(0, min(100, score))

        if score >= 90:
            badge = "healthy"
        elif score >= 70:
            badge = "warning"
        else:
            badge = "critical"

        return score, badge
