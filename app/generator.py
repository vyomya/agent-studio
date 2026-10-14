"""Generator module for the core area.

The generator is responsible for calling an LLM provider to turn a spec (and optional
style example) into an HTML page.  The concrete provider (primary or fallback) is
configured via environment variables; the implementation is deliberately thin – it
does **not** contain any model‑specific logic, only the wiring required by the
acceptance criteria of ticket #3.

Key responsibilities:
* Read configuration from ``PRIMARY_BASE_URL``, ``PRIMARY_API_KEY``, ``FALLBACK_BASE_URL``
  and ``FALLBACK_API_KEY``.  Missing values raise ``GeneratorConfigError``.
* Attempt a request against the primary provider.  If the response has status code
  402, 429 or a timeout occurs, retry once against the fallback provider.
* If both attempts fail, raise ``GeneratorError`` with a friendly message – this is the
  message shown to the visitor.

The module also provides a lightweight ``MockProvider`` that can be used in tests to
avoid real network calls.  The mock can be instructed via the ``MOCK_RESPONSE``
environment variable to simulate success, HTTP errors or timeouts.

Only the ``Generator`` class is exported; tests import it directly and can also
inject a custom provider for finer control.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

import requests

__all__ = ["Generator", "GeneratorError", "GeneratorConfigError", "Provider", "MockProvider"]


class GeneratorError(RuntimeError):
    """Raised when generation fails after primary and fallback attempts.

    The message is intentionally user‑facing – callers can present it directly to the
    visitor.
    """


class GeneratorConfigError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


@dataclass
class ProviderResponse:
    """Simple wrapper for a provider's HTTP response.

    ``status_code`` mimics ``requests.Response.status_code`` and ``content`` holds the
    generated HTML (or an empty string on error).  ``error`` is optional and can store a
    textual description of a failure for debugging.
    """

    status_code: int
    content: str = ""
    error: Optional[str] = None


class Provider:
    """Abstract provider used by :class:`Generator`.

    Sub‑classes must implement :meth:`call` which performs the actual request and
    returns a :class:`ProviderResponse`.
    """

    def __init__(self, base_url: str, api_key: str, name: str = "primary") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name

    def call(self, payload: Mapping[str, Any]) -> ProviderResponse:
        """Call the remote LLM provider.

        The default implementation performs a JSON POST to ``{base_url}/v1/chat/completions``
        with the supplied ``payload``.  It expects a JSON response containing a ``content``
        field with the generated HTML.
        """
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
        except requests.exceptions.Timeout as exc:
            # Propagate a timeout as a special response so the Generator can retry.
            return ProviderResponse(status_code=0, error=str(exc))
        except requests.exceptions.RequestException as exc:
            # Treat any other request error as a generic failure.
            return ProviderResponse(status_code=0, error=str(exc))

        if resp.status_code != 200:
            return ProviderResponse(status_code=resp.status_code, error=resp.text)

        try:
            data = resp.json()
            content = data.get("content", "")
        except (json.JSONDecodeError, ValueError) as exc:
            return ProviderResponse(status_code=resp.status_code, error=str(exc))
        return ProviderResponse(status_code=200, content=content)


class MockProvider(Provider):
    """A provider used in tests – behaviour driven by ``MOCK_RESPONSE``.

    ``MOCK_RESPONSE`` can be a JSON string describing the response, e.g.

    ``{"status": 200, "content": "<html>…"}``

    or a special marker ``"timeout"`` to simulate a timeout.
    """

    def __init__(self, name: str = "mock") -> None:
        # The mock does not need a real URL or key.
        super().__init__(base_url="mock://provider", api_key="mock", name=name)

    def call(self, payload: Mapping[str, Any]) -> ProviderResponse:
        raw = os.getenv("MOCK_RESPONSE", "")
        if raw.lower() == "timeout":
            # Simulate a timeout – the Generator treats status_code 0 as a timeout.
            return ProviderResponse(status_code=0, error="mock timeout")
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError:
            # If not JSON, treat the whole string as content with a 200 status.
            return ProviderResponse(status_code=200, content=raw)
        status = int(spec.get("status", 200))
        content = spec.get("content", "")
        return ProviderResponse(status_code=status, content=content)


class Generator:
    """Core generator handling primary/fallback provider logic.

    The public API is :meth:`generate`.  It accepts a ``spec`` string (and optional
    ``style_example``) and returns the generated HTML or raises :class:`GeneratorError`.
    """

    RETRY_STATUS = {402, 429, 0}  # ``0`` represents a timeout from the Provider.

    def __init__(self, provider_factory: Callable[[str, str, str], Provider] | None = None) -> None:
        """Create a generator.

        ``provider_factory`` is a callable used to instantiate providers.  It receives
        ``base_url``, ``api_key`` and a ``name`` (``"primary"`` or ``"fallback"``).  The
        default uses the :class:`Provider` class.  Tests can supply a factory that returns a
        :class:`MockProvider`.
        """
        # Configuration is read once at construction – changing env vars later only
        # affects a newly‑created Generator, matching the acceptance criterion that a
        # restart (i.e., new process) is required to pick up changes.
        self.primary_url = os.getenv("PRIMARY_BASE_URL")
        self.primary_key = os.getenv("PRIMARY_API_KEY")
        self.fallback_url = os.getenv("FALLBACK_BASE_URL")
        self.fallback_key = os.getenv("FALLBACK_API_KEY")
        if not all([self.primary_url, self.primary_key, self.fallback_url, self.fallback_key]):
            raise GeneratorConfigError("Missing required generator environment variables")
        self.factory = provider_factory or (lambda url, key, name: Provider(url, key, name))
        self.primary: Provider = self.factory(self.primary_url, self.primary_key, "primary")
        self.fallback: Provider = self.factory(self.fallback_url, self.fallback_key, "fallback")

    def _attempt(self, provider: Provider, payload: Mapping[str, Any]) -> ProviderResponse:
        return provider.call(payload)

    def generate(self, spec: str, style_example: str | None = None) -> str:
        """Generate HTML from ``spec``.

        ``style_example`` is optional and, if provided, is included in the payload under the
        key ``"style"``.  The payload format is deliberately simple – it mirrors what a
        real LLM prompt might look like but does not enforce any contract.
        """
        payload: dict[str, Any] = {"spec": spec}
        if style_example:
            payload["style"] = style_example

        # Try primary first.
        primary_resp = self._attempt(self.primary, payload)
        if primary_resp.status_code not in self.RETRY_STATUS:
            # Successful response.
            return primary_resp.content
        # Primary failed with retry‑eligible status – try fallback.
        fallback_resp = self._attempt(self.fallback, payload)
        if fallback_resp.status_code not in self.RETRY_STATUS:
            return fallback_resp.content
        # Both failed – raise a friendly error.
        raise GeneratorError("The service is currently busy, please try again later.")

