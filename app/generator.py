"""OpenAI-compatible page generator with configurable primary and fallback providers."""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

__all__ = ["Generator", "GeneratorError", "GeneratorConfigError", "Provider", "MockProvider"]


class GeneratorError(RuntimeError):
    """Raised when a provider cannot generate a page."""


class GeneratorConfigError(RuntimeError):
    """Raised when generator configuration is missing or invalid."""


@dataclass
class ProviderResponse:
    status_code: int
    content: str = ""
    error: str | None = None


class Provider:
    """Calls an OpenAI-compatible chat-completions endpoint."""

    timeout_seconds = 10

    def __init__(self, base_url: str, api_key: str, model: str, name: str = "primary") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name

    def call(self, messages: list[dict[str, str]]) -> ProviderResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"model": self.model, "messages": messages},
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            return ProviderResponse(status_code=0, error=str(exc))
        except requests.exceptions.RequestException as exc:
            return ProviderResponse(status_code=-1, error=str(exc))

        if response.status_code != 200:
            return ProviderResponse(status_code=response.status_code, error=response.text)
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return ProviderResponse(status_code=200, error=f"Invalid chat-completions response: {exc}")
        if not isinstance(content, str) or not content:
            return ProviderResponse(status_code=200, error="Chat-completions response contained no page content")
        return ProviderResponse(status_code=200, content=content)


_VALID_HTML = """<!doctype html><html><head><title>Mock page</title></head><body>
<h1>Mock page</h1><section><h2>First</h2></section>
<section><h2>Second</h2></section><section><h2>Third</h2></section></body></html>"""


class MockProvider(Provider):
    """Deterministic provider selected with GENERATOR_PROVIDER=mock.

    MOCK_RESPONSE accepts: valid, script, missing_sections, or 429. The fallback may
    override the response with MOCK_RESPONSE_FALLBACK.
    """

    def __init__(self, base_url: str = "mock://provider", api_key: str = "mock", model: str = "mock", name: str = "primary") -> None:
        super().__init__(base_url, api_key, model, name)

    def call(self, messages: list[dict[str, str]]) -> ProviderResponse:
        outcome = os.getenv("MOCK_RESPONSE_FALLBACK") if self.name == "fallback" else None
        outcome = outcome or os.getenv("MOCK_RESPONSE", "valid")
        outcome = outcome.strip().lower()
        if outcome == "429":
            return ProviderResponse(status_code=429, error="Mock rate limit")
        if outcome == "valid":
            return ProviderResponse(status_code=200, content=_VALID_HTML)
        if outcome == "script":
            content = _VALID_HTML.replace("</body>", "<script>alert(1)</script></body>")
            return ProviderResponse(status_code=200, content=content)
        if outcome == "missing_sections":
            content = "<html><head><title>Mock</title></head><body><h1>Mock</h1></body></html>"
            return ProviderResponse(status_code=200, content=content)
        return ProviderResponse(status_code=500, error=f"Unknown mock outcome: {outcome}")


class Generator:
    """Generate HTML and retry once with fallback on 402, 429, or timeout."""

    RETRY_STATUS = {402, 429, 0}
    BUSY_MESSAGE = "The service is currently busy, please try again later."

    def __init__(self) -> None:
        self.provider_mode = os.getenv("GENERATOR_PROVIDER", "openai").strip().lower()
        if self.provider_mode not in {"openai", "mock"}:
            raise GeneratorConfigError("GENERATOR_PROVIDER must be 'openai' or 'mock'")

        primary_model = os.getenv("PRIMARY_MODEL")
        fallback_model = os.getenv("FALLBACK_MODEL")
        if self.provider_mode == "mock":
            self.primary = MockProvider(model=primary_model or "mock-primary", name="primary")
            self.fallback = MockProvider(model=fallback_model or "mock-fallback", name="fallback")
            return

        primary_url = os.getenv("PRIMARY_BASE_URL")
        primary_key = os.getenv("PRIMARY_API_KEY")
        fallback_url = os.getenv("FALLBACK_BASE_URL")
        fallback_key = os.getenv("FALLBACK_API_KEY")
        if not all((primary_url, primary_key, primary_model, fallback_url, fallback_key, fallback_model)):
            raise GeneratorConfigError(
                "PRIMARY_BASE_URL, PRIMARY_API_KEY, PRIMARY_MODEL, FALLBACK_BASE_URL, "
                "FALLBACK_API_KEY, and FALLBACK_MODEL are required"
            )
        self.primary = Provider(primary_url, primary_key, primary_model, "primary")
        self.fallback = Provider(fallback_url, fallback_key, fallback_model, "fallback")

    @staticmethod
    def _messages(
        spec: str,
        style_example: str | None,
        previous_attempt: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> list[dict[str, str]]:
        user_content = "Create one self-contained HTML page for this specification: " + spec
        if style_example:
            user_content += " Style example: " + style_example
        if previous_attempt is not None:
            user_content += (
                "\n\nYour previous HTML attempt failed validation. Return a corrected, complete "
                "self-contained HTML document.\nValidation errors:\n- "
                + "\n- ".join(validation_errors or [])
                + "\nPrevious HTML attempt:\n"
                + previous_attempt
            )
        return [
            {"role": "system", "content": "Return a complete, self-contained HTML document with inline CSS. Return HTML only."},
            {"role": "user", "content": user_content},
        ]

    def _attempt(self, provider: Provider, messages: list[dict[str, str]]) -> ProviderResponse:
        return provider.call(messages)

    def generate(
        self,
        spec: str,
        style_example: str | None = None,
        *,
        previous_attempt: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Generate one model response; the route owns allowance accounting."""
        messages = self._messages(spec, style_example, previous_attempt, validation_errors)
        return self._request(messages)

    def _request(self, messages: list[dict[str, str]]) -> str:
        primary = self._attempt(self.primary, messages)
        if primary.status_code == 200 and not primary.error:
            return primary.content
        if primary.status_code not in self.RETRY_STATUS:
            raise GeneratorError(self.BUSY_MESSAGE)

        fallback = self._attempt(self.fallback, messages)
        if fallback.status_code == 200 and not fallback.error:
            return fallback.content
        raise GeneratorError(self.BUSY_MESSAGE)

    def refine(self, page_html: str, instruction: str) -> str:
        """Refine a saved page through the same metered model request path."""
        messages = [
            {
                "role": "system",
                "content": (
                    "Return a complete, self-contained HTML document with inline CSS. "
                    "Apply the requested changes to the supplied page and return HTML only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Refine this HTML page according to the instruction below. "
                    f"Instruction: {instruction} Existing HTML: {page_html}"
                ),
            },
        ]
        return self._request(messages)
