"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import BACKEND_DIR, get_settings
from app.core.errors import StudioError
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    from app.db.init import init_db

    init_db()
    pool = None
    if settings.run_worker_in_process and settings.environment != "test":
        from app.workers.runner import WorkerPool

        pool = WorkerPool()
        pool.start()
    if settings.environment != "test":
        import threading

        threading.Thread(target=_warm_ai_models, name="warm-models", daemon=True).start()
    log.info("app.started", env=settings.environment, tts=settings.tts_provider, llm=settings.llm_provider, worker="in-process" if pool else "external")
    yield
    if pool:
        pool.stop()


def _warm_ai_models() -> None:
    """Fetch/load the default embedding + reranking models in the background, so the
    first "Ask the Book" question doesn't wait on a one-time model download."""
    try:
        from app.providers.embeddings import get_embedding_provider
        from app.providers.rerank import get_reranker

        get_embedding_provider(language="en").embed(["warm up"])
        reranker = get_reranker("en")
        if reranker:
            reranker.score("warm up", ["warm up"])
        log.info("ai.models_ready")
    except Exception as exc:  # offline etc.: retrieval falls back gracefully
        log.warning("ai.warmup_failed", error=str(exc)[:200])


class _DropClientResets(logging.Filter):
    """Windows' proactor loop logs a traceback whenever a browser drops a keep-alive
    connection (WinError 10054). It's harmless; keep it out of the error log."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not isinstance(exc, ConnectionResetError)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logging.getLogger("asyncio").addFilter(_DropClientResets())
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.exception_handler(StudioError)
    async def studio_error(_request: Request, exc: StudioError):
        headers = {"Retry-After": str(exc.details["retry_after"])} if "retry_after" in exc.details else None
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        message = f"{field}: {first.get('msg')}" if field else str(first.get("msg", "Invalid request"))
        return JSONResponse({"error": {"code": "validation_failed", "message": message, "retryable": False, "details": {"errors": exc.errors()}}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": f"http_{exc.status_code}", "message": str(exc.detail), "retryable": False, "details": {}}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        log.exception("api.unhandled_error", error=type(exc).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": f"The server hit an unexpected error ({type(exc).__name__}). Details are in the server log.", "retryable": True, "details": {}}},
            status_code=500,
        )

    from app.api.routes import ai, auth, books, chapters, jobs, media, player, system, voices, ws

    for module in (auth, books, chapters, jobs, player, voices, ai, system, media, ws):
        app.include_router(module.router)

    # Serve the built frontend (production / single-command mode).
    if FRONTEND_DIST.exists():
        index = FRONTEND_DIST / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith(("api/", "media/", "ws/")):
                return JSONResponse({"error": {"code": "not_found", "message": "Not found", "retryable": False, "details": {}}}, status_code=404)
            candidate = (FRONTEND_DIST / path).resolve()
            if path and FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
