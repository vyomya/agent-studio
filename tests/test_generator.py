"""Tests for the core generator implementation.

The real ``Generator`` class reads configuration from environment variables and
instantiates provider objects.  For unit tests we provide a small factory that returns a
custom ``MockProvider`` which reads separate ``MOCK_RESPONSE_<NAME>`` variables for the
primary and fallback providers.  This allows us to simulate success, specific HTTP error
codes and timeouts without any network traffic.
"""

import os
import json
import pytest

from app.generator import Generator, GeneratorError, GeneratorConfigError, Provider


class TestMockProvider(Provider):
    """Mock provider that picks its response from ``MOCK_RESPONSE_<NAME>`` env vars.

    ``name`` is the identifier passed to the factory (e.g., ``"primary"`` or
    ``"fallback"``).  The environment variable ``MOCK_RESPONSE_<NAME>.upper()`` should contain
    a JSON string with ``status`` and optional ``content`` fields, or the literal string
    ``timeout`` to simulate a request timeout.
    """

    def __init__(self, base_url: str, api_key: str, name: str = "primary") -> None:
        super().__init__(base_url, api_key, name)

    def call(self, payload):  # type: ignore[override]
        var = f"MOCK_RESPONSE_{self.name.upper()}"
        raw = os.getenv(var, "")
        if raw.lower() == "timeout":
            return type("R", (), {"status_code": 0, "content": "", "error": "mock timeout"})()
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError:
            return type("R", (), {"status_code": 200, "content": raw, "error": None})()
        status = int(spec.get("status", 200))
        content = spec.get("content", "")
        return type("R", (), {"status_code": status, "content": content, "error": None})()


def _factory(url, key, name):
    return TestMockProvider(url, key, name)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Clear relevant environment variables before each test."""
    for var in ["PRIMARY_BASE_URL", "PRIMARY_API_KEY", "FALLBACK_BASE_URL", "FALLBACK_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    for var in list(os.environ):
        if var.startswith("MOCK_RESPONSE_"):
            monkeypatch.delenv(var, raising=False)
    yield


def test_generate_success_primary(monkeypatch):
    monkeypatch.setenv("PRIMARY_BASE_URL", "https://primary.example")
    monkeypatch.setenv("PRIMARY_API_KEY", "pk-primary")
    monkeypatch.setenv("FALLBACK_BASE_URL", "https://fallback.example")
    monkeypatch.setenv("FALLBACK_API_KEY", "pk-fallback")
    monkeypatch.setenv("MOCK_RESPONSE_PRIMARY", json.dumps({"status": 200, "content": "<html>OK</html>"}))
    gen = Generator(provider_factory=_factory)
    assert gen.generate("spec") == "<html>OK</html>"


def test_generate_fallback_on_primary_error(monkeypatch):
    monkeypatch.setenv("PRIMARY_BASE_URL", "https://primary.example")
    monkeypatch.setenv("PRIMARY_API_KEY", "pk-primary")
    monkeypatch.setenv("FALLBACK_BASE_URL", "https://fallback.example")
    monkeypatch.setenv("FALLBACK_API_KEY", "pk-fallback")
    monkeypatch.setenv("MOCK_RESPONSE_PRIMARY", json.dumps({"status": 429}))
    monkeypatch.setenv("MOCK_RESPONSE_FALLBACK", json.dumps({"status": 200, "content": "<html>fallback</html>"}))
    gen = Generator(provider_factory=_factory)
    assert gen.generate("spec") == "<html>fallback</html>"


def test_generate_failure_both(monkeypatch):
    monkeypatch.setenv("PRIMARY_BASE_URL", "https://primary.example")
    monkeypatch.setenv("PRIMARY_API_KEY", "pk-primary")
    monkeypatch.setenv("FALLBACK_BASE_URL", "https://fallback.example")
    monkeypatch.setenv("FALLBACK_API_KEY", "pk-fallback")
    monkeypatch.setenv("MOCK_RESPONSE_PRIMARY", json.dumps({"status": 429}))
    monkeypatch.setenv("MOCK_RESPONSE_FALLBACK", json.dumps({"status": 429}))
    gen = Generator(provider_factory=_factory)
    with pytest.raises(GeneratorError) as exc:
        gen.generate("spec")
    assert "busy" in str(exc.value)


def test_missing_configuration(monkeypatch):
    with pytest.raises(GeneratorConfigError):
        Generator(provider_factory=_factory)

