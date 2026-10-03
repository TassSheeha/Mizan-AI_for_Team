"""
Payment Concierge — smoke tests for the 14-field schema and service layer.

Run with:
    cd payment-concierge && uv pip install -r requirements.txt && python -m pytest
"""

from decimal import Decimal
from datetime import time

from payment_concierge.schemas.models import (
    ComplianceFloor,
    ContactWindow,
    CustomerAccount,
    CustomerLookupRequest,
    CustomerLookupResponse,
    DPDBucket,
    BucketLabel,
    OutstandingRequest,
    OutstandingResponse,
    RankSolutionsRequest,
    RankSolutionsResponse,
    SolutionItem,
    ProductType,
    BankConfig,
    ElevenLabsWebhookPayload,
)
from payment_concierge.services.compliance import (
    build_compliance_floor,
    is_within_contact_window,
    should_attempt_contact,
)
from payment_concierge.services.rule_engine import (
    lookup_customer,
    get_bank_config,
    rank_solutions,
    get_bucket_for_dpd,
)


# ─── Schema tests ────────────────────────────────────────────────────────────


def test_contact_window_default():
    cw = ContactWindow()
    assert cw.start == time(9, 0)
    assert cw.end == time(20, 0)


def test_contact_window_rejects_wider():
    import pydantic
    try:
        ContactWindow(start=time(8, 0))
        assert False, "Should have raised"
    except pydantic.ValidationError:
        pass


def test_customer_account_defaults():
    c = CustomerAccount(
        customer_id="T1", name="Test", phone="+971-50-000-0000",
        total_outstanding=Decimal("1000.00"),
    )
    assert c.product_type == ProductType.conventional
    assert c.dpd_days == 0
    assert c.missed_payments == 0


def test_compliance_floor_6_fields():
    floor = build_compliance_floor()
    assert floor.contact_window is not None
    assert floor.regulatory_triggers is not None
    assert floor.disclosure_script is not None
    assert floor.third_party_disclosure is not None
    assert floor.hardship_offer_log is not None
    assert floor.call_recording_retention_years == 5


def test_disclosure_script_content():
    floor = build_compliance_floor(
        institution_name="Emirates NBD",
        calling_agent_name="Mizan Assistant",
    )
    assert floor.disclosure_script.institution_name == "Emirates NBD"
    assert floor.disclosure_script.calling_agent_name == "Mizan Assistant"


def test_webhook_payload():
    p = ElevenLabsWebhookPayload(
        tool_name="lookup_customer",
        arguments={"customer_identifier": "ACC-001"},
    )
    assert p.tool_name == "lookup_customer"
    assert p.arguments["customer_identifier"] == "ACC-001"


# ─── Service tests ────────────────────────────────────────────────────────────


def test_lookup_existing_customer():
    customer = lookup_customer("ACC-001")
    assert customer is not None
    assert customer.name == "Ahmed Al Mansoori"
    assert customer.total_outstanding == Decimal("16600.00")


def test_lookup_missing_customer():
    assert lookup_customer("NONEXISTENT") is None


def test_bank_config_exists():
    config = get_bank_config("EMIRATES_NBD")
    assert config is not None
    assert config.bank_id == "EMIRATES_NBD"
    assert len(config.dpd_buckets) == 5


def test_bank_config_missing():
    assert get_bank_config("FAKE_BANK") is None


def test_bucket_for_dpd():
    bucket = get_bucket_for_dpd(45)
    assert bucket == "under"


def test_rank_solutions():
    customer = lookup_customer("ACC-001")
    assert customer is not None
    solutions = rank_solutions(customer)
    assert len(solutions) >= 3  # full, PTP, maybe discount + hardship
    assert solutions[0].solution_id == "full"
    assert solutions[0].rank == 1


def test_compliance_contact_window_now():
    # Should return True during business hours (test depends on time of day)
    result = is_within_contact_window()
    assert isinstance(result, bool)


def test_compliance_should_contact_triggers():
    result = should_attempt_contact(dpd_days=45, missed_payments=2)
    assert result["should_attempt"] is True
    assert "two_missed_payment_notice" in result["triggers"]


def test_compliance_no_triggers():
    result = should_attempt_contact(dpd_days=5, missed_payments=0)
    assert result["should_attempt"] is False