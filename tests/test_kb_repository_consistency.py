from contextlib import contextmanager

from sqlalchemy import create_engine, text

from app.application.errors import ApplicationError
from app.infrastructure.repositories import kb_repo as kb_repo_module
from app.infrastructure.repositories.kb_repo import KbRepository


def test_delete_document_recounts_kb_and_marks_vector_index_stale(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE kb_knowledge_bases (
            id TEXT PRIMARY KEY, doc_count INTEGER, chunk_count INTEGER,
            total_tokens INTEGER, index_status TEXT, updated_at TEXT)"""))
        connection.execute(text("""CREATE TABLE kb_documents (
            id TEXT PRIMARY KEY, kb_id TEXT, status TEXT, total_tokens INTEGER)"""))
        connection.execute(text("""CREATE TABLE kb_chunks (
            id TEXT PRIMARY KEY, doc_id TEXT, kb_id TEXT)"""))
        connection.execute(text("""CREATE TABLE kb_tasks (
            id TEXT PRIMARY KEY, kb_id TEXT, doc_id TEXT, status TEXT)"""))
        connection.execute(text("INSERT INTO kb_knowledge_bases VALUES ('kb-1', 2, 3, 30, 'ready', '')"))
        connection.execute(text("INSERT INTO kb_documents VALUES ('doc-1', 'kb-1', 'ready', 10), ('doc-2', 'kb-1', 'ready', 20)"))
        connection.execute(text("INSERT INTO kb_chunks VALUES ('c1', 'doc-1', 'kb-1'), ('c2', 'doc-1', 'kb-1'), ('c3', 'doc-2', 'kb-1')"))
        connection.execute(text("INSERT INTO kb_tasks VALUES ('t1', 'kb-1', 'doc-1', 'pending')"))

    @contextmanager
    def sqlite_session():
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(kb_repo_module, "get_db", sqlite_session)

    assert KbRepository().delete_doc_by_id("doc-1") is True
    with engine.connect() as connection:
        kb = connection.execute(text("SELECT * FROM kb_knowledge_bases WHERE id='kb-1'")).mappings().one()
        assert (kb["doc_count"], kb["chunk_count"], kb["total_tokens"], kb["index_status"]) == (1, 1, 20, "stale")
        assert connection.execute(text("SELECT COUNT(*) FROM kb_chunks WHERE doc_id='doc-1'")).scalar_one() == 0
        assert connection.execute(text("SELECT status FROM kb_tasks WHERE id='t1'")).scalar_one() == "cancelled"

    assert KbRepository().delete_doc_by_id("missing") is False


def test_delete_document_rejects_running_task_without_mutating_rows(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE kb_knowledge_bases (id TEXT PRIMARY KEY, doc_count INTEGER, chunk_count INTEGER, total_tokens INTEGER, index_status TEXT, updated_at TEXT)"))
        connection.execute(text("CREATE TABLE kb_documents (id TEXT PRIMARY KEY, kb_id TEXT, status TEXT, total_tokens INTEGER)"))
        connection.execute(text("CREATE TABLE kb_chunks (id TEXT PRIMARY KEY, doc_id TEXT, kb_id TEXT)"))
        connection.execute(text("CREATE TABLE kb_tasks (id TEXT PRIMARY KEY, kb_id TEXT, doc_id TEXT, status TEXT)"))
        connection.execute(text("INSERT INTO kb_knowledge_bases VALUES ('kb-1', 1, 1, 10, 'ready', '')"))
        connection.execute(text("INSERT INTO kb_documents VALUES ('doc-1', 'kb-1', 'processing', 0)"))
        connection.execute(text("INSERT INTO kb_chunks VALUES ('c1', 'doc-1', 'kb-1')"))
        connection.execute(text("INSERT INTO kb_tasks VALUES ('t1', 'kb-1', 'doc-1', 'running')"))

    @contextmanager
    def sqlite_session():
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(kb_repo_module, "get_db", sqlite_session)

    try:
        KbRepository().delete_doc_by_id("doc-1")
    except ApplicationError as exc:
        assert exc.code == "task_running"
    else:
        raise AssertionError("running document task must block deletion")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM kb_documents WHERE id='doc-1'")).scalar_one() == 1
        assert connection.execute(text("SELECT status FROM kb_tasks WHERE id='t1'")).scalar_one() == "running"


def test_delete_knowledge_base_cleans_all_owned_rows_in_one_transaction(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for table, columns in {
            "kb_knowledge_bases": "id TEXT PRIMARY KEY",
            "kb_tasks": "id TEXT, kb_id TEXT, status TEXT",
            "kb_sources": "id TEXT, kb_id TEXT",
            "kb_index_meta": "kb_id TEXT",
            "kb_conversations": "id TEXT, kb_id TEXT",
            "kb_chunks": "id TEXT, kb_id TEXT",
            "kb_documents": "id TEXT, kb_id TEXT",
        }.items():
            connection.execute(text(f"CREATE TABLE {table} ({columns})"))
        connection.execute(text("INSERT INTO kb_knowledge_bases VALUES ('kb-1')"))
        connection.execute(text("INSERT INTO kb_tasks VALUES ('row-1', 'kb-1', 'pending')"))
        for table in ("kb_sources", "kb_conversations", "kb_chunks", "kb_documents"):
            connection.execute(text(f"INSERT INTO {table} VALUES ('row-1', 'kb-1')"))
        connection.execute(text("INSERT INTO kb_index_meta VALUES ('kb-1')"))

    @contextmanager
    def sqlite_session():
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(kb_repo_module, "get_db", sqlite_session)
    KbRepository().delete_kb_by_id("kb-1")

    with engine.connect() as connection:
        for table in ("kb_knowledge_bases", "kb_tasks", "kb_sources", "kb_index_meta", "kb_conversations", "kb_chunks", "kb_documents"):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_delete_knowledge_base_is_blocked_while_worker_is_running(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for table, columns in {
            "kb_knowledge_bases": "id TEXT PRIMARY KEY",
            "kb_tasks": "id TEXT, kb_id TEXT, status TEXT",
            "kb_sources": "id TEXT, kb_id TEXT",
            "kb_index_meta": "kb_id TEXT",
            "kb_conversations": "id TEXT, kb_id TEXT",
            "kb_chunks": "id TEXT, kb_id TEXT",
            "kb_documents": "id TEXT, kb_id TEXT",
        }.items():
            connection.execute(text(f"CREATE TABLE {table} ({columns})"))
        connection.execute(text("INSERT INTO kb_knowledge_bases VALUES ('kb-1')"))
        connection.execute(text("INSERT INTO kb_tasks VALUES ('t1', 'kb-1', 'running')"))

    @contextmanager
    def sqlite_session():
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(kb_repo_module, "get_db", sqlite_session)

    try:
        KbRepository().delete_kb_by_id("kb-1")
    except ApplicationError as exc:
        assert exc.code == "task_running"
    else:
        raise AssertionError("running knowledge task must block deletion")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM kb_knowledge_bases WHERE id='kb-1'")).scalar_one() == 1
        assert connection.execute(text("SELECT status FROM kb_tasks WHERE id='t1'")).scalar_one() == "running"


def test_task_claim_cancels_work_for_a_deleted_document(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE kb_knowledge_bases (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE kb_documents (id TEXT PRIMARY KEY, kb_id TEXT)"))
        connection.execute(text("""CREATE TABLE kb_tasks (
            id TEXT PRIMARY KEY, kb_id TEXT, doc_id TEXT, task_type TEXT,
            status TEXT, created_at TEXT, completed_at TEXT)"""))
        connection.execute(text("INSERT INTO kb_knowledge_bases VALUES ('kb-1')"))
        connection.execute(text("INSERT INTO kb_tasks VALUES ('task-1', 'kb-1', 'missing-doc', 'reindex', 'pending', '2026-01-01', NULL)"))

    @contextmanager
    def sqlite_session():
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(kb_repo_module, "get_db", sqlite_session)

    assert KbRepository().claim_next_task("worker", 30) is None
    with engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM kb_tasks WHERE id='task-1'")).scalar_one() == "cancelled"
