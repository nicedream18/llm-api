
from app.application.services.kb_worker import KnowledgeTaskWorker


class FakeRepository:
    def __init__(self):
        self.failure = None

    def find_chunk_by_doc_id(self, _doc_id):
        return ["chunk"]

    def fail_or_retry_task(self, task_id, message, max_attempts):
        self.failure = (task_id, message, max_attempts)


class FakeKbService:
    def __init__(self, fail=False):
        self.called = []
        self.fail = fail

    def run_reindex_pipeline(self, *args):
        self.called.append(args)
        if self.fail:
            raise RuntimeError("failure")


def test_worker_dispatches_reindex_with_claimed_task_id():
    repo = FakeRepository()
    service = FakeKbService()
    worker = KnowledgeTaskWorker(service, repo)
    worker._execute({"id": "task-1", "kb_id": "kb-1", "doc_id": "doc-1", "task_type": "reindex"})
    assert service.called == [("kb-1", "doc-1", "task-1", ["chunk"])]
    assert repo.failure is None


def test_worker_retries_failed_task():
    repo = FakeRepository()
    worker = KnowledgeTaskWorker(FakeKbService(fail=True), repo)
    worker._execute({"id": "task-1", "kb_id": "kb-1", "doc_id": "doc-1", "task_type": "reindex"})
    assert repo.failure and repo.failure[0] == "task-1"
