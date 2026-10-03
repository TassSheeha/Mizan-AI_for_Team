"""
Payment Concierge — Customer lookup endpoint.
Returns account data and compliance context for the ElevenLabs agent.
"""

from fastapi import APIRouter, HTTPException

from payment_concierge.schemas.models import (
    CustomerLookupRequest,
    CustomerLookupResponse,
)
from payment_concierge.services.compliance import build_compliance_floor
from payment_concierge.services.rule_engine import get_bank_config, lookup_customer

router = APIRouter(prefix="/customer", tags=["customer"])


@router.post("/lookup", response_model=CustomerLookupResponse)
def customer_lookup(req: CustomerLookupRequest):
    """
    Look up a customer by identifier (account number, phone, or email).
    Returns account data, the CBUAE compliance floor, and bank config.
    Called by the ElevenLabs agent as a tool during a collections call.
    """
    customer = lookup_customer(
        identifier=req.customer_identifier, bank_id=req.bank_id
    )
    if not customer:
        return CustomerLookupResponse(
            found=False,
            customer=None,
            compliance_floor=build_compliance_floor(),
        )

    bank_config = get_bank_config(req.bank_id)
    if not bank_config:
        bank_config = None

    compliance = build_compliance_floor(
        institution_name="Emirates NBD",
        calling_agent_name="Mizan Assistant",
    )

    return CustomerLookupResponse(
        found=True,
        customer=customer,
        compliance_floor=compliance,
        bank_config=bank_config,
    )