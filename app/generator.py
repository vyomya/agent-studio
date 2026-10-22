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

    timeout_seconds = 60

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        name: str = "primary",
        max_tokens: int = 2048,
    ) -> None:
        try:
            timeout_seconds = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
        except (TypeError, ValueError):
            timeout_seconds = 60
        self.timeout_seconds = timeout_seconds if timeout_seconds >= 1 else 60
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self.max_tokens = max_tokens

    def call(self, messages: list[dict[str, str]]) -> ProviderResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                },
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

_SYSTEM_PROMPT = """Return one complete HTML document that parses as HTML.
Make it self-contained and use inline CSS.
Include a non-empty <title>.
Include exactly one <h1>.
Include at least three <section> elements.
Keep the document at or below 100 KB.
Do not include <script> elements, inline event handlers, or javascript: URLs.
Do not load external resources: avoid external src/srcset URLs, external <link> or <base> href URLs, CSS url(...), and @import.
Do not include <iframe>, <object>, <embed>, or a meta refresh.
Return only the HTML document, no Markdown fences."""


class MockProvider(Provider):
    """Deterministic provider selected with GENERATOR_PROVIDER=mock.

    MOCK_RESPONSE accepts: valid, script, missing_sections, or 429. The fallback may
    override the response with MOCK_RESPONSE_FALLBACK.
    """

    def __init__(self, base_url: str = "mock://provider", api_key: str = "mock", model: str = "mock", name: str = "primary") -> None:
        super().__init__(base_url, api_key, model, name)

    def call(self, messages: list[dict[str, str]]) -> ProviderResponse:
        user_content = messages[-1]["content"] if messages else ""
        is_refine = user_content.startswith("Refine this HTML page according to the instruction below.")
        if is_refine:
            outcome = os.getenv("MOCK_REFINE_RESPONSE_FALLBACK") if self.name == "fallback" else None
            outcome = outcome or os.getenv("MOCK_REFINE_RESPONSE", "valid")
        else:
            outcome = os.getenv("MOCK_RESPONSE_FALLBACK") if self.name == "fallback" else None
            outcome = outcome or os.getenv("MOCK_RESPONSE", "valid")
        outcome = outcome.strip().lower()
        if outcome == "429":
            return ProviderResponse(status_code=429, error="Mock rate limit")
        if outcome == "valid":
            if is_refine:
                instruction = user_content.split("Instruction:", 1)[1].split(" Existing HTML:", 1)[0].strip()
                refined = _VALID_HTML.replace("Mock page", "Mock refined page")
                if "dark" in instruction.lower():
                    refined = refined.replace("<head>", "<head><style>body { background: #111; color: #eee; }</style>")
                return ProviderResponse(status_code=200, content=refined)
            return ProviderResponse(status_code=200, content=_VALID_HTML)
        if outcome == "script":
            content = _VALID_HTML.replace("</body>", "<script>alert(1)</script></body>")
            return ProviderResponse(status_code=200, content=content)
        if outcome == "missing_sections":
            content = "<html><head><title>Mock</title></head><body><h1>Mock</h1></body></html>"
            return ProviderResponse(status_code=200, content=content)
        return ProviderResponse(status_code=500, error=f"Unknown mock outcome: {outcome}")


class Generator:
    """Generate HTML and retry once with fallback on 402, 429, 503, or timeout."""

    RETRY_STATUS = {402, 429, 503, 0}
    BUSY_MESSAGE = "The service is currently busy, please try again later."

    def __init__(self) -> None:
        self.provider_mode = os.getenv("GENERATOR_PROVIDER", "openai").strip().lower()
        if self.provider_mode not in {"openai", "mock"}:
            raise GeneratorConfigError("GENERATOR_PROVIDER must be 'openai' or 'mock'")
        try:
            self.max_tokens = int(os.getenv("MODEL_MAX_TOKENS", "2048"))
        except ValueError as exc:
            raise GeneratorConfigError("MODEL_MAX_TOKENS must be a positive integer") from exc
        if self.max_tokens < 1:
            raise GeneratorConfigError("MODEL_MAX_TOKENS must be a positive integer")

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
        self.primary = Provider(primary_url, primary_key, primary_model, "primary", self.max_tokens)
        self.fallback = Provider(fallback_url, fallback_key, fallback_model, "fallback", self.max_tokens)

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
            {"role": "system", "content": _SYSTEM_PROMPT},
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

    def refine(
        self,
        page_html: str,
        instruction: str,
        *,
        previous_attempt: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> str:
        """Refine a saved page through the same metered model request path."""
        user_content = (
            "Refine this HTML page according to the instruction below. "
            f"Instruction: {instruction} Existing HTML: {page_html}"
        )
        if previous_attempt is not None:
            user_content += (
                "\n\nYour previous refined HTML attempt failed validation. Return a corrected, complete "
                "self-contained HTML document.\nValidation errors:\n- "
                + "\n- ".join(validation_errors or [])
                + "\nPrevious HTML attempt:\n"
                + previous_attempt
            )
        messages = [
            {
                "role": "system",
                "content": _SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]
        return self._request(messages)
