"""Immutable per-request security policy and legacy bootstrap conversion."""
from dataclasses import dataclass, replace

from app.config import SecuritySettings


@dataclass(frozen=True)
class SecuritySnapshot:
    settings: SecuritySettings
    custom_rules: tuple = ()
    builtin_rules: tuple = ()


def upgrade_settings(settings: SecuritySettings) -> SecuritySettings:
    # REDACT_SECRETS used to gate mode-based redaction. It was not an independent switch.
    mode = "audit" if settings.mode == "redact" and not settings.redact_secrets else settings.mode
    return replace(settings, mode=mode, redact_secrets=False)
