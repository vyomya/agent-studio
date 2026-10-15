"""Generate, validate, and save a page with a bounded repair loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

if __package__:
    from .generator import Generator
    from .validator import validate_html
else:  # Container runs modules directly from its /app working directory.
    from generator import Generator
    from validator import validate_html

MAX_ATTEMPTS = 3


class InvalidPageError(RuntimeError):
    """Raised when every generated page fails validation."""

    def __init__(self, attempts: int, errors: list[str]) -> None:
        self.attempts = attempts
        self.errors = list(errors)
        super().__init__(f"No valid page could be built after {attempts} attempts.")


@dataclass(frozen=True)
class GeneratedPage:
    """A validated page together with the saved record and attempt count."""

    html: str
    attempts: int
    saved_record: object


SavePage = Callable[[str, str, int], object]


def generate_valid_page(
    spec: str,
    generator: Generator,
    save_page: SavePage,
    style_example: str | None = None,
) -> GeneratedPage:
    """Try up to three times; save only after code validation succeeds.

    save_page receives (spec, html, attempts) so persistence can retain the
    original request and the successful attempt number.
    """
    previous_attempt: str | None = None
    errors: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        html = generator.generate(
            spec,
            style_example,
            previous_attempt=previous_attempt,
            validation_errors=errors,
        )
        errors = validate_html(html)
        if not errors:
            saved_record = save_page(spec, html, attempt)
            return GeneratedPage(html=html, attempts=attempt, saved_record=saved_record)
        previous_attempt = html

    raise InvalidPageError(MAX_ATTEMPTS, errors)
