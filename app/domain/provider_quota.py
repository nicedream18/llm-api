"""Keep vendor-reported quota units and windows separate."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.errors import ApplicationError
from app.types.provider_sync import QuotaWindow


def normalize_quota(payload):
    if not isinstance(payload, dict):
        raise ApplicationError("Invalid quota response", 502, "invalid_provider_response")
    windows = payload.get("windows", [payload] if "remaining" in payload else [])
    if not isinstance(windows, list) or len(windows) > 100:
        raise ApplicationError("Invalid quota windows", 502, "invalid_provider_response")
    try:
        normalized = [QuotaWindow.model_validate(window) for window in windows]
    except (ValueError, TypeError):
        raise ApplicationError("Invalid quota window", 502, "invalid_provider_response") from None
    result = {"source": "reported", "windows": [window.model_dump(mode="json") for window in normalized]}
    result["status"] = quota_status(result)
    return result


def quota_status(snapshot, now=None):
    now = now or datetime.now(UTC)
    if not snapshot or not snapshot.get("windows"):
        return "unknown"
    if snapshot.get("fetched_at"):
        fetched = datetime.fromisoformat(snapshot["fetched_at"])
        if now - fetched > timedelta(minutes=15):
            return "stale"
    known = []
    for window in snapshot["windows"]:
        if window.get("unit") == "unknown" or window.get("remaining") is None:
            continue
        if window.get("unit") == "currency" and not window.get("currency"):
            continue
        if window.get("reset_at"):
            try:
                reset = datetime.fromisoformat(window["reset_at"])
                if reset.replace(tzinfo=reset.tzinfo or UTC) <= now:
                    return "stale"
            except ValueError:
                return "unknown"
        remaining = Decimal(str(window["remaining"]))
        if remaining <= 0:
            return "exhausted"
        known.append((remaining, Decimal(str(window["limit"])) if window.get("limit") else None))
    if not known:
        return "unknown"
    return "low" if any(limit and remaining / limit <= Decimal("0.1") for remaining, limit in known) else "normal"
