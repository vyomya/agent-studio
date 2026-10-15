"""Tests for the bounded generate/validate/save loop."""
from __future__ import annotations

import pytest

from app.retry import InvalidPageError, generate_valid_page


VALID_HTML = """<!doctype html><html><head><title>Example</title></head><body>
<h1>Example</h1><section>One</section><section>Two</section><section>Three</section>
</body></html>"""


class SequenceGenerator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def generate(self, spec, style_example=None, *, previous_attempt=None, validation_errors=None):
        self.calls.append({
            "spec": spec,
            "style_example": style_example,
            "previous_attempt": previous_attempt,
            "validation_errors": validation_errors,
        })
        return next(self.responses)


def test_always_invalid_page_is_not_saved_after_three_attempts():
    invalid = "<html><head></head><body><h1>Bad</h1></body></html>"
    generator = SequenceGenerator([invalid, invalid, invalid, VALID_HTML])
    saved: list[tuple[str, str, int]] = []

    with pytest.raises(InvalidPageError) as raised:
        generate_valid_page("a page", generator, lambda *args: saved.append(args))

    assert raised.value.attempts == 3
    assert len(generator.calls) == 3
    assert saved == []


def test_retry_sends_failed_attempt_and_errors_back_to_generator():
    invalid = "<html><head></head><body><h1>Bad</h1></body></html>"
    generator = SequenceGenerator([invalid, VALID_HTML])

    result = generate_valid_page(
        "a page", generator, lambda spec, html, attempts: (spec, html, attempts)
    )

    assert result.attempts == 2
    assert generator.calls[1]["previous_attempt"] == invalid
    assert "Missing or empty <title> element." in generator.calls[1]["validation_errors"]


def test_page_that_passes_on_second_attempt_is_saved_once():
    invalid = "<html><head></head><body><h1>Bad</h1></body></html>"
    generator = SequenceGenerator([invalid, VALID_HTML])
    saved: list[tuple[str, str, int]] = []

    result = generate_valid_page("a page", generator, lambda *args: saved.append(args))

    assert result.html == VALID_HTML
    assert result.attempts == 2
    assert saved == [("a page", VALID_HTML, 2)]


def test_complete_markdown_fence_is_removed_before_validation_and_save():
    fenced = f"```html\n{VALID_HTML}\n```"
    saved: list[tuple[str, str, int]] = []
    generator = SequenceGenerator([fenced])

    result = generate_valid_page(
        "a page", generator, lambda *args: saved.append(args)
    )

    assert result.html == VALID_HTML
    assert saved == [("a page", VALID_HTML, 1)]


def test_retry_receives_unfenced_previous_html():
    invalid_html = "<html><body><h1>Incomplete</h1></body></html>"
    fenced_invalid = f"```html\n{invalid_html}\n```"
    generator = SequenceGenerator([fenced_invalid, VALID_HTML])

    result = generate_valid_page(
        "a page", generator, lambda *args: args
    )

    assert result.attempts == 2
    assert generator.calls[1]["previous_attempt"] == invalid_html


def test_real_generator_retries_without_per_attempt_allowance_arguments(monkeypatch):
    from app.generator import Generator

    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    responses = iter(["<html><body><h1>invalid</h1></body></html>", VALID_HTML])

    generator = Generator()
    monkeypatch.setattr(generator, "_request", lambda messages: next(responses))

    result = generate_valid_page(
        "a page", generator, lambda *args: args
    )

    assert result.attempts == 2
