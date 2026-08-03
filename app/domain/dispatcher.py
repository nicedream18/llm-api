"""Channel dispatcher: selects a channel for a model based on priority + weighted random."""
import random
import logging
from collections import defaultdict
from typing import List

from app.domain.entities import ChannelEntity, DispatchResult

logger = logging.getLogger(__name__)


class AppException(Exception):
    def __init__(self, code="0001", info=None):
        self.code = code
        self.info = info
        super().__init__(info or code)


class Dispatcher:
    def __init__(self, channel_repository):
        self.channel_repository = channel_repository

    def dispatch(self, model: str) -> DispatchResult:
        channels = self.channel_repository.get_enabled_channels()
        if not channels:
            raise AppException("0004", "No enabled channels")

        candidates = [ch for ch in channels if self._supports_model(ch, model)]
        if not candidates:
            raise AppException("0004", f"No channel supports model: {model}")

        by_priority = defaultdict(list)
        for ch in candidates:
            by_priority[ch.priority or 0].append(ch)

        top_priority = max(by_priority.keys())
        top_group = by_priority[top_priority]

        selected = self._weighted_random(top_group)
        upstream_model = self._resolve_model(selected, model)

        logger.info(f"Dispatched model={model} to channel={selected.name} upstream={upstream_model}")
        return DispatchResult(channel=selected, upstream_model=upstream_model, success=True)

    def _supports_model(self, channel: ChannelEntity, model: str) -> bool:
        if not channel.models:
            return True
        if model in channel.models:
            return True
        if channel.model_mapping and model in channel.model_mapping:
            return True
        return False

    def _resolve_model(self, channel: ChannelEntity, model: str) -> str:
        if channel.model_mapping and model in channel.model_mapping:
            return channel.model_mapping[model]
        return model

    def _weighted_random(self, channels: List[ChannelEntity]) -> ChannelEntity:
        weights = [max(1, ch.weight or 1) for ch in channels]
        total = sum(weights)
        r = random.randint(0, total - 1)
        cumulative = 0
        for ch, w in zip(channels, weights):
            cumulative += w
            if r < cumulative:
                return ch
        return channels[-1]
