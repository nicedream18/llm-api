"""Channel candidate planner with priority and weighted selection."""
from __future__ import annotations

import random
from collections import defaultdict

from app.domain.entities import ChannelEntity, DispatchResult
from app.types.response import AppException


class Dispatcher:
    def __init__(self, channel_repository, provider_source=None):
        self.channel_repository = channel_repository
        self.provider_source = provider_source

    def _supports_model(self, channel: ChannelEntity, model: str) -> bool:
        return not channel.models or model in channel.models or bool(channel.model_mapping and model in channel.model_mapping)

    def _resolve_model(self, channel: ChannelEntity, model: str) -> str:
        return (channel.model_mapping or {}).get(model, model)

    def candidates(self, model: str, excluded: set[str] | None = None) -> list[DispatchResult]:
        excluded = excluded or set()
        channels = self.channel_repository.get_enabled_channels()
        if self.provider_source is not None:
            channels = [*channels, *self.provider_source.routing_channels(model)]
        eligible = [c for c in channels if (c.id or c.name) not in excluded and self._supports_model(c, model)]
        if not eligible:
            return []
        groups = defaultdict(list)
        for channel in eligible:
            groups[channel.priority or 0].append(channel)
        results: list[DispatchResult] = []
        # Preserve priority ordering while randomizing candidates within each
        # priority group. This lets the gateway fail over to lower priorities
        # after all candidates in a higher-priority group have failed.
        for priority in sorted(groups, reverse=True):
            remaining = list(groups[priority])
            while remaining:
                weights = [max(1, int(c.weight or 1)) for c in remaining]
                chosen = random.choices(remaining, weights=weights, k=1)[0]
                remaining.remove(chosen)
                results.append(DispatchResult(channel=chosen, upstream_model=self._resolve_model(chosen, model), success=True))
        return results

    def dispatch(self, model: str) -> DispatchResult:
        candidates = self.candidates(model)
        if not candidates:
            raise AppException("0004", f"No channel supports model: {model}")
        return candidates[0]
