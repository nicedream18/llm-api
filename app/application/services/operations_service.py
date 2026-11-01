"""Internal alert evaluation; no external notifications are sent."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from app.types.analytics import AnalyticsQuery

logger = logging.getLogger(__name__)


class OperationsService:
    def __init__(self, analytics, alerts):
        self.analytics, self.alerts = analytics, alerts

    def evaluate(self):
        for rule in self.alerts.rules():
            triggered = set()
            if rule["enabled"]:
                end = datetime.now(UTC)
                report = self.analytics.report(AnalyticsQuery(start=end - timedelta(minutes=rule["window_minutes"]), end=end, group_by="provider"))
                for item in report["items"]:
                    metric = rule["metric"]
                    value = item["failure_rate"] if metric == "failure_rate" else item["latency_p95"] if metric == "latency_p95" else item["unknown_price"]
                    samples = item["attempts"] if metric == "unknown_price" else item["requests"]
                    if samples >= rule["min_samples"] and value is not None and value >= rule["threshold"]:
                        key = rule["id"] + ":" + hashlib.sha256(item["group"].encode()).hexdigest()
                        triggered.add(key)
                        self.alerts.transition(key, True, rule["severity"], f"{metric} exceeded configured threshold for {item['group'][:128]}")
            for key in self.alerts.active_fingerprints(rule["id"]):
                if key not in triggered:
                    self.alerts.transition(key, False)
        return {"evaluated_at": datetime.now(UTC).isoformat()}


class OperationsWorker:
    def __init__(self, service):
        self.service = service
        self._stop = asyncio.Event()
        self.task = None

    async def start(self):
        if self.task and not self.task.done():
            return
        self._stop.clear()
        self.task = asyncio.create_task(self._run(), name="operations-alerts")

    async def stop(self):
        self._stop.set()
        if self.task:
            await self.task
            self.task = None

    async def _run(self):
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.service.evaluate)
            except Exception:  # noqa: BLE001 - worker boundary; failure never resolves existing alerts
                logger.warning("Operational alert evaluation unavailable")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
            except TimeoutError:
                pass
