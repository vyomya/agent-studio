"""PostgreSQL persistence for validated gallery pages."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Page:
    id: int
    spec: str
    html: str
    attempts: int
    created_at: datetime
    parent_id: int | None
    version: int
    refine_instruction: str | None = None


def database_url() -> str:
    """Return the app DB URL, falling back to the shared test DB for tests."""
    url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_TEST")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def connect():
    return psycopg.connect(database_url(), row_factory=dict_row)


def initialize_database() -> None:
    """Create the gallery table if it does not yet exist."""
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                id BIGSERIAL PRIMARY KEY,
                spec TEXT NOT NULL,
                html TEXT NOT NULL,
                attempts INTEGER NOT NULL CHECK (attempts BETWEEN 1 AND 3),
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                parent_id BIGINT REFERENCES pages(id) ON DELETE RESTRICT,
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                refine_instruction TEXT
            )
            """
        )


def save_page(
    spec: str,
    html: str,
    attempts: int,
    *,
    parent_id: int | None = None,
    version: int = 1,
    refine_instruction: str | None = None,
) -> Page:
    """Persist a validated page and return its durable record."""
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO pages (spec, html, attempts, parent_id, version, refine_instruction)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, spec, html, attempts, created_at, parent_id, version, refine_instruction
            """,
            (spec, html, attempts, parent_id, version, refine_instruction),
        ).fetchone()
    return Page(**row)


def list_pages() -> list[Page]:
    """Return gallery pages newest first, with stable ordering for tied timestamps."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, spec, html, attempts, created_at, parent_id, version, refine_instruction
            FROM pages ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return [Page(**row) for row in rows]


def get_page(page_id: int) -> Page | None:
    """Return one saved gallery page, or ``None`` when it does not exist."""
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, spec, html, attempts, created_at, parent_id, version, refine_instruction
            FROM pages WHERE id = %s
            """,
            (page_id,),
        ).fetchone()
    return Page(**row) if row is not None else None
