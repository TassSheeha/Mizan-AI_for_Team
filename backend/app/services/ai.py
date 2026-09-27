"""
app.services.ai — Thread-safe wrapper around the existing MizanAssistant.

IMPORTANT CONTRACT: this module NEVER modifies the `mizan` package, the RAG
pipeline (Tass02), or the LLM models. It only instantiates MizanAssistant with
the exact same Groq model (llama-3.3-70b-versatile) and exposes:

  - lazy background initialization (model + index load is heavy)
  - reload() after knowledge-base changes (admin document management)
  - blocking work offloaded to a threadpool via run_in_threadpool
"""

import logging
import sys
import threading
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings, PROJECT_ROOT

# Make the repo-root modules (mizan, config) importable from the backend.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("mizan.ai")

_START_EVENT = "start"
_READY_EVENT = "ready"
_FAILED_EVENT = "failed"


class AIService:
    def __init__(self) -> None:
        self._assistant = None
        self._lock = threading.Lock()
        self._status = _START_EVENT
        self._error: str | None = None
        self.started_at = None
        self._start_background()

    # ─── Lifecycle ────────────────────────────────────────────────────────────
    def _start_background(self) -> None:
        import os
        import time
        if os.environ.get("MIZAN_TEST_MODE") == "1":
            # Test hook: skip heavy index loading; tests stub the AI layer.
            self._status = "ready"
            return
        self.started_at = time.time()
        thread = threading.Thread(target=self._initialize, daemon=True, name="ai-init")
        thread.start()

    def _initialize(self) -> None:
        try:
            from mizan.assistant import MizanAssistant

            assistant = MizanAssistant(
                provider="groq",
                api_key=settings.GROQ_API_KEY or None,
                model_name=settings.GROQ_MODEL,
                retriever_mode="hybrid",
            )
            with self._lock:
                self._assistant = assistant
                self._status = _READY_EVENT
                self._error = None
            logger.info("AI layer ready (model=%s, provider=groq)", settings.GROQ_MODEL)
        except Exception as exc:  # pragma: no cover - depends on local index
            with self._lock:
                self._assistant = None
                self._status = _FAILED_EVENT
                self._error = str(exc)
            logger.exception("AI layer failed to initialize")

    def reload(self) -> None:
        """Re-create the assistant after knowledge-base changes (add/delete docs)."""
        with self._lock:
            self._assistant = None
            self._status = _START_EVENT
        self._initialize()

    # ─── State ────────────────────────────────────────────────────────────────
    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def _get(self):
        with self._lock:
            assistant = self._assistant
        if assistant is None:
            raise RuntimeError("AI layer is not ready yet")
        return assistant

    # ─── Public API (async, blocking work in threadpool) ─────────────────────
    async def ask_stream(self, query: str, top_k: int, mode: str,
                         filters: dict | None, chat_history: list[dict]) -> dict:
        assistant = self._get()
        return await run_in_threadpool(
            assistant.ask_stream,
            query, top_k, mode, filters, chat_history,
        )

    async def finish_stream(self, raw_text: str) -> str:
        assistant = self._get()
        return await run_in_threadpool(assistant.finish_stream, raw_text)

    # ─── Sync API (used inside the SSE sync generator, runs in threadpool) ───
    def ask_stream_sync(self, query: str, top_k: int, mode: str,
                        filters: dict | None, chat_history: list[dict]) -> dict:
        return self._get().ask_stream(
            query=query, top_k=top_k, mode=mode,
            filters=filters, chat_history=chat_history,
        )

    def finish_stream_sync(self, raw_text: str) -> str:
        return self._get().finish_stream(raw_text)

    def provider_name(self) -> str:
        try:
            return str(self._get().generator.provider)
        except RuntimeError:
            return "loading"


ai_service = AIService()
