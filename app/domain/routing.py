"""Route planning shares filters with previews; preview never consumes capacity."""

import random
from datetime import UTC, datetime

from app.application.errors import ApplicationError
from app.types.routing import RoutePolicy


def supports_endpoint(channel, endpoint):
    endpoints = (channel.config or {}).get("endpoints")
    if endpoints is not None:
        return endpoint in endpoints
    # Legacy channels retain broad OpenAI compatibility. Non-OpenAI transports
    # only implement chat conversion unless explicitly configured otherwise.
    return channel.type in {"openai", "azure", "deepseek", "moonshot", "qwen", "zhipu", "doubao", "custom"} or endpoint == "/v1/chat/completions"


class RoutingPlanner:
    def __init__(self, repository, dispatcher):
        self.repo, self.dispatcher = repository, dispatcher

    def policy(self, request):
        value = self.repo.policy(request.route_group) if request.route_group else None
        if request.route_group and value is None:
            raise ApplicationError("Route group not found", 404, "route_group_not_found")
        policy = RoutePolicy.model_validate(value or {})
        if (not policy.enabled or (policy.api_key_ids and request.principal_id not in policy.api_key_ids)
                or (policy.models and request.model not in policy.models)
                or (policy.endpoints and request.endpoint not in policy.endpoints)):
            raise ApplicationError("Route policy denied this request", 403, "route_forbidden")
        return policy

    def plan(self, request, excluded=None, preview=False):
        policy = self.policy(request)
        kwargs = {"preview": True} if preview else {}
        candidates = self.dispatcher.candidates(request.model, excluded or set(), **kwargs)
        eligible, diagnostics = [], []
        for item in candidates:
            channel = item.channel
            state = self.repo.state(str(channel.id or channel.name))
            names = {channel.id, channel.name}
            reason = None
            if request.allowed_channels and not names.intersection(request.allowed_channels):
                reason = "key_channel_forbidden"
            elif policy.channels and not names.intersection(policy.channels):
                reason = "group_channel_forbidden"
            elif not supports_endpoint(channel, request.endpoint):
                reason = "endpoint_unsupported"
            elif (channel.config or {}).get("quota_status") == "exhausted":
                reason = "quota_exhausted"
            elif policy.unknown_quota == "deny" and (channel.config or {}).get("quota_status", "unknown") not in {"normal", "low"}:
                reason = "quota_unknown"
            else:
                if state.get("cooldown_until", "") and state["cooldown_until"] > datetime.now(UTC).isoformat():
                    reason = "cooling"
                elif state["active"] >= policy.max_concurrent or (state.get("failure_count") and state["active"]):
                    reason = "capacity_exhausted"
            diagnostics.append({"channel_id": channel.id, "channel_name": channel.name, "eligible": reason is None, "reason": reason, "active": state["active"], "quota_status": (channel.config or {}).get("quota_status", "unknown")})
            if reason is None:
                eligible.append(item)
        if policy.strategy == "quota_balanced":
            # Weighted random without replacement; preserve priority tiers and
            # use a normalized fraction, never compare tokens with currency.
            ordered = []
            for priority in sorted({item.channel.priority for item in eligible}, reverse=True):
                remaining = [item for item in eligible if item.channel.priority == priority]
                while remaining:
                    weights = [max(0.01, float((item.channel.config or {}).get("quota_fraction", 0.1))) * max(1, item.channel.weight) for item in remaining]
                    chosen = random.choices(remaining, weights=weights, k=1)[0]
                    ordered.append(chosen)
                    remaining.remove(chosen)
            eligible = ordered
        return eligible, policy, diagnostics

    def preview(self, request):
        items, policy, diagnostics = self.plan(request, preview=True)
        return {"strategy": policy.strategy, "retry_budget": policy.retry_budget, "candidates": [{"channel_id": item.channel.id, "upstream_model": item.upstream_model} for item in items], "diagnostics": diagnostics}
