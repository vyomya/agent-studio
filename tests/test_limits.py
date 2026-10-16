"""Tests for the PostgreSQL-backed model allowance guard."""

import os
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from unittest.mock import Mock

import pytest

from app import limits


class FakeCursor:
    def __init__(self, returned_rows):
        self.returned_rows = iter(returned_rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return next(self.returned_rows)


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.exit_exception = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exit_exception = exc
        return False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        pass

    def close(self):
        pass


def install_fake_database(monkeypatch, returned_rows):
    cursor = FakeCursor(returned_rows)
    connection = FakeConnection(cursor)
    connect = Mock(return_value=connection)
    monkeypatch.setattr(limits.psycopg, "connect", connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")
    return connect, connection, cursor


def test_check_model_limits_uses_configured_windows_and_allows_request(monkeypatch):
    connect, _, cursor = install_fake_database(monkeypatch, [(1,), (1, 1), (1,)])
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "3")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "9")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "30")

    assert limits.check_model_limits("192.0.2.5") is None

    connect.assert_called_once_with("postgresql://test/db")
    assert len(cursor.statements) == 5
    assert "CREATE TABLE IF NOT EXISTS model_limits" in cursor.statements[0][0]
    assert "pg_advisory_xact_lock" in cursor.statements[1][0]
    assert cursor.statements[2][1][0] == ""
    assert cursor.statements[3][1][0] == "192.0.2.5"
    assert cursor.statements[2][1][1].hour == 0
    assert cursor.statements[3][1][1].minute == 0
    assert "SUM(day_count)" in cursor.statements[4][0]
    assert cursor.statements[4][1][0] == "192.0.2.5"


@pytest.mark.parametrize(
    ("hour_count", "day_count", "hour_limit", "day_limit"),
    [(2, 1, "1", "20"), (1, 3, "5", "2")],
)
def test_visitor_limit_returns_friendly_429_before_model_call(
    monkeypatch, hour_count, day_count, hour_limit, day_limit
):
    _, connection, _ = install_fake_database(monkeypatch, [(1,), (hour_count, day_count), (day_count,)])
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", hour_limit)
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", day_limit)
    model_call = Mock()

    with pytest.raises(limits.LimitExceeded) as caught:
        limits.check_model_limits("192.0.2.8")
        model_call()

    assert caught.value.status_code == 429
    assert caught.value.detail == "Model allowance limit exceeded. Please try again later."
    assert connection.exit_exception is caught.value
    model_call.assert_not_called()


def test_global_limit_returns_429_without_updating_visitor_or_calling_model(monkeypatch):
    _, connection, cursor = install_fake_database(monkeypatch, [(2,)])
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "1")
    model_call = Mock()

    with pytest.raises(limits.LimitExceeded):
        limits.check_model_limits("192.0.2.9")
        model_call()

    assert len(cursor.statements) == 3  # DDL, visitor lock, global counter; no visitor upsert.
    assert connection.exit_exception is not None
    model_call.assert_not_called()


def test_generation_and_refinement_share_the_same_guard(monkeypatch):
    _, _, cursor = install_fake_database(
        monkeypatch, [(1,), (1, 1), (1,), (2,), (2, 2), (2,)]
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")

    # Both request types use the exact same guard and visitor key.
    for operation in ("generate", "refine"):
        limits.check_model_limits("198.51.100.4")

    visitor_params = [params for _, params in cursor.statements if params and params[0] == "198.51.100.4"]
    assert len(visitor_params) == 6


def test_global_daily_default_matches_model_allowance(monkeypatch):
    monkeypatch.delenv("GLOBAL_MODEL_DAILY_LIMIT", raising=False)

    assert limits._positive_limit("GLOBAL_MODEL_DAILY_LIMIT", 40) == 40


def test_real_database_daily_limit_spans_six_hour_windows(monkeypatch):
    database_url = os.getenv("DATABASE_URL_TEST")
    if not database_url:
        pytest.skip("DATABASE_URL_TEST is not configured")

    visitor_id = f"daily-limit-integration-{uuid4()}"
    start = datetime(2026, 1, 5, 6, tzinfo=timezone.utc)
    day = start.date()
    global_day_window = datetime.combine(day, time.min)

    # Keep this integration test isolated from other test-database activity.
    with limits.psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(limits._CREATE_TABLE)
            cursor.execute(
                """
                SELECT global_day_count FROM model_limits
                WHERE visitor_ip = %s AND hour_window = %s AND day_date = %s
                """,
                ("", global_day_window, day),
            )
            previous_global = cursor.fetchone()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")
    accepted = rejected = 0
    try:
        for hour_offset in range(6):
            fixed_now = start + timedelta(hours=hour_offset)

            class FixedDateTime:
                @staticmethod
                def now(tz=None):
                    return fixed_now

                combine = staticmethod(datetime.combine)

            monkeypatch.setattr(limits, "datetime", FixedDateTime)
            for _ in range(5):
                if accepted < 20:
                    limits.check_model_limits(visitor_id)
                    accepted += 1
                else:
                    with pytest.raises(limits.LimitExceeded) as caught:
                        limits.check_model_limits(visitor_id)
                    assert caught.value.status_code == 429
                    assert caught.value.detail == (
                        "Model allowance limit exceeded. Please try again later."
                    )
                    rejected += 1

        assert accepted == 20
        assert rejected == 10
    finally:
        # Remove test visitor rows and restore the pre-existing global counter.
        with limits.psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM model_limits WHERE visitor_ip = %s AND day_date = %s",
                    (visitor_id, day),
                )
                if previous_global is None:
                    cursor.execute(
                        "DELETE FROM model_limits WHERE visitor_ip = %s AND hour_window = %s AND day_date = %s",
                        ("", global_day_window, day),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE model_limits SET global_day_count = %s
                        WHERE visitor_ip = %s AND hour_window = %s AND day_date = %s
                        """,
                        (previous_global[0], "", global_day_window, day),
                    )


def test_invalid_visitor_id_is_rejected_before_database_or_model(monkeypatch):
    connect = Mock()
    monkeypatch.setattr(limits.psycopg, "connect", connect)
    model_call = Mock()

    with pytest.raises(ValueError, match="non-empty"):
        limits.check_model_limits("")
        model_call()

    connect.assert_not_called()
    model_call.assert_not_called()


def test_missing_database_url_fails_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    connect = Mock()
    monkeypatch.setattr(limits.psycopg, "connect", connect)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        limits.check_model_limits("192.0.2.10")

    connect.assert_not_called()


def test_model_request_slot_rejects_concurrent_request_before_limits_or_model(monkeypatch):
    first_cursor = FakeCursor([(True,)])
    second_cursor = FakeCursor([(False,)])
    first_connection = FakeConnection(first_cursor)
    second_connection = FakeConnection(second_cursor)
    first_connection.commit = Mock()
    second_connection.commit = Mock()
    first_connection.close = Mock()
    second_connection.close = Mock()
    connect = Mock(side_effect=[first_connection, second_connection])
    monkeypatch.setattr(limits.psycopg, "connect", connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")
    check_limits = Mock()
    monkeypatch.setattr(limits, "check_model_limits", check_limits)
    model_call = Mock()

    with limits.model_request_slot("192.0.2.11"):
        model_call()
        with pytest.raises(limits.ModelBusy) as caught:
            with limits.model_request_slot("192.0.2.12"):
                model_call()

    assert caught.value.status_code == 503
    assert caught.value.detail == "The service is currently busy, please try again later."
    assert check_limits.call_args_list == [(("192.0.2.11",),)]
    model_call.assert_called_once_with()
    assert "pg_try_advisory_lock" in first_cursor.statements[0][0]
    assert first_cursor.statements[0][1] == (limits._GENERATION_LOCK_KEY,)
    assert "pg_try_advisory_lock" in second_cursor.statements[0][0]
    first_connection.commit.assert_called_once_with()
    second_connection.commit.assert_called_once_with()
    first_connection.close.assert_called_once_with()
    second_connection.close.assert_called_once_with()
