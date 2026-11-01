from contextlib import contextmanager

from sqlalchemy import create_engine, text

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

    assert KbRepository().delete_doc_by_id("missing") is False
