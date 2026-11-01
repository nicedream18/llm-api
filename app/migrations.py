"""Compatibility CLI for database migrations.

Usage: python -m app.migrations {status|upgrade|validate}
"""
from app.infrastructure.database.migrations import _cli

if __name__ == "__main__":
    _cli()
