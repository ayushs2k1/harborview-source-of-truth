"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sot.api.routers import (
    decisions,
    evidence,
    exports,
    flags,
    health,
    persons,
    pipeline,
    runs,
    views,
)
from sot.config import ENGINE_VERSION, settings

log = logging.getLogger("sot.api")


def create_app() -> FastAPI:
    """Build the API.

    CORS is restricted to localhost: the data is a care home's staffing records and
    never needs to be reachable from anywhere else (spec section 23, privacy).
    """
    app = FastAPI(
        title="Harborview Source of Truth",
        version=ENGINE_VERSION,
        description="Every number has receipts.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings().cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (health, runs, flags, persons, views, evidence, exports, decisions, pipeline):
        app.include_router(module.router, prefix="/api")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Last line of defence for principle 1: never crash on the user.

        An unexpected error still becomes a readable JSON response rather than a
        connection reset, and the traceback goes to the server log where we can find it.
        """
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": str(exc),
                "path": request.url.path,
                "hint": "This is a bug. The run log has the traceback.",
            },
        )

    return app


app = create_app()
