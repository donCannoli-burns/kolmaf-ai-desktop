"""LLM provider abstraction and prompt construction for Kolmaf-AI.

This module defines a provider-agnostic interface so the response loop can be
plugged into any LLM (OpenAI, Anthropic, Ollama/Gemma, vLLM, etc.) without
changing the orchestration or safety logic. All responses remain proposals:
they are printed to the console and never written back to KoLmafia.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    """Structured response returned by an LLM provider."""

    text: str
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    """Minimal async contract for any chat/text LLM backend."""

    async def generate(self, prompt: str, system_prompt: str) -> LLMResponse:
        """Return a generated response for the given prompt and system prompt."""
        ...


class PromptBuilder:
    """Builds structured prompts from session events and retrieved context."""

    DEFAULT_SYSTEM_PROMPT = (
        "You are KOL-AI, a safe assistant living inside a KoLmafia session log. "
        "You observe player messages prefixed with 'KOLMAFA_USER:' and propose "
        "helpful, concise replies. You never echo secrets, credentials, or raw "
        "command output. You stay within the game's family-friendly tone. "
        "Responses are proposals only; they are not executed."
    )

    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> None:
        self.system_prompt = system_prompt

    def build(self, user_message: str, context: str) -> str:
        """Combine retrieved context and the user message into a user prompt."""

        if context:
            return (
                "RETRIEVED CONTEXT:\n"
                f"{context}\n\n"
                "PLAYER MESSAGE:\n"
                f"{user_message}\n\n"
                "Propose a short, helpful response (KOL-AI: <text>):"
            )
        return (
            "PLAYER MESSAGE:\n"
            f"{user_message}\n\n"
            "Propose a short, helpful response (KOL-AI: <text>):"
        )

    def get_system_prompt(self) -> str:
        return self.system_prompt


class StaticProvider:
    """Deterministic provider used for tests and dry-run demos.

    It does not call any network. It returns a canned acknowledgement so the
    architecture can be exercised end-to-end without secrets or external deps.
    The response body excludes the ``KOLMAFA:`` prefix — that is added by
    ``build_kolmafa_output`` in the bridge layer.
    """

    async def generate(self, prompt: str, system_prompt: str) -> LLMResponse:
        del system_prompt
        # Echo-free canned response: never includes the raw player message.
        return LLMResponse(text="I reviewed the context and am online.")


def run_provider(
    provider: LLMProvider,
    prompt: str,
    system_prompt: str,
) -> LLMResponse:
    """Run an async provider from synchronous bridge code."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Should not happen in CLI path, but stay safe.
        future = asyncio.ensure_future(provider.generate(prompt, system_prompt))
        return loop.run_until_complete(future)
    return asyncio.run(provider.generate(prompt, system_prompt))


class OllamaProvider:
    """Async provider that calls a local Ollama instance (Gemma 2, 4, etc.).

    Configuration (environment variables, checked in order):
      OLLAMA_BASE_URL / KOLMAFA_OLLAMA_URL   – base URL (default http://localhost:11434)
      OLLAMA_DEFAULT_MODEL / KOLMAFA_OLLAMA_MODEL – model name (default gemma2:2b)
      OLLAMA_TIMEOUT / KOLMAFA_OLLAMA_TIMEOUT     – request timeout seconds (default 120)

    The ``generate`` method uses the ``/api/chat`` endpoint (OpenAI-compatible
    messages format) for best results with modern instruction-tuned models.
    Falls back to ``/api/generate`` for raw completion models if needed.
    """

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        timeout: int = 120,
    ) -> None:
        import os

        # Check user's OLLAMA_* names first, then KOLMAFA_*, then defaults
        self.base_url = (
            base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("KOLMAFA_OLLAMA_URL", "http://localhost:11434")
        ).rstrip("/")

        self.model = (
            model
            or os.environ.get("OLLAMA_DEFAULT_MODEL")
            or os.environ.get("KOLMAFA_OLLAMA_MODEL", "gemma2:2b")
        )

        raw_timeout = (
            os.environ.get("OLLAMA_TIMEOUT")
            or os.environ.get("KOLMAFA_OLLAMA_TIMEOUT")
        )
        if raw_timeout is not None:
            timeout = int(raw_timeout)
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Call ``/api/chat`` with a list of message dicts (OpenAI format).

        Each message dict must have ``role`` (``user``, ``assistant``, ``system``)
        and ``content`` keys.
        """
        try:
            import httpx
        except ImportError as exc:
            raise LLMError(
                "httpx is required for Ollama provider. Install with: uv add httpx"
            ) from exc

        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Is ollama running? (ollama serve)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Ollama returned {exc.response.status_code}: {exc.response.text}") from exc

        message = data.get("message", {})
        text = (message.get("content") or "").strip()
        if not text:
            raise LLMError("Ollama chat returned an empty response")

        return LLMResponse(
            text=text,
            usage={
                "eval_count": data.get("eval_count", 0),
                "eval_duration": data.get("eval_duration", 0),
            },
        )

    async def generate(self, prompt: str, system_prompt: str) -> LLMResponse:
        """Call ``/api/chat`` with a simple user message tuple.

        This satisfies the ``LLMProvider`` protocol for the response loop.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, system_prompt=system_prompt)


def get_provider(kind: str = "static") -> LLMProvider:
    """Factory: return an ``LLMProvider`` matching *kind*.

    Accepted values: ``"static"`` (returns ``StaticProvider``) or ``"ollama"``
    (returns ``OllamaProvider``).  Any other value raises ``ValueError``.
    """
    if kind == "static":
        return StaticProvider()
    if kind == "ollama":
        return OllamaProvider()
    msg = f"Unknown LLM provider kind: {kind!r}. Expected 'static' or 'ollama'."
    raise ValueError(msg)


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails or is misconfigured."""
