from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.mcp_session_repo import McpSessionRepository


def test_mcp_session_repository_persists_owner_ttl_and_replay_window():
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/018_mcp_sessions.sql"))
        execute_migration(db, Path("docs/migrations/018_mcp_sessions.sql"))
    first = McpSessionRepository(engine)
    second = McpSessionRepository(engine)
    owner = ("mcp", "principal-1")
    first.create("session-1", owner, 3600)
    assert second.validate("session-1", owner, 3600)
    assert not second.validate("session-1", ("mcp", "other"), 3600)

    for index in range(1, 5):
        assert first.append_event("session-1", {"jsonrpc": "2.0", "method": "message", "params": {"index": index}}, max_events=3) == index
    replayed = second.replay("session-1", owner, after_event_id=1)
    assert [item["event_id"] for item in replayed] == [2, 3, 4]
    assert [item["payload"]["params"]["index"] for item in replayed] == [2, 3, 4]
    assert second.replay("session-1", ("mcp", "other"), 0) == []
    assert second.delete("session-1") is True
    assert second.replay("session-1", owner, 0) == []
    assert inspect(engine).has_table("mcp_session_events")
