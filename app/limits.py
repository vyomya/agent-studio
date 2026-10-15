"""PostgreSQL-backed model allowance limits.

Call check_model_limits before starting any model request. The helper uses one
transaction for visitor and global counters, so a rejected call consumes
neither allowance.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timezone

import psycopg
from fastapi import HTTPException

_DETAIL = "Model allowance limit exceeded. Please try again later."
_GLOBAL_VISITOR = ""  # Empty visitor IDs are rejected; reserve this row for the global counter.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS model_limits (
    visitor_ip TEXT NOT NULL,
    hour_window TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    day_date DATE NOT NULL,
    hour_count INT NOT NULL DEFAULT 0,
    day_count INT NOT NULL DEFAULT 0,
    global_day_count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (visitor_ip, hour_window, day_date)
)
"""


class LimitExceeded(HTTPException):
    """Raised when a configured visitor or global model limit is reached."""

    def __init__(self) -> None:
        super().__init__(status_code=429, detail=_DETAIL)


def _positive_limit(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def check_model_limits(visitor_id: str) -> None:
    """Atomically account for one model request or raise an HTTP 429.

    visitor_id is normally the requester's IP address. Generation and refine
    handlers must call this same helper before invoking the model. Counters
    use UTC windows. The atomic upsert on the global sentinel row serializes
    daily-cap decisions across visitors.
    """
    if not visitor_id or visitor_id == _GLOBAL_VISITOR:
        raise ValueError("visitor_id must be a non-empty visitor identifier")

    per_hour = _positive_limit("MODEL_LIMIT_PER_HOUR", 5)
    per_day = _positive_limit("MODEL_LIMIT_PER_DAY", 20)
    global_per_day = _positive_limit("GLOBAL_MODEL_DAILY_LIMIT", 1000)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured to enforce model limits")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    day = now.date()
    hour_window = now.replace(minute=0, second=0, microsecond=0)
    global_day_window = datetime.combine(day, time.min)

    # Raising inside the connection context rolls back both upserts. A visitor
    # rejected at their cap does not spend a global request either.
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_CREATE_TABLE)
            cursor.execute(
                """
                INSERT INTO model_limits
                    (visitor_ip, hour_window, day_date, hour_count, day_count, global_day_count)
                VALUES (%s, %s, %s, 0, 0, 1)
                ON CONFLICT (visitor_ip, hour_window, day_date) DO UPDATE
                    SET global_day_count = model_limits.global_day_count + 1
                RETURNING global_day_count
                """,
                (_GLOBAL_VISITOR, global_day_window, day),
            )
            global_count = cursor.fetchone()[0]
            if global_count > global_per_day:
                raise LimitExceeded()

            cursor.execute(
                """
                INSERT INTO model_limits
                    (visitor_ip, hour_window, day_date, hour_count, day_count, global_day_count)
                VALUES (%s, %s, %s, 1, 1, 0)
                ON CONFLICT (visitor_ip, hour_window, day_date) DO UPDATE
                    SET hour_count = model_limits.hour_count + 1,
                        day_count = model_limits.day_count + 1
                RETURNING hour_count, day_count
                """,
                (visitor_id, hour_window, day),
            )
            hour_count, day_count = cursor.fetchone()
            if hour_count > per_hour or day_count > per_day:
                raise LimitExceeded()
