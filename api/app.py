"""FastAPI application for Polaris Recommendation API."""

from __future__ import annotations

import logging
import time

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routers import recommendations, scholarships

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("polaris.api")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Polaris — Scholarship Recommendation API",
        version="0.1.0",
        description=(
            "Deterministic scholarship matching engine. "
            "Provide a student profile and receive ranked scholarship recommendations "
            "with explanations, strengths, gaps, and next steps."
        ),
        contact={"name": "Polaris Team"},
        license_info={"name": "Internal"},
    )

    # --- Global exception handlers ---

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Return 422 for Pydantic validation errors."""
        errors = []
        for error in exc.errors():
            loc = " -> ".join(str(part) for part in error["loc"])
            errors.append(f"{loc}: {error['msg']}")
        logger.warning("Validation error: %s", errors)
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Return 500 for unhandled exceptions."""
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # --- Request logging middleware ---

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log request start, end, status, and execution time."""
        start = time.perf_counter()
        logger.info("→ %s %s", request.method, request.url.path)

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "← %s %s — %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # --- Routes ---

    app.include_router(recommendations.router, tags=["recommendations"])
    app.include_router(scholarships.router, tags=["scholarships"])

    @app.get(
        "/health",
        summary="Health check",
        description="Returns service health status.",
        response_model=dict[str, str],
    )
    def health():
        return {"status": "ok"}

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
