"""Record retry consumption independently from the final user-facing outcome."""

from datetime import UTC, datetime

from app.types.usage import UsageFact


class UsageRecorder:
    def __init__(self, repository, execution_id, request_id, request, api_key_id=None):
        self.repo = repository
        self.common = {"execution_id": execution_id, "request_id": request_id, "api_key_id": api_key_id,
                       "model": request.model, "route_group": request.route_group[:64], "endpoint": request.endpoint}
        self.attempts = []
        self._finished_at = None

    def attempt(self, item):
        values = {**self.common, "event_key": f"attempt:{item.attempt_no}", "kind": "attempt", "channel_id": item.channel_id,
                  "provider": item.provider, "account_id": item.account_id, "model": item.upstream_model or self.common["model"],
                  "status_code": item.status_code, "outcome": "succeeded" if item.succeeded else "failed", "input_tokens": item.input_tokens,
                  "output_tokens": item.output_tokens, "total_tokens": item.total_tokens, "usage_source": item.usage_source,
                  "duration_ms": item.duration_ms, "first_token_ms": item.first_token_ms, "occurred_at": item.started_at}
        if not any(attempt.attempt_no == item.attempt_no for attempt in self.attempts):
            self.attempts.append(item)
        self.repo.append(UsageFact(**values))

    def finish(self, outcome, status_code, duration_ms):
        self._finished_at = self._finished_at or datetime.now(UTC).isoformat()
        self.repo.append(UsageFact(**self.common, event_key="outcome", kind="outcome", outcome=outcome,
            status_code=status_code, duration_ms=duration_ms, occurred_at=self._finished_at))

    @property
    def consumed(self):
        return sum(item.total_tokens or 0 for item in self.attempts)
