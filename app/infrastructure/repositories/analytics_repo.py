"""Bounded streaming aggregation of immutable usage; currencies never combined."""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.application.errors import ApplicationError
from app.infrastructure.database.connection import engine as default_engine

FILTERS = ("provider", "account_id", "model", "api_key_id", "route_group", "endpoint")


def _filter(query):
    clauses = ["occurred_at>=:start", "occurred_at<:end"]
    values = {"start": query.start.isoformat(), "end": query.end.isoformat()}
    for name in FILTERS:
        if getattr(query, name) is not None:
            if getattr(query, name) == "(unknown)":
                clauses.append(f"COALESCE({name},'')='' ")
            else:
                clauses.append(f"{name}=:{name}")
                values[name] = getattr(query, name)
    if query.bucket:
        beginning = datetime.strptime(query.bucket, "%Y-%m-%d").replace(tzinfo=ZoneInfo(query.timezone)) if query.group_by == "day" else datetime.strptime(query.bucket, "%Y-%m-%dT%H:00%z")
        ending = beginning + (timedelta(days=1) if query.group_by == "day" else timedelta(hours=1))
        clauses.extend(["occurred_at>=:bucket_start", "occurred_at<:bucket_end"])
        values.update({"bucket_start": beginning.astimezone(UTC).isoformat(), "bucket_end": ending.astimezone(UTC).isoformat()})
    return " AND ".join(clauses), values


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


class AnalyticsRepository:
    MAX_ROWS = 100_000
    MAX_GROUPS = 2000

    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def report(self, query):
        where, values = _filter(query)
        groups = {}
        zone = ZoneInfo(query.timezone)
        with self.engine.connect().execution_options(stream_results=True) as db:
            rows = db.execute(text("SELECT * FROM usage_ledger WHERE " + where + " ORDER BY occurred_at,id LIMIT :maximum"), {**values, "maximum": self.MAX_ROWS + 1}).mappings()
            for index, row in enumerate(rows):
                if index == self.MAX_ROWS:
                    raise ApplicationError("Narrow the analytics range or filters (100000 event limit)", 422, "analytics_budget_exceeded")
                if query.group_by in {"day", "hour"}:
                    local = datetime.fromisoformat(row["occurred_at"]).astimezone(zone)
                    label = local.strftime("%Y-%m-%d" if query.group_by == "day" else "%Y-%m-%dT%H:00%z")
                else:
                    label = row[query.group_by] or "(unknown)"
                if label not in groups:
                    if len(groups) >= self.MAX_GROUPS:
                        raise ApplicationError("Narrow analytics grouping (2000 group limit)", 422, "analytics_budget_exceeded")
                    groups[label] = {"group": label, "requests": 0, "errors": 0, "attempts": 0, "total_tokens": 0,
                        "unknown_usage": 0, "unknown_price": 0, "estimated_usage": 0, "costs": defaultdict(Decimal), "latencies": [], "first_tokens": []}
                bucket = groups[label]
                if row["kind"] == "outcome":
                    bucket["requests"] += 1
                    bucket["errors"] += int(row["status_code"] is None or row["status_code"] >= 400 or row["outcome"] in {"error", "client_disconnect"})
                    bucket["latencies"].append(row["duration_ms"])
                else:
                    bucket["attempts"] += 1
                    bucket["total_tokens"] += row["total_tokens"] or 0
                    bucket["unknown_usage"] += int(row["usage_source"] == "unknown")
                    bucket["unknown_price"] += int(row["cost"] is None)
                    bucket["estimated_usage"] += int(row["usage_source"] == "estimated")
                    if row["cost"] is not None:
                        bucket["costs"][row["currency"]] += Decimal(row["cost"])
                    if row["first_token_ms"] is not None:
                        bucket["first_tokens"].append(row["first_token_ms"])
        items = []
        for label in sorted(groups):
            item = groups[label]
            latency, first = item.pop("latencies"), item.pop("first_tokens")
            item["costs"] = {currency: str(cost) for currency, cost in sorted(item["costs"].items())}
            item.update({"failure_rate": item["errors"] / item["requests"] if item["requests"] else None,
                         "latency_p50": percentile(latency, 0.5), "latency_p95": percentile(latency, 0.95),
                         "latency_p99": percentile(latency, 0.99), "first_token_p95": percentile(first, 0.95)})
            items.append(item)
        return {"start": query.start.isoformat(), "end": query.end.isoformat(), "timezone": query.timezone,
                "group_by": query.group_by, "items": items, "limits": {"events": self.MAX_ROWS, "groups": self.MAX_GROUPS}}

    def events(self, query, limit=50, offset=0):
        where, values = _filter(query)
        with self.engine.connect() as db:
            total = db.execute(text("SELECT COUNT(*) FROM usage_ledger WHERE " + where), values).scalar_one()
            rows = db.execute(text("SELECT * FROM usage_ledger WHERE " + where + " ORDER BY occurred_at DESC,id DESC LIMIT :limit OFFSET :offset"), {**values, "limit": limit, "offset": offset}).mappings()
            return {"total": total, "items": [dict(row) for row in rows], "limit": limit, "offset": offset}
