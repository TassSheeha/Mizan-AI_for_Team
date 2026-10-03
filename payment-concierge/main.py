"""
Payment Concierge — FastAPI application entry point.

This is the backend service that ElevenLabs Conversational AI agents call
for tool execution (customer lookup, outstanding amount, solution ranking).

Run with:
    uvicorn payment_concierge.main:app --reload

Or after installing dependencies:
    cd payment-concierge && uvicorn main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from payment_concierge.config.settings import settings
from payment_concierge.routers import customer, outstanding, solutions, webhooks

app = FastAPI(
    title="Payment Concierge — Backend API",
    description=(
        "Backend service for the Ignyte Payment Concierge voice agent. "
        "Provides tool-execution endpoints that ElevenLabs Conversational AI "
        "agents call during collections calls: customer lookup, outstanding "
        "amount, settlement solution ranking. Built on the 14-field schema "
        "(6 CBUAE-locked compliance fields + 8 bank-configurable fields)."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(customer.router)
app.include_router(outstanding.router)
app.include_router(solutions.router)
app.include_router(webhooks.router)


@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "payment-concierge",
        "version": "0.1.0",
        "backend": settings.rule_engine_backend,
    }