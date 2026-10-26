"""Durable steering: acknowledge only messages visible in graph state/checkpoint."""
from __future__ import annotations
from typing import Any
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage


def _as_text(message: dict[str, Any]) -> str:
    text = "\n".join(part.get("text", "") for part in message.get("parts") or [] if isinstance(part, dict)).strip()
    references = message.get("references") or []
    if references:
        text += "\n\nFiles the user pointed at:\n" + "\n".join(f"- {path}" for path in references)
    return text


def acknowledge_steering(store: Any, task_id: str, state: Any) -> None:
    """Caller supplies persisted graph state, never a proposed middleware update."""
    ids = {getattr(message, "id", None) for message in (state or {}).get("messages", [])}
    delivered = [message["id"] for message in store.pending_messages(task_id) if message["id"] in ids]
    if delivered:
        store.mark_messages_delivered(delivered)


class SteeringHook(AgentMiddleware):
    def __init__(self, store: Any, task_id: str) -> None:
        self.store, self.task_id = store, task_id

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        # Prior node updates are durable with Runner's sync checkpointing.
        # A crash before this update commits leaves pending intact; on replay,
        # the messages reducer deduplicates the stable product message IDs.
        acknowledge_steering(self.store, self.task_id, state)
        pending = self.store.pending_messages(self.task_id)
        messages = [HumanMessage(id=message["id"], content=_as_text(message)) for message in pending if _as_text(message)]
        return {"messages": messages} if messages else None
