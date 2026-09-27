"""
app.main — FastAPI application entry point for Mizan AI (production backend).

Mounts: auth, chat (SSE), notifications, admin. Adds CORS, request logging,
rate limiting, unified error handling, and a public health probe.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.errors import error_body, register_error_handlers
from app.core.logging import RequestLoggingMiddleware, setup_logging
from app.core.rate_limit import limiter
from app.api.routes import admin, auth, chat, notifications, voice
from app.db.models import init_db

setup_logging()
logger = logging.getLogger("mizan.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Mizan backend started (model=%s)", settings.GROQ_MODEL)

    # Register built-in legal documents into the admin registry (idempotent)
    from app.db.models import SessionLocal
    from app.api.routes.admin import _sync_builtin_documents
    with SessionLocal() as db:
        _sync_builtin_documents(db)

    # Preload the Libyan Whisper STT model in the background
    voice.preload()

    yield
    logger.info("Mizan backend shutting down")


app = FastAPI(
    title="Mizan AI — المستشار القانوني الليبي الذكي",
    version="1.0.0",
    description="Production Full-Stack API: RAG legal assistant for Libyan law",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content=error_body("rate_limited", "عدد كبير من الطلبات. حاول بعد قليل."),
    ),
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(notifications.router)
app.include_router(voice.router)
app.include_router(admin.router)


@app.get("/api/health", tags=["meta"])
def public_health():
    return {
        "status": "ok" if ai_ready() else "starting",
        "service": "mizan-backend",
        "version": "1.0.0",
    }


def ai_ready() -> bool:
    from app.services.ai import ai_service

    return ai_service.status == "ready"


@app.get("/")
def root():
    return {"service": "Mizan AI API", "docs": "/docs"}
