"""app.core.logging — Structured logging setup + request/audit logging."""

import json
import logging
import sys
import time
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(exist_ok=True)

_AUDIT_LOGGER = logging.getLogger("mizan.audit")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = JsonFormatter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(LOG_DIR / "mizan.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("chromadb").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every API request with duration and status code."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            logging.getLogger("mizan.request").error(
                "%s %s → 500 (%.3fs)", request.method, request.url.path, duration
            )
            raise
        duration = time.perf_counter() - start
        logging.getLogger("mizan.request").info(
            "%s %s → %d (%.3fs)", request.method, request.url.path, response.status_code, duration
        )
        response.headers["X-Process-Time-Ms"] = f"{duration * 1000:.1f}"
        return response


def audit(action: str, user_id: int | None = None, detail: str = "") -> None:
    """Append an immutable audit-trail entry (console + file)."""
    _AUDIT_LOGGER.info("user=%s action=%s detail=%s", user_id, action, detail)
