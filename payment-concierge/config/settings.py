"""
Payment Concierge — Application settings.
Loaded from environment variables with sensible defaults for local dev.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    # ── Server ──────────────────────────────────────────────────────────────
    host: str = os.getenv("PC_HOST", "0.0.0.0")
    port: int = int(os.getenv("PC_PORT", "8000"))
    log_level: str = os.getenv("PC_LOG_LEVEL", "info")

    # ── ElevenLabs integration ──────────────────────────────────────────────
    # Shared API key the ElevenLabs agent uses to authenticate webhook calls
    # to this backend. Set via environment variable; no default in source.
    elevenlabs_api_key: Optional[str] = os.getenv("ELEVENLABS_API_KEY")

    # ElevenLabs base URL for the Conversational AI SDK / agent API.
    # Prod: https://api.elevenlabs.io
    elevenlabs_base_url: str = os.getenv(
        "ELEVENLABS_BASE_URL", "https://api.elevenlabs.io"
    )

    # Published ElevenLabs agent ID (set once the agent is deployed)
    elevenlabs_agent_id: Optional[str] = os.getenv("ELEVENLABS_AGENT_ID")

    # ── Rule engine (Pratibha's model → DB) ────────────────────────────────
    # Until the Excel model → DB pipeline is built, the service runs with
    # in-memory fixture data keyed by bank identifier.
    rule_engine_backend: str = os.getenv(
        "RULE_ENGINE_BACKEND", "fixture"
    )  # "fixture" | "db"
    rule_engine_db_url: Optional[str] = os.getenv(
        "RULE_ENGINE_DB_URL",
    )
    default_bank_id: str = os.getenv(
        "DEFAULT_BANK_ID", "EMIRATES_NBD"
    )

    # ── CBUAE compliance floor ──────────────────────────────────────────────
    # These are regulatory constants from analyst-priya's memo (6 locked
    # fields).  Not configurable per bank — any attempt to widen them is
    # rejected by the compliance service.
    contact_window_start: str = "09:00"
    contact_window_end: str = "20:00"
    two_missed_payment_notice_enabled: bool = True
    mandatory_contact_dpd: int = 30
    mandatory_written_notice_dpd: int = 60
    monthly_notice_while_in_arrears: bool = True
    call_recording_retention_years: int = 5

    # ── CORS ────────────────────────────────────────────────────────────────
    allowed_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "PC_ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
    )


settings = Settings()