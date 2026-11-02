
import asyncio
import threading

import pytest

from app.application.services.kb_worker import KnowledgeTaskWorker


class FakeRepository:
    def __init__(self):
        self.failure = None
        self.recovered = False
        self.claimed = []
        self.claimed_event = threading.Event()

    def find_chunk_by_doc_id(self, _doc_id):
        return ["chunk"]

    def recover_expired_tasks(self):
        self.recovered = True

    def claim_next_task(self, worker_id, lease_seconds):
        self.claimed.append((worker_id, lease_seconds))
        self.claimed_event.set()

    def fail_or_retry_task(self, task_id, message, max_attempts, lease):
        assert lease.generation == 1
        self.failure = (task_id, message, max_attempts)


class FakeKbService:
    def __init__(self, fail=False):
        self.called = []
        self.fail = fail

    def run_import_pipeline(self, *args, lease):
        assert lease.worker_id == "worker-1"
        self.called.append(("import", args))
        if self.fail:
            raise RuntimeError("failure")

    def run_reindex_pipeline(self, *args, lease):
        assert lease.worker_id == "worker-1"
        self.called.append(("reindex", args))
        if self.fail:
            raise RuntimeError("failure")


def test_worker_dispatches_reindex_with_claimed_task_id():
    repo = FakeRepository()
    service = FakeKbService()
    worker = KnowledgeTaskWorker(service, repo)
    worker._execute({"worker_id": "worker-1", "attempt_count": 1, "id": "task-1", "kb_id": "kb-1", "doc_id": "doc-1", "task_type": "reindex"})
    assert service.called == [("reindex", ("kb-1", "doc-1", "task-1", ["chunk"]))]
    assert repo.failure is None


def test_worker_retries_failed_task():
    repo = FakeRepository()
    worker = KnowledgeTaskWorker(FakeKbService(fail=True), repo)
    worker._execute({"worker_id": "worker-1", "attempt_count": 1, "id": "task-1", "kb_id": "kb-1", "doc_id": "doc-1", "task_type": "reindex"})
    assert repo.failure and repo.failure[0] == "task-1"


def test_worker_dispatches_import_payload_to_import_pipeline():
    repo = FakeRepository()
    service = FakeKbService()
    worker = KnowledgeTaskWorker(service, repo, worker_id="worker-1")

    worker._execute({"worker_id": "worker-1", "attempt_count": 1,
        "id": "task-2", "kb_id": "kb-2", "doc_id": "doc-2", "task_type": "import",
        "payload": {"filename": "guide.md", "content": "encoded", "file_type": "md", "source_type": "git"},
    })

    kind, args = service.called[0]
    assert kind == "import"
    assert args[0:3] == ("kb-2", "doc-2", "task-2")
    assert args[3].filename == "guide.md"
    assert args[3].content == "encoded" and args[3].file_type == "md"
    assert args[3].source_type == "git"
    assert repo.failure is None


def test_worker_rejects_unknown_task_and_records_retry_state():
    repo = FakeRepository()
    worker = KnowledgeTaskWorker(FakeKbService(), repo)

    worker._execute({"worker_id": "worker-1", "attempt_count": 1, "id": "task-3", "task_type": "unknown"})

    assert repo.failure is not None
    assert repo.failure[0] == "task-3"
    assert "Unsupported task type" in repo.failure[1]


@pytest.mark.asyncio
async def test_worker_start_recovers_tasks_and_stops_idle_loop():
    repo = FakeRepository()
    worker = KnowledgeTaskWorker(FakeKbService(), repo, worker_id="worker-1")

    await worker.start()
    assert worker.running
    assert await asyncio.to_thread(repo.claimed_event.wait, 1)
    await worker.stop()

    assert repo.recovered is True
    assert repo.claimed
    assert repo.claimed[0][0] == "worker-1"
    assert worker.running is False
