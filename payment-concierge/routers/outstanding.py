"""
Payment Concierge — Outstanding amount endpoint.
Returns the current outstanding balance with a breakdown.
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException

from payment_concierge.schemas.models import OutstandingRequest, OutstandingResponse
from payment_concierge.services.compliance import build_compliance_floor
from payment_concierge.services.rule_engine import lookup_customer

router = APIRouter(prefix="/outstanding", tags=["outstanding"])


@router.post("/amount", response_model=OutstandingResponse)
def get_outstanding_amount(req: OutstandingRequest):
    """
    Return the outstanding amount for a customer, with principal/interest/fees
    breakdown. The ElevenLabs agent calls this to present the current balance
    to the customer during the conversation.
    """
    customer = lookup_customer(
        identifier=req.customer_id, bank_id=req.bank_id
    )
    if not customer:
        raise HTTPException(
            status_code=404,
            detail=f"Customer {req.customer_id} not found",
        )

    compliance = build_compliance_floor(
        institution_name="Emirates NBD",
        calling_agent_name="Mizan Assistant",
    )

    return OutstandingResponse(
        customer_id=customer.customer_id,
        customer_name=customer.name,
        total_outstanding=customer.total_outstanding,
        principal=customer.outstanding_principal,
        interest=customer.accrued_interest,
        fees=customer.late_fees,
        currency="AED",
        dpd_days=customer.dpd_days,
        compliance_floor=compliance,
    )