"""Checksum-verified, serialized MySQL schema migration runner."""
from __future__ import annotations

import hashlib
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import text

from app.application.services.auth_service import hash_password
from app.config import config
from app.infrastructure.database.connection import engine

logger = logging.getLogger(__name__)
MIGRATION_DIR = Path(__file__).resolve().parents[3] / "docs" / "migrations"
_VERSION = re.compile(r"^(\d{3}_[a-z0-9_]+)\.sql$")


def sql_statements(script: str) -> list[str]:
    """Split application-owned migrations without splitting quoted literals.

    Migrations support standard statements and line/block comments. Stored
    procedures and DELIMITER directives are deliberately unsupported.
    """
    statements = []
    buffer = []
    quote = None
    index = 0
    while index < len(script):
        char = script[index]
        following = script[index:index + 2]
        if quote:
            buffer.append(char)
            if char == "\\" and index + 1 < len(script):
                index += 1
                buffer.append(script[index])
            elif char == quote:
                if index + 1 < len(script) and script[index + 1] == quote:
                    index += 1
                    buffer.append(script[index])
                else:
                    quote = None
        elif following == "--" or char == "#":
            end = script.find("\n", index)
            index = len(script) if end == -1 else end
            buffer.append("\n")
            continue
        elif following == "/*":
            end = script.find("*/", index + 2)
            if end == -1:
                raise ValueError("Unterminated SQL comment")
            index = end + 2
            buffer.append(" ")
            continue
        elif char in {"'", '"', "`"}:
            quote = char
            buffer.append(char)
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)
        index += 1
    if quote:
        raise ValueError("Unterminated SQL literal")
    remaining = "".join(buffer).strip()
    if remaining:
        statements.append(remaining)
    return statements


def execute_migration(db, path: Path) -> None:
    for statement in sql_statements(path.read_text(encoding="utf-8")):
        db.execute(text(statement))


def migration_files() -> list[tuple[str, Path, str]]:
    result = []
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        match = _VERSION.match(path.name)
        if not match:
            raise RuntimeError(f"Invalid migration filename: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append((match.group(1), path, digest))
    return result


def _ensure_column(db, table: str, column: str, definition: str) -> None:
    exists = db.execute(text("""SELECT 1 FROM information_schema.columns
        WHERE table_schema=DATABASE() AND table_name=:table_name AND column_name=:column_name LIMIT 1"""),
        {"table_name": table, "column_name": column}).first()
    if not exists:
        db.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"))


def _apply_compatibility_ddl(db) -> None:
    """Idempotent DDL for legacy installations; base tables must already exist."""
    table_exists = db.execute(text("""SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema=DATABASE() AND table_name IN ('request_logs','kb_tasks','kb_knowledge_bases')""")).scalar()
    if int(table_exists or 0) != 3:
        raise RuntimeError("Legacy schema is incomplete; initialize from docs/waliapi.sql before upgrading")
    db.execute(text("""CREATE TABLE IF NOT EXISTS admin_users (
        id VARCHAR(64) NOT NULL PRIMARY KEY, username VARCHAR(128) NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, status TINYINT NOT NULL DEFAULT 1,
        created_at VARCHAR(32) NOT NULL, updated_at VARCHAR(32) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))
    db.execute(text("""CREATE TABLE IF NOT EXISTS admin_audit_logs (
        id VARCHAR(64) NOT NULL PRIMARY KEY, username VARCHAR(128), action VARCHAR(128) NOT NULL,
        request_id VARCHAR(128), client_ip VARCHAR(64), success TINYINT NOT NULL DEFAULT 1,
        created_at VARCHAR(32) NOT NULL, KEY idx_admin_audit_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))
    db.execute(text("""CREATE TABLE IF NOT EXISTS api_key_quota_ledger (
        id VARCHAR(64) NOT NULL PRIMARY KEY, api_key_id VARCHAR(64) NOT NULL,
        request_id VARCHAR(128) NOT NULL UNIQUE, reserved_tokens BIGINT NOT NULL DEFAULT 0,
        actual_tokens BIGINT NOT NULL DEFAULT 0, released_tokens BIGINT NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL, created_at VARCHAR(32) NOT NULL, settled_at VARCHAR(32),
        KEY idx_quota_key (api_key_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))
    db.execute(text("""CREATE TABLE IF NOT EXISTS gateway_attempts (
        id VARCHAR(64) NOT NULL PRIMARY KEY, request_id VARCHAR(128) NOT NULL,
        attempt_no INT NOT NULL, channel_id VARCHAR(64), channel_name VARCHAR(128),
        status_code INT, error_type VARCHAR(64), error_message TEXT,
        duration_ms BIGINT NOT NULL DEFAULT 0, succeeded TINYINT NOT NULL DEFAULT 0,
        created_at VARCHAR(32) NOT NULL, KEY idx_attempt_request (request_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))
    for column, definition in {
        "protocol_type": "VARCHAR(32) NULL",
        "request_id": "VARCHAR(128) NULL",
        "endpoint": "VARCHAR(128) NULL",
        "attempt_count": "INT NOT NULL DEFAULT 1",
        "final_attempt": "INT NOT NULL DEFAULT 1",
        "stream_status": "VARCHAR(32) NULL",
        "usage_source": "VARCHAR(32) NULL",
        "client_disconnect": "TINYINT NOT NULL DEFAULT 0",
        "truncated": "TINYINT NOT NULL DEFAULT 0",
        "client_ip": "VARCHAR(64) NULL",
        "api_key_name": "VARCHAR(128) NULL",
        "channel_name": "VARCHAR(128) NULL",
        "upstream_model": "VARCHAR(128) NULL",
        "mode": "VARCHAR(32) NULL",
        "status_code": "INT NULL",
        "prompt_tokens": "BIGINT NOT NULL DEFAULT 0",
        "completion_tokens": "BIGINT NOT NULL DEFAULT 0",
        "total_tokens": "BIGINT NOT NULL DEFAULT 0",
        "duration_ms": "BIGINT NOT NULL DEFAULT 0",
        "risk_level": "VARCHAR(16) NOT NULL DEFAULT 'Clean'",
        "risk_score": "INT NOT NULL DEFAULT 0",
        "risk_summary": "TEXT NULL",
        "security_action": "VARCHAR(32) NOT NULL DEFAULT 'Allow'",
        "sanitized": "TINYINT NOT NULL DEFAULT 0",
        "blocked_reason": "TEXT NULL",
        "is_stream": "TINYINT NOT NULL DEFAULT 0",
        "is_retry": "TINYINT NOT NULL DEFAULT 0",
        "request_body": "MEDIUMTEXT NULL",
        "response_choices": "MEDIUMTEXT NULL",
        "trace_id": "VARCHAR(64) NULL",
        "created_at": "VARCHAR(32) NULL",
    }.items():
        _ensure_column(db, "request_logs", column, definition)
    for column, definition in {
        "payload": "MEDIUMTEXT NULL",
        "worker_id": "VARCHAR(128) NULL",
        "lease_until": "VARCHAR(32) NULL",
        "attempt_count": "INT NOT NULL DEFAULT 0",
        "started_at": "VARCHAR(32) NULL",
    }.items():
        _ensure_column(db, "kb_tasks", column, definition)
    for column, definition in {
        "status": "TINYINT NOT NULL DEFAULT 1",
        "embedding_model": "VARCHAR(128) NULL",
        "embedding_channel_id": "VARCHAR(64) NULL",
        "embedding_dim": "INT NOT NULL DEFAULT 0",
        "doc_count": "INT NOT NULL DEFAULT 0",
        "chunk_count": "INT NOT NULL DEFAULT 0",
        "total_tokens": "BIGINT NOT NULL DEFAULT 0",
        "index_status": "VARCHAR(32) NOT NULL DEFAULT 'none'",
    }.items():
        _ensure_column(db, "kb_knowledge_bases", column, definition)
    for column, definition in {
        "name": "VARCHAR(256) NULL",
        "pattern": "TEXT NULL",
        "action": "VARCHAR(32) NULL",
        "updated_at": "VARCHAR(32) NULL",
    }.items():
        _ensure_column(db, "security_builtin_rules", column, definition)
    for column, definition in {
        "name": "VARCHAR(256) NULL",
        "updated_at": "VARCHAR(32) NULL",
    }.items():
        _ensure_column(db, "security_custom_rules", column, definition)


def status() -> list[dict]:
    with engine.connect() as db:
        exists = db.execute(text("""SELECT 1 FROM information_schema.tables
            WHERE table_schema=DATABASE() AND table_name='schema_migrations' LIMIT 1""")).first()
        applied = {} if not exists else {row["version"]: row["checksum"] for row in db.execute(
            text("SELECT version, checksum FROM schema_migrations")).mappings().all()}
    return [{"version": version, "checksum": checksum, "applied": version in applied,
             "checksum_valid": version not in applied or applied[version] == checksum}
            for version, _path, checksum in migration_files()]


def validate() -> bool:
    rows = status()
    invalid = [row["version"] for row in rows if not row["checksum_valid"]]
    if invalid:
        raise RuntimeError("Migration checksum mismatch: " + ", ".join(invalid))
    return True


def apply_migrations() -> None:
    files = migration_files()
    with engine.connect() as lock_connection:
        acquired = lock_connection.execute(text("SELECT GET_LOCK('waliapi_schema_migrations', 30)")).scalar()
        if acquired != 1:
            raise RuntimeError("Could not acquire schema migration lock")
        try:
            with engine.begin() as db:
                db.execute(text("""CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(32) PRIMARY KEY, checksum VARCHAR(64) NOT NULL,
                    applied_at VARCHAR(32) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))
                applied = {row["version"]: row["checksum"] for row in db.execute(
                    text("SELECT version, checksum FROM schema_migrations")).mappings().all()}
            if files and applied and "001_baseline" not in applied:
                # Existing deployments may have changed before a version table existed.
                _apply_compatibility_ddl_with_transaction()
            for version, path, checksum in files:
                existing = applied.get(version)
                if existing:
                    if existing != checksum:
                        raise RuntimeError(f"Migration checksum mismatch for {version}")
                    continue
                logger.info("Applying database migration %s", version)
                with engine.begin() as db:
                    _apply_compatibility_ddl(db)
                    execute_migration(db, path)
                    db.execute(text("INSERT INTO schema_migrations (version, checksum, applied_at) VALUES (:version, :checksum, UTC_TIMESTAMP())"),
                               {"version": version, "checksum": checksum})
                applied[version] = checksum
            _bootstrap_admin()
        finally:
            lock_connection.execute(text("SELECT RELEASE_LOCK('waliapi_schema_migrations')"))


def _bootstrap_admin() -> None:
    password_hash = config.auth.admin_password_hash
    if not password_hash and config.auth.bootstrap_password:
        password_hash = hash_password(config.auth.bootstrap_password)
    if not password_hash:
        return
    with engine.begin() as db:
        found = db.execute(text("SELECT 1 FROM admin_users WHERE username=:username"),
                           {"username": config.auth.admin_username}).first()
        if not found:
            db.execute(text("""INSERT INTO admin_users
                (id, username, password_hash, status, created_at, updated_at)
                VALUES (UUID(), :username, :password_hash, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP())"""),
                       {"username": config.auth.admin_username, "password_hash": password_hash})


def _apply_compatibility_ddl_with_transaction() -> None:
    with engine.begin() as db:
        _apply_compatibility_ddl(db)


def _cli() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "upgrade":
        apply_migrations()
        print("Migrations applied")
    elif command == "validate":
        validate()
        print("Migration checksums valid")
    elif command == "status":
        for row in status():
            print(f"{row['version']} applied={row['applied']} checksum_valid={row['checksum_valid']}")
    else:
        raise SystemExit("Usage: python -m app.infrastructure.database.migrations [status|upgrade|validate]")


if __name__ == "__main__":
    _cli()
