"""FastAPI application for Polaris Recommendation API."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routers import recommendations, review, scholarships

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("polaris.api")


def _allowed_origins() -> list[str]:
    """Origins allowed to call this API cross-origin.

    Empty by default, which means CORS is not enabled at all — correct for the
    single-origin deployment where the API serves ``frontend/dist`` itself.
    A split deployment (frontend on a CDN, API elsewhere) must name its
    origins explicitly rather than reaching for ``*``, because the public
    read/matching API has no authentication and a wildcard would let any site
    on the internet read it. The admin review surface is separately protected
    by a bearer token, but CORS is not an authentication mechanism.
    """
    raw = os.environ.get("POLARIS_ALLOWED_ORIGINS", "").strip()
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


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

    # --- Cross-origin policy ---
    origins = _allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
        logger.info("CORS enabled for %d configured origin(s)", len(origins))

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
    app.include_router(review.router)

    @app.get(
        "/health",
        summary="Health check",
        description=(
            "Liveness and readiness. Reports `degraded` (HTTP 503) when the "
            "database is unreachable, so an orchestrator restarts or holds "
            "traffic instead of routing it to an API that cannot serve it."
        ),
    )
    def health():
        from sqlalchemy import text

        from database.session import SessionLocal

        try:
            session = SessionLocal()
            try:
                session.execute(text("SELECT 1"))
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 — the point is to report, not raise
            logger.error("Health check failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "database": "unreachable"},
            )
        return {"status": "ok", "database": "ok"}

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dir.exists():
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            # Hashed build assets, served by StaticFiles for range/caching.
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        index = frontend_dir / "index.html"
        static_root = frontend_dir.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            """Serve a real file if one exists, otherwise the SPA entry point.

            The frontend is a single-page app with history routing, so
            ``/discover``, ``/match`` and ``/scholarships/<id>`` exist only in
            the browser. A plain ``StaticFiles(html=True)`` mount answers 404 for
            all of them, which means a bookmark, a shared link, or a page
            refresh on any route other than ``/`` breaks — including the
            shortlist, which lives in localStorage and survives a reload only if
            the reload resolves.

            Registered after the API routers, so it is reached only by a path
            nothing else claimed. An unknown ``/api/...`` path still 404s as
            JSON rather than falling through to the SPA shell: returning HTML
            for an API route turns a client-side bug into a parse error three
            layers away.
            """
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404, content={"detail": "Not found"}
                )

            candidate = (static_root / full_path).resolve()
            # `is_relative_to` is the traversal guard: a crafted path such as
            # ``../../.env`` resolves outside the build directory and is refused.
            if full_path and candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(str(candidate))
            return FileResponse(str(index))

    return app


app = create_app()
