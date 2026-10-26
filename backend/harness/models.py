"""Models: turn a user-defined `ModelSpec` into a chat model.

The harness is self-hosted, so nothing is hard-coded: each installation brings
its own endpoint, key and model name. Two wire formats cover almost everything:

- Anthropic's API (detected from the address)
- the OpenAI-compatible chat API, which OpenAI, OpenRouter, Ollama, vLLM and
  most gateways speak

`demo://` is a scripted stand-in that needs no key. It exists so the app and the
test suite can run a whole task end to end without calling a real model.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from .config import ModelSpec

DEMO_SCHEME = "demo://"

# The probe asks for one harmless tool call. It never includes project files,
# a prompt from the user, or a command: the only thing sent is this check.
_PROBE_PROMPT = "This is a capability check. Call report_capability with ok=true. Do not answer in text."
_DEFAULT_TIMEOUT = 30.0


@tool
def report_capability(ok: bool) -> str:
    """Report whether this model can call tools. Call this exactly once with ok=true."""
    return "probed" if ok else "not-probed"


def _redact(message: str, secret: str) -> str:
    text = str(message)
    if secret:
        text = text.replace(secret, "[redacted]")
    return text[:500]


def _classify(error: Exception) -> tuple[str, bool]:
    """Name the failure the way the setup screen explains it.

    ``provider_reachable`` is False only when nothing answered. A rejected key
    or an unsupported tool schema still means the address was reached.
    """
    message = str(error).lower()
    if any(word in message for word in ("authentication", "unauthorized", "invalid api key", "api key", "401", "403", "permission denied")):
        return "provider_auth", True
    if any(word in message for word in ("connection", "connect", "timed out", "timeout", "getaddrinfo", "name or service", "network", "ssl", "certificate", "dns")):
        return "provider_unreachable", False
    if any(word in message for word in ("model not found", "does not exist", "unknown model", "404")):
        return "model_not_found", True
    if any(word in message for word in ("tool", "function call", "function calling", "unsupported")):
        return "tools_unsupported", True
    return "provider_error", True


async def probe_model(spec: ModelSpec, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Check provider reachability and real tool-call support.

    A model is only allowed to run tasks that change files when this returns
    ``tools: True``. ``None`` means the check could not decide (for example the
    provider was unreachable), and the caller must keep writes disabled.
    """
    checked_at = time.time()
    if spec.base_url.startswith(DEMO_SCHEME):
        return {
            "model": spec.model,
            "tools": True,
            "provider_reachable": True,
            "demo": True,
            "streaming": True,
            "error_code": None,
            "error_message": None,
            "checked_at": checked_at,
        }

    try:
        model = build_chat_model(spec).bind_tools([report_capability])
        response = await asyncio.wait_for(model.ainvoke([HumanMessage(content=_PROBE_PROMPT)]), timeout=timeout)
    except Exception as error:  # noqa: BLE001 - every provider failure is a result, not a crash
        code, reachable = _classify(error)
        return {
            "model": spec.model,
            "tools": False if code == "tools_unsupported" else None,
            "provider_reachable": reachable,
            "demo": False,
            "streaming": spec.streaming,
            "error_code": code,
            "error_message": _redact(error, spec.api_key),
            "checked_at": checked_at,
        }

    calls = list(getattr(response, "tool_calls", None) or [])
    return {
        "model": spec.model,
        "tools": bool(calls),
        "provider_reachable": True,
        "demo": False,
        "streaming": spec.streaming,
        "error_code": None if calls else "tools_not_observed",
        "error_message": None if calls else "The provider answered, but it did not call the probe tool.",
        "checked_at": checked_at,
    }


def build_chat_model(spec: ModelSpec) -> BaseChatModel:
    if spec.base_url.startswith(DEMO_SCHEME):
        from .demo_model import demo_model

        return demo_model()

    if "anthropic" in spec.base_url:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=spec.model, api_key=spec.api_key, base_url=spec.base_url, max_retries=0)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=spec.model,
        # Local servers such as Ollama ignore the key but the client insists on one.
        api_key=spec.api_key or "not-needed",
        base_url=spec.base_url,
        stream_usage=True,
        disable_streaming=not spec.streaming,
        # Retries are owned by the durability layer, so they are counted and visible.
        max_retries=0,
    )
