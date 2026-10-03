"""
Payment Concierge — Solutions ranking endpoint.
Pre-computes ranked settlement options for a customer before the call starts.
"""

from fastapi import APIRouter, HTTPException

from payment_concierge.schemas.models import (
    ProductType,
    RankSolutionsRequest,
    RankSolutionsResponse,
    SolutionItem,
)
from payment_concierge.services.compliance import build_compliance_floor
from payment_concierge.services.rule_engine import lookup_customer, rank_solutions

router = APIRouter(prefix="/solutions", tags=["solutions"])


@router.post("/rank", response_model=RankSolutionsResponse)
def rank_payment_solutions(req: RankSolutionsRequest):
    """
    Pre-compute the ranked settlement options for a customer.
    The ElevenLabs agent calls this at the start of a call to know which
    solutions to present. No live lookups during the call — everything is
    pre-computed so the agent stays fast and deterministic.
    """
    customer = lookup_customer(
        identifier=req.customer_id, bank_id=req.bank_id
    )
    if not customer:
        raise HTTPException(
            status_code=404,
            detail=f"Customer {req.customer_id} not found",
        )

    solutions = rank_solutions(customer, bank_id=req.bank_id)

    compliance = build_compliance_floor(
        institution_name="Emirates NBD",
        calling_agent_name="Mizan Assistant",
    )

    return RankSolutionsResponse(
        solutions=solutions,
        compliance_floor=compliance,
    )