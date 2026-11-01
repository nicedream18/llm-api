"""Bounded synchronization workers backed by durable job leases."""

import asyncio
import logging
import uuid

from app.application.errors import ApplicationError

logger = logging.getLogger(__name__)


class ProviderSyncWorker:
    def __init__(self, service, repository, count=2):
        self.service, self.repo = service, repository
        self.count = count
        self.owner = uuid.uuid4().hex
        self._stop = asyncio.Event()
        self._tasks = []

    @property
    def running(self):
        return any(not task.done() for task in self._tasks)

    async def start(self):
        if self.running:
            return
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._run(), name=f"provider-sync-{index}") for index in range(self.count)]

    async def stop(self):
        self._stop.set()
        if self._tasks:
            _done, pending = await asyncio.wait(self._tasks, timeout=2)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.to_thread(self.repo.abandon_sync, self.owner)
        self._tasks.clear()

    async def _run(self):
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.repo.schedule_sync)
                job = await asyncio.to_thread(self.repo.claim_sync, self.owner)
                if job:
                    await asyncio.to_thread(self.execute, job)
                    continue
            except Exception:  # noqa: BLE001 - isolate database failures at the worker boundary
                logger.warning("Provider synchronization worker is unavailable")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1)
            except TimeoutError:
                pass

    def execute(self, job):
        try:
            self.service._provider_data(job["account_id"], job["kind"], job)
        except ApplicationError as exc:
            self.repo.finish_sync(job, exc.code, retry=exc.status_code in {429, 502, 503, 504})
        except (ValueError, TypeError, RuntimeError):
            self.repo.finish_sync(job, "sync_failed", retry=True)
        else:
            self.repo.finish_sync(job)
