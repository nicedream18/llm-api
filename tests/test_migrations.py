import hashlib
from pathlib import Path


def test_baseline_migration_has_stable_checksum_input():
    path = Path("docs/migrations/001_baseline.sql")
    assert hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_text().startswith("-- Baseline migration")


def test_sql_splitter_keeps_literals_and_removes_comments():
    from app.infrastructure.database.migrations import sql_statements

    script = """
    -- ignored ;
    CREATE TABLE example (value TEXT);
    /* block ; */ INSERT INTO example VALUES ('a;b -- still a literal');
    INSERT INTO example VALUES ('it''s; quoted'); # ignored
    """
    parts = sql_statements(script)
    assert len(parts) == 3
    assert "'a;b -- still a literal'" in parts[1]
    assert "'it''s; quoted'" in parts[2]


def test_sql_migration_executes_instead_of_only_recording_version(tmp_path):
    from sqlalchemy import create_engine, text

    from app.infrastructure.database.migrations import execute_migration

    script = tmp_path / "009_example.sql"
    script.write_text(
        "CREATE TABLE example (value TEXT); INSERT INTO example VALUES ('first;second');"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        execute_migration(connection, script)
        assert (
            connection.execute(text("SELECT value FROM example")).scalar_one()
            == "first;second"
        )
    engine.dispose()


def test_invalid_sql_literals_are_rejected_before_execution():
    import pytest

    from app.infrastructure.database.migrations import sql_statements

    for script in ("SELECT 'missing", "/* missing"):
        with pytest.raises(ValueError):
            sql_statements(script)
