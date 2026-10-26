"""Typed API errors.

Every failure the local API returns has the same JSON shape:

    {code, message, details, retryable, current_revision?}

`code` is stable and machine-readable; `message` is for the user. Routes raise
`ApiError`; the handler in `install_error_handlers` turns it into a response and
never leaks a traceback or a secret.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        current_revision: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable
        self.current_revision = current_revision

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }
        if self.current_revision is not None:
            payload["current_revision"] = self.current_revision
        return payload


def _legacy_code(status: int) -> str:
    return {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "invalid_request",
        429: "rate_limited",
        503: "unavailable",
    }.get(status, "error")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status_code)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail if isinstance(error.detail, str) else "Request failed."
        payload = ApiError(_legacy_code(error.status_code), detail, status_code=error.status_code).body()
        return JSONResponse(payload, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's default shape is `{"detail": [...]}`; keep every failure in one shape.
        payload = ApiError(
            "invalid_request",
            "The request is invalid.",
            status_code=422,
            details={"errors": jsonable_encoder(error.errors())},
        ).body()
        return JSONResponse(payload, status_code=422)
