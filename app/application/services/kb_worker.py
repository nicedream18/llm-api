"""Recoverable database-backed knowledge task worker."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from app.config import config
from app.domain.task_lease import LostTaskLease, TaskLease
from app.types.models import UploadDocDTO

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KnowledgeTaskWorker:
    def __init__(self, kb_service, repository, worker_id: str | None = None):
        self.kb_service = kb_service
        self.repository = repository
        self.worker_id = worker_id or uuid.uuid4().hex
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        await asyncio.to_thread(self.repository.recover_expired_tasks)
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._run(), name=f"kb-worker-{i}") for i in range(config.workers.count)]

    @property
    def running(self) -> bool:
        return bool(self._tasks) and any(not task.done() for task in self._tasks)

    async def stop(self):
        self._stop.set()
        if self._tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=10)
            except TimeoutError:
                for task in self._tasks:
                    task.cancel()
        self._tasks.clear()

    async def _run(self):
        while not self._stop.is_set():
            await asyncio.to_thread(self.repository.recover_expired_tasks)
            task = await asyncio.to_thread(self.repository.claim_next_task, self.worker_id, config.workers.lease_seconds)
            if not task:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=0.5)
                except TimeoutError:
                    pass
                continue
            try:
                await self._execute_async(task)
            except Exception:
                logger.exception("Knowledge task execution failed", extra={"task_id": task["id"]})

    async def _execute_async(self, task):
        lease = TaskLease(task["worker_id"], task["attempt_count"])
        execution = asyncio.create_task(asyncio.to_thread(self._execute, task, lease))
        try:
            while not execution.done():
                try:
                    await asyncio.wait_for(asyncio.shield(execution), timeout=max(5, config.workers.lease_seconds // 3))
                except TimeoutError:
                    renewed = await asyncio.to_thread(self.repository.renew_task_lease, task["id"], lease, config.workers.lease_seconds)
                    if not renewed:
                        lease.cancelled.set()
                        return
            await execution
        except asyncio.CancelledError:
            lease.cancelled.set()
            execution.cancel()
            with suppress(asyncio.CancelledError):
                await execution
            raise
        finally:
            lease.cancelled.set()

    def _execute(self, task, lease=None):
        lease = lease or TaskLease(task["worker_id"], task["attempt_count"])
        task_id = task["id"]
        try:
            if task["task_type"] == "import":
                payload = task["payload"]
                dto = UploadDocDTO(filename=payload["filename"], content=payload["content"],
                                   file_type=payload.get("file_type"), source_type=payload.get("source_type"))
                self.kb_service.run_import_pipeline(task["kb_id"], task["doc_id"], task_id, dto, lease=lease)
            elif task["task_type"] == "reindex":
                chunks = self.repository.find_chunk_by_doc_id(task["doc_id"])
                self.kb_service.run_reindex_pipeline(task["kb_id"], task["doc_id"], task_id, chunks, lease=lease)
            else:
                raise ValueError(f"Unsupported task type: {task['task_type']}")
        except LostTaskLease:
            logger.info("Knowledge task lost ownership: %s", task_id)
        except Exception as exc:  # noqa: BLE001 - worker must mark failed tasks
            self.repository.fail_or_retry_task(task_id, str(exc), config.workers.max_attempts, lease)
