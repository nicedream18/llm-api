from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.mcp_audit_repo import McpAuditRepository


def test_mcp_audit_repository_persists_redacted_call_metadata():
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/012_mcp_audit.sql"))
    repo = McpAuditRepository(engine)
    repo.record(
        request_id="req-1", principal_type="mcp", principal_id="mcp-1",
        tool_name="list_knowledge_bases", success=True, error_type=None, duration_ms=7,
    )
    rows = repo.list()
    assert rows[0]["tool_name"] == "list_knowledge_bases"
    assert rows[0]["success"] == 1
    assert "secret" not in str(rows)
    assert "mcp_audit_logs" in inspect(engine).get_table_names()
