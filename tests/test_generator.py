"""Generator tests use deterministic mock outcomes and a localhost fake API."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.generator import Generator, GeneratorConfigError, GeneratorError, Provider


@contextmanager
def fake_openai_server(responses):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            self.server.requests_received.append((self.path, payload, self.headers.get("Authorization")))
            result = self.server.responses[payload["model"]]
            if result.get("delay"):
                time.sleep(result["delay"])
            status = result.get("status", 200)
            body = result.get("body")
            if body is None:
                body = json.dumps({"choices": [{"message": {"content": result.get("content", "<html>ok</html>")}}]})
            encoded = body.encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except BrokenPipeError:
                pass  # expected when the timeout test's client has already disconnected

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.responses = responses
    server.requests_received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def configure_real_provider(monkeypatch, base_url):
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai")
    monkeypatch.setenv("PRIMARY_BASE_URL", base_url)
    monkeypatch.setenv("PRIMARY_API_KEY", "primary-test-key")
    monkeypatch.setenv("PRIMARY_MODEL", "primary-model")
    monkeypatch.setenv("FALLBACK_BASE_URL", base_url)
    monkeypatch.setenv("FALLBACK_API_KEY", "fallback-test-key")
    monkeypatch.setenv("FALLBACK_MODEL", "fallback-model")


@pytest.fixture(autouse=True)
def clear_generator_environment(monkeypatch):
    for name in (
        "GENERATOR_PROVIDER", "PRIMARY_BASE_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
        "FALLBACK_BASE_URL", "FALLBACK_API_KEY", "FALLBACK_MODEL", "MOCK_RESPONSE",
        "MOCK_RESPONSE_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_openai_compatible_request_and_response(monkeypatch):
    with fake_openai_server({"primary-model": {"content": "<html>from primary</html>"}}) as (url, server):
        configure_real_provider(monkeypatch, url)
        page = Generator().generate("a dog-walking pricing page", "soft pastel style")

    assert page == "<html>from primary</html>"
    path, payload, authorization = server.requests_received[0]
    assert path == "/v1/chat/completions"
    assert set(payload) == {"model", "messages"}
    assert payload["model"] == "primary-model"
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert "dog-walking pricing page" in payload["messages"][1]["content"]
    assert "soft pastel style" in payload["messages"][1]["content"]
    assert authorization == "Bearer primary-test-key"


@pytest.mark.parametrize("status", [402, 429])
def test_eligible_http_status_uses_fallback_once(monkeypatch, status):
    with fake_openai_server({
        "primary-model": {"status": status},
        "fallback-model": {"content": "<html>fallback</html>"},
    }) as (url, server):
        configure_real_provider(monkeypatch, url)
        assert Generator().generate("spec") == "<html>fallback</html>"

    assert [payload["model"] for _, payload, _ in server.requests_received] == ["primary-model", "fallback-model"]


def test_timeout_uses_fallback_once(monkeypatch):
    monkeypatch.setattr(Provider, "timeout_seconds", 0.05)
    with fake_openai_server({
        "primary-model": {"delay": 0.2},
        "fallback-model": {"content": "<html>fallback</html>"},
    }) as (url, server):
        configure_real_provider(monkeypatch, url)
        assert Generator().generate("spec") == "<html>fallback</html>"

    assert [payload["model"] for _, payload, _ in server.requests_received] == ["primary-model", "fallback-model"]


def test_http_500_is_an_error_and_does_not_become_a_page(monkeypatch):
    with fake_openai_server({
        "primary-model": {"status": 500, "body": "upstream failure"},
        "fallback-model": {"content": "should not be used"},
    }) as (url, server):
        configure_real_provider(monkeypatch, url)
        with pytest.raises(GeneratorError, match="busy"):
            Generator().generate("spec")

    assert [payload["model"] for _, payload, _ in server.requests_received] == ["primary-model"]


@pytest.mark.parametrize(
    ("outcome", "expected_fragment"),
    [("valid", "<section>"), ("script", "<script>"), ("missing_sections", "<h1>Mock</h1>")],
)
def test_environment_selects_mock_provider_outcomes(monkeypatch, outcome, expected_fragment):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", outcome)
    page = Generator().generate("spec")
    assert expected_fragment in page


def test_mock_429_retries_with_configured_fallback(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "429")
    monkeypatch.setenv("MOCK_RESPONSE_FALLBACK", "valid")
    assert "Mock page" in Generator().generate("spec")


def test_both_mock_attempts_failing_show_friendly_error(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "429")
    monkeypatch.setenv("MOCK_RESPONSE_FALLBACK", "429")
    with pytest.raises(GeneratorError, match="busy"):
        Generator().generate("spec")


def test_openai_provider_requires_primary_and_fallback_configuration(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai")
    with pytest.raises(GeneratorConfigError):
        Generator()


def test_retry_prompt_includes_previous_html_and_validation_errors():
    messages = Generator._messages(
        "a page",
        None,
        previous_attempt="<html>broken</html>",
        validation_errors=["Missing or empty <title> element."],
    )

    prompt = messages[1]["content"]
    assert "<html>broken</html>" in prompt
    assert "Missing or empty <title> element." in prompt
