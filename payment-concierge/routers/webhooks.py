"""
Payment Concierge — ElevenLabs webhook receiver.
Receives tool-call requests from the ElevenLabs Conversational AI agent
and routes them to the appropriate backend function.

The webhook endpoint is what you configure in the ElevenLabs agent builder
under "Tools" → "Webhook". Each tool the agent is configured with will POST
here with the agent's tool name and arguments.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from payment_concierge.config.settings import settings
from payment_concierge.schemas.models import (
    CustomerLookupRequest,
    ElevenLabsWebhookPayload,
    ElevenLabsWebhookResponse,
    OutstandingRequest,
    RankSolutionsRequest,
)
from payment_concierge.services.rule_engine import lookup_customer, rank_solutions
from payment_concierge.services.compliance import build_compliance_floor

router = APIRouter(prefix="/elevenlabs", tags=["elevenlabs"])

API_KEY_HEADER = APIKeyHeader(name="X-Api-Key", auto_error=False)


def _verify_api_key(api_key: str | None) -> None:
    """Reject unauthenticated webhook calls."""
    configured_key = settings.elevenlabs_api_key
    if configured_key and (not api_key or api_key != configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing ElevenLabs API key",
        )


# Tool name → handler mapping
_TOOL_HANDLERS: dict[str, callable] = {}


def _register_tool(name: str):
    """Decorator to register a tool handler."""
    def wrapper(fn):
        _TOOL_HANDLERS[name] = fn
        return fn
    return wrapper


@_register_tool("lookup_customer")
def _handle_lookup(args: dict) -> dict:
    req = CustomerLookupRequest(**args)
    customer = lookup_customer(
        identifier=req.customer_identifier, bank_id=req.bank_id
    )
    if not customer:
        return {"found": False}
    return {
        "found": True,
        "customer": customer.model_dump(mode="json"),
        "compliance_floor": build_compliance_floor().model_dump(mode="json"),
    }


@_register_tool("get_outstanding_amount")
def _handle_outstanding(args: dict) -> dict:
    req = OutstandingRequest(**args)
    customer = lookup_customer(
        identifier=req.customer_id, bank_id=req.bank_id
    )
    if not customer:
        return {"error": f"Customer {req.customer_id} not found"}
    return {
        "customer_id": customer.customer_id,
        "customer_name": customer.name,
        "total_outstanding": str(customer.total_outstanding),
        "principal": str(customer.outstanding_principal),
        "interest": str(customer.accrued_interest),
        "fees": str(customer.late_fees),
        "dpd_days": customer.dpd_days,
    }


@_register_tool("rank_solutions")
def _handle_rank_solutions(args: dict) -> dict:
    req = RankSolutionsRequest(**args)
    customer = lookup_customer(
        identifier=req.customer_id, bank_id=req.bank_id
    )
    if not customer:
        return {"error": f"Customer {req.customer_id} not found"}
    solutions = rank_solutions(customer, bank_id=req.bank_id)
    return {
        "solutions": [s.model_dump(mode="json") for s in solutions],
    }


@router.post("/webhook", response_model=ElevenLabsWebhookResponse)
def webhook(
    payload: ElevenLabsWebhookPayload,
    api_key: str | None = API_KEY_HEADER,
):
    """
    Unified webhook endpoint for ElevenLabs agent tool calls.

    The agent calls this endpoint with the tool name and arguments.
    The router dispatches to the registered handler and returns the result.
    """
    _verify_api_key(api_key)

    handler = _TOOL_HANDLERS.get(payload.tool_name)
    if not handler:
        return ElevenLabsWebhookResponse(
            result={},
            error=f"Unknown tool: {payload.tool_name}",
        )

    try:
        result = handler(payload.arguments)
        return ElevenLabsWebhookResponse(result=result)
    except Exception as e:
        return ElevenLabsWebhookResponse(
            result={},
            error=str(e),
        )


@router.get("/tools")
def list_tools():
    """Return the list of registered tool names for introspection."""
    return {"tools": list(_TOOL_HANDLERS.keys())}