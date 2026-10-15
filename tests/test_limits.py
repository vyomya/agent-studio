"""Tests for the PostgreSQL-backed model allowance guard."""

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
    connect, _, cursor = install_fake_database(monkeypatch, [(1,), (1, 1)])
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "3")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "9")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "30")

    assert limits.check_model_limits("192.0.2.5") is None

    connect.assert_called_once_with("postgresql://test/db")
    assert len(cursor.statements) == 3
    assert "CREATE TABLE IF NOT EXISTS model_limits" in cursor.statements[0][0]
    assert cursor.statements[1][1][0] == ""
    assert cursor.statements[2][1][0] == "192.0.2.5"
    assert cursor.statements[1][1][1].hour == 0
    assert cursor.statements[2][1][1].minute == 0


@pytest.mark.parametrize(
    ("hour_count", "day_count", "hour_limit", "day_limit"),
    [(2, 1, "1", "20"), (1, 3, "5", "2")],
)
def test_visitor_limit_returns_friendly_429_before_model_call(
    monkeypatch, hour_count, day_count, hour_limit, day_limit
):
    _, connection, _ = install_fake_database(monkeypatch, [(1,), (hour_count, day_count)])
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

    assert len(cursor.statements) == 2  # DDL and global counter only; no visitor upsert.
    assert connection.exit_exception is not None
    model_call.assert_not_called()


def test_generation_and_refinement_share_the_same_guard(monkeypatch):
    _, _, cursor = install_fake_database(monkeypatch, [(1,), (1, 1), (2,), (2, 2)])
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")

    # Both request types use the exact same guard and visitor key.
    for operation in ("generate", "refine"):
        limits.check_model_limits("198.51.100.4")

    visitor_params = [params for _, params in cursor.statements if params and params[0] == "198.51.100.4"]
    assert len(visitor_params) == 2


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
        with pytest.raises(limits.LimitExceeded) as caught:
            with limits.model_request_slot("192.0.2.12"):
                model_call()

    assert caught.value.status_code == 429
    assert caught.value.detail == "Model allowance limit exceeded. Please try again later."
    assert check_limits.call_args_list == [(("192.0.2.11",),)]
    model_call.assert_called_once_with()
    assert "pg_try_advisory_lock" in first_cursor.statements[0][0]
    assert first_cursor.statements[0][1] == (limits._GENERATION_LOCK_KEY,)
    assert "pg_try_advisory_lock" in second_cursor.statements[0][0]
    first_connection.commit.assert_called_once_with()
    second_connection.commit.assert_called_once_with()
    first_connection.close.assert_called_once_with()
    second_connection.close.assert_called_once_with()
