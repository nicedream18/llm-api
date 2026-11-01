"""Backward-compatible HTTP adapter exports.

The adapter implementation lives in :mod:`channel_adapters`. Older callers
and the documented project layout use this module name, so keep this facade
instead of maintaining a second implementation.
"""

from app.infrastructure.adapters.channel_adapters import (
    AnthropicAdapter,
    ChannelAdapter,
    CustomAdapter,
    GeminiAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    adapter_for,
    models_url,
)

__all__ = [
    "AnthropicAdapter",
    "ChannelAdapter",
    "CustomAdapter",
    "GeminiAdapter",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "adapter_for",
    "models_url",
]
