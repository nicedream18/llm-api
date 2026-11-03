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


def test_sql_splitter_accepts_unterminated_comment_at_eof():
    from app.infrastructure.database.migrations import sql_statements

    assert sql_statements("SELECT 1; -- trailing comment") == ["SELECT 1"]


def test_execute_migration_normalizes_sqlite_index_guard_for_mysql(tmp_path):
    from sqlalchemy import create_engine, inspect

    from app.infrastructure.database import migrations

    script = tmp_path / "019_index.sql"
    script.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY); CREATE INDEX IF NOT EXISTS idx_sample ON sample (id);", encoding="utf-8")
    engine = create_engine("sqlite://")

    class MysqlDialect:
        name = "mysql"

    with engine.begin() as connection:
        class FakeConnection:
            dialect = MysqlDialect()

            @staticmethod
            def execute(statement):
                return connection.execute(statement)

        # Execute against SQLite while selecting the MySQL normalization path.
        migrations.execute_migration(FakeConnection(), script)
    assert inspect(engine).has_table("sample")


def test_migration_files_rejects_invalid_filename(monkeypatch, tmp_path):
    from app.infrastructure.database import migrations

    (tmp_path / "bad.sql").write_text("SELECT 1", encoding="utf-8")
    monkeypatch.setattr(migrations, "MIGRATION_DIR", tmp_path)
    import pytest

    with pytest.raises(RuntimeError, match="Invalid migration filename"):
        migrations.migration_files()


def test_validate_reports_checksum_mismatch(monkeypatch):
    from app.infrastructure.database import migrations

    monkeypatch.setattr(
        migrations,
        "status",
        lambda: [{"version": "001_baseline", "checksum_valid": False}],
    )
    import pytest

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrations.validate()


def test_migration_files_include_mcp_session_persistence():
    from app.infrastructure.database import migrations

    versions = [version for version, _path, _checksum in migrations.migration_files()]
    assert "018_mcp_sessions" in versions


def test_high_entropy_rule_migration_registers_rule_idempotently(tmp_path):
    from sqlalchemy import create_engine, text

    from app.infrastructure.database.migrations import execute_migration

    migration = Path("docs/migrations/027_security_high_entropy_rule.sql")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE security_builtin_rules (
            id TEXT PRIMARY KEY, rule_id TEXT UNIQUE, category TEXT, severity TEXT,
            title TEXT, name TEXT, description TEXT, pattern TEXT, action TEXT,
            enabled INTEGER, created_at TEXT, updated_at TEXT
        )""")
        connection.connection.create_function("UTC_TIMESTAMP", 0, lambda: "now")
        execute_migration(connection, migration)
        execute_migration(connection, migration)
        row = connection.execute(text(
            "SELECT rule_id, severity, action, enabled FROM security_builtin_rules"
        )).one()

    assert tuple(row) == ("credential_high_entropy", "medium", "warn", 1)
    engine.dispose()
