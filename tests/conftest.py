"""Shared fixtures and helpers for the repo's test suites."""

from __future__ import annotations

from pathlib import Path

import psycopg
from testcontainers.postgres import PostgresContainer

SCHEMA_PATH = Path(__file__).parent.parent / "sql" / "schema.sql"


def normalize_pg_url(raw: str) -> str:
    """Strip the SQLAlchemy +psycopg2 suffix so libpq-style clients can connect."""
    return raw.replace("postgresql+psycopg2", "postgresql")


def apply_schema(container: PostgresContainer) -> str:
    """Apply `sql/schema.sql` to the running container and return its libpq URL."""
    url = normalize_pg_url(container.get_connection_url())
    with psycopg.connect(url) as conn:
        conn.execute(SCHEMA_PATH.read_text())
        conn.commit()
    return url
