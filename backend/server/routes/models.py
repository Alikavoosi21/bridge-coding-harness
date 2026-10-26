"""Models the user defined: address, model name, and a key kept in the OS keychain."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from harness.models import probe_model
from harness.config import ModelSpec

from .. import keychain, settings
from ..errors import ApiError
from ..schemas import ModelIn, ProbeModel

router = APIRouter(tags=["models"])


class DiscoverModels(BaseModel):
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    id: str | None = None


@router.post('/models/discover')
async def discover(body: DiscoverModels) -> dict:
    from ..model_catalog import discover_models
    secret = body.api_key or ''
    if body.id and not secret:
        entry = next((item for item in settings.load()['models'] if item['id'] == body.id), None)
        if entry is None or entry['base_url'].rstrip('/') != body.base_url.strip().rstrip('/'):
            raise ApiError('invalid_request', 'کلید ذخیره‌شده فقط به نشانی همان سرویس فرستاده می‌شود.', status_code=422)
        secret = keychain.get_key(body.id)
    return await discover_models(body.base_url, secret)


def _public(entry: dict[str, Any], default_id: str) -> dict[str, Any]:
    """A model as the UI may see it: never the key itself, only whether one is stored."""
    return {**entry, "has_key": keychain.has_key(entry["id"]), "is_default": entry["id"] == default_id}


def _spec(entry: dict[str, Any], api_key: str) -> ModelSpec:
    """The fields a model spec understands; stored capability results stay out."""
    fields = ModelSpec.__dataclass_fields__
    return ModelSpec(**{name: entry[name] for name in fields if name in entry and name != "api_key"}, api_key=api_key)


@router.get("/models")
def list_models() -> list[dict[str, Any]]:
    data = settings.load()
    return [_public(entry, data["default_model"]) for entry in data["models"]]


@router.post("/models")
def save_model(body: ModelIn) -> dict[str, Any]:
    """Add a model, or update the one with the same id."""
    data = settings.load()
    model_id = body.id or uuid.uuid4().hex[:8]
    existing = next((m for m in data["models"] if m["id"] == model_id), None)
    entry = {"id": model_id, "name": body.name or body.model, "base_url": body.base_url.strip(), "model": body.model.strip(), "input_price": body.input_price, "output_price": body.output_price, "streaming": body.streaming}
    # A probe is only evidence for the exact address/model/key it ran against.
    changed = existing is None or existing.get("base_url") != entry["base_url"] or existing.get("model") != entry["model"] or bool(body.api_key)
    if not changed and existing and existing.get("capabilities"):
        entry["capabilities"] = existing["capabilities"]
    data["models"] = [m for m in data["models"] if m["id"] != model_id] + [entry]
    if not any(m["id"] == data["default_model"] for m in data["models"]):
        data["default_model"] = model_id
    settings.save(data)
    if body.api_key:
        keychain.set_key(model_id, body.api_key)
    return _public(entry, data["default_model"])


@router.post("/models/probe")
async def probe(body: ProbeModel) -> dict[str, Any]:
    """Ask a model whether it can call tools, without sending any project content.

    The result is stored beside the model as evidence. An unsaved probe is
    returned to the caller and never written to settings.
    """
    data = settings.load()
    entry = next((m for m in data["models"] if m["id"] == body.id), None) if body.id else None
    if body.id and entry is None:
        raise HTTPException(status_code=404, detail="No such model.")
    if entry is None:
        if not body.base_url or not body.model:
            raise ApiError("invalid_request", "A probe needs a saved model id, or both base_url and model.", status_code=422)
        spec = ModelSpec(id="unsaved", name=body.model, base_url=body.base_url, model=body.model, api_key=body.api_key or "")
    else:
        spec = _spec(entry, body.api_key or keychain.get_key(entry["id"]))

    result = await probe_model(spec)

    if entry is not None and body.persist:
        entry["capabilities"] = result
        settings.save(data)
        return {**_public(entry, data["default_model"]), "probe": result}
    return {"id": spec.id, "probe": result}


@router.delete("/models/{model_id}")
def delete_model(model_id: str) -> dict[str, bool]:
    data = settings.load()
    remaining = [m for m in data["models"] if m["id"] != model_id]
    if len(remaining) == len(data["models"]):
        raise HTTPException(status_code=404, detail="No such model.")
    data["models"] = remaining
    if data["default_model"] == model_id:
        data["default_model"] = remaining[0]["id"] if remaining else ""
    settings.save(data)
    keychain.delete_key(model_id)
    return {"deleted": True}


@router.post("/models/{model_id}/default")
def set_default(model_id: str) -> dict[str, str]:
    data = settings.load()
    if not any(m["id"] == model_id for m in data["models"]):
        raise HTTPException(status_code=404, detail="No such model.")
    data["default_model"] = model_id
    settings.save(data)
    return {"default_model": model_id}
