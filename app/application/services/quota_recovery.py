"""Durable settlement intents; unknown consumption is never auto-released.

The spool must be on a persistent, private volume. It contains reservation IDs
and token counts only. Database row locks make replay by multiple workers safe.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class RecoverableQuota:
    def __init__(self, repository, directory: Path):
        self.repository = repository
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, reservation: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", reservation):
            raise ValueError("Invalid quota reservation ID")
        return self.directory / f"{reservation}.json"

    def _write(self, reservation: str, action: str, tokens: int = 0) -> None:
        destination = self._path(reservation)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".quota-", delete=False) as file:
                temporary = Path(file.name)
                file.write(json.dumps({"id": reservation, "action": action, "tokens": max(0, int(tokens))}).encode())
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def reserve(self, key_id: str, request_id: str, tokens: int):
        # Bound disk growth before reserving or dispatching another request.
        if sum(1 for _ in self.directory.glob("*.json")) >= 10000:
            raise RuntimeError("Quota recovery spool is full")
        reservation = self.repository.reserve(key_id, request_id, tokens)
        if reservation:
            try:
                self._write(reservation, "unknown")
            except OSError:
                self.repository.release(reservation)  # No upstream call has started.
                raise
        return reservation

    def settle(self, reservation: str, tokens: int) -> bool:
        self._write(reservation, "settle", tokens)
        return self._apply(reservation, "settle", tokens)

    def release(self, reservation: str) -> bool:
        self._write(reservation, "release")
        return self._apply(reservation, "release", 0)

    def _apply(self, reservation: str, action: str, tokens: int) -> bool:
        try:
            changed = (self.repository.settle(reservation, tokens) if action == "settle"
                       else self.repository.release(reservation))
            if changed or self.repository.outcome_matches(reservation, action, tokens):
                self._path(reservation).unlink(missing_ok=True)
                return True
            logger.error("Quota settlement outcome conflict: %s", reservation)
        except Exception:  # noqa: BLE001 - durable intent remains for retry
            logger.warning("Quota settlement deferred: %s", reservation)
        return False

    def recover(self) -> dict[str, int]:
        result = {"recovered": 0, "unknown": 0, "pending": 0, "invalid": 0}
        for path in list(self.directory.glob("*.json"))[:10000]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                reservation, action, tokens = value["id"], value["action"], value["tokens"]
                if self._path(reservation) != path or type(tokens) is not int or tokens < 0:
                    raise ValueError("Invalid settlement intent")
                if action == "unknown":
                    result["unknown"] += 1
                elif action in {"settle", "release"}:
                    result["recovered" if self._apply(reservation, action, tokens) else "pending"] += 1
                else:
                    raise ValueError("Invalid settlement action")
            except (OSError, ValueError, KeyError, TypeError):
                result["invalid"] += 1
        if result["unknown"] or result["invalid"]:
            logger.warning("Quota reconciliation requires inspection: unknown=%s invalid=%s", result["unknown"], result["invalid"])
        return result


class QuotaRecoveryWorker:
    def __init__(self, quota: RecoverableQuota):
        self.quota = quota
        self.task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()

    async def start(self):
        if self.task is not None and not self.task.done():
            return
        self.stop_event.clear()
        self.task = asyncio.create_task(self._run(), name="quota-recovery")

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await self.task
            self.task = None

    async def _run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.quota.recover)
            except OSError:
                logger.error("Quota recovery spool unavailable")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=5)
            except TimeoutError:
                pass
