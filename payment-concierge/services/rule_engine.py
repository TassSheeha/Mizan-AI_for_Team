"""
Payment Concierge — Rule engine interface.

Pratibha's Excel model (due 7-8 Oct) defines the rule engine that determines
customer treatment based on bank-specific tuning parameters. Until that model
is built and connected via DB, this module serves fixture data.

The fixture backend ships with Emirates NBD defaults (marked as assumptions,
not verified facts — per analyst-priya's memo). Swap to the DB backend by
setting RULE_ENGINE_BACKEND=db when Pratibha's model lands.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from payment_concierge.config.settings import settings
from payment_concierge.schemas.models import (
    AECBReporting,
    BankConfig,
    BucketLabel,
    CustomerAccount,
    DPDBucket,
    EscalationTier,
    PTPPolicy,
    ProductType,
    SettlementAuthority,
    SettlementOutcome,
    SolutionItem,
)


# ─── Fixture data ─────────────────────────────────────────────────────────────


_FIXTURE_EMIRATES_NBD = BankConfig(
    bank_id="EMIRATES_NBD",
    product_type=ProductType.conventional,
    dpd_buckets=[
        DPDBucket(bucket_id="curr", dpd_min=0, dpd_max=29, label=BucketLabel.current,
                   contact_frequency_cap_per_day=1, contact_frequency_cap_per_week=3),
        DPDBucket(bucket_id="under", dpd_min=30, dpd_max=89, label=BucketLabel.underperforming,
                   contact_frequency_cap_per_day=2, contact_frequency_cap_per_week=5),
        DPDBucket(bucket_id="sub", dpd_min=90, dpd_max=120, label=BucketLabel.substandard,
                   contact_frequency_cap_per_day=3, contact_frequency_cap_per_week=7),
        DPDBucket(bucket_id="doubt", dpd_min=121, dpd_max=180, label=BucketLabel.doubtful,
                   contact_frequency_cap_per_day=2, contact_frequency_cap_per_week=4),
        DPDBucket(bucket_id="wo", dpd_min=181, dpd_max=9999, label=BucketLabel.write_off,
                   contact_frequency_cap_per_day=1, contact_frequency_cap_per_week=2),
    ],
    escalation_tiers=[
        EscalationTier(tier_id="t1", dpd_range="0-29",
                       channel_mix=["sms", "phone"],
                       script_intensity_level=1),
        EscalationTier(tier_id="t2", dpd_range="30-89",
                       channel_mix=["phone", "email", "sms"],
                       script_intensity_level=2,
                       human_handoff_condition="ptp_breach_2"),
        EscalationTier(tier_id="t3", dpd_range="90-120",
                       channel_mix=["phone", "email", "registered_post"],
                       script_intensity_level=3,
                       human_handoff_condition="hardship_refusal"),
        EscalationTier(tier_id="t4", dpd_range="121-180",
                       channel_mix=["phone", "registered_post", "legal_notice"],
                       script_intensity_level=4,
                       human_handoff_condition="always"),
    ],
    settlement_authority_matrix=[
        SettlementAuthority(tier_id="t1", max_discount_pct=Decimal("0"), requires_human_approval=True),
        SettlementAuthority(tier_id="t2", max_discount_pct=Decimal("5"), requires_human_approval=False),
        SettlementAuthority(tier_id="t3", max_discount_pct=Decimal("15"), requires_human_approval=False),
        SettlementAuthority(tier_id="t4", max_discount_pct=Decimal("25"), requires_human_approval=False),
    ],
    ptp_policy=PTPPolicy(max_ptp_per_cycle=2, ptp_window_days=7,
                           re_ptp_allowed=True, breach_action="escalate"),
    legal_referral_dpd=120,
    write_off_dpd=180,
    aecb_reporting=AECBReporting(enabled=True, frequency="monthly"),
)

_FIXTURE_CUSTOMERS: dict[str, CustomerAccount] = {
    "ACC-001": CustomerAccount(
        customer_id="ACC-001",
        name="Ahmed Al Mansoori",
        phone="+971-50-123-4567",
        email="ahmed@example.com",
        product_type=ProductType.conventional,
        outstanding_principal=Decimal("15000.00"),
        accrued_interest=Decimal("1250.00"),
        late_fees=Decimal("350.00"),
        total_outstanding=Decimal("16600.00"),
        dpd_days=45,
        current_bucket="under",
        missed_payments=2,
        ptp_breaches=0,
        in_hardship_program=False,
        customer_since="2022-03-15",
        last_contact_date="2026-09-28",
    ),
    "ACC-002": CustomerAccount(
        customer_id="ACC-002",
        name="Fatima Al Zaabi",
        phone="+971-55-987-6543",
        email=None,
        product_type=ProductType.conventional,
        outstanding_principal=Decimal("45000.00"),
        accrued_interest=Decimal("5100.00"),
        late_fees=Decimal("1200.00"),
        total_outstanding=Decimal("51300.00"),
        dpd_days=95,
        current_bucket="sub",
        missed_payments=4,
        ptp_breaches=1,
        in_hardship_program=True,
        customer_since="2020-11-01",
        last_contact_date="2026-10-01",
    ),
    "ACC-003": CustomerAccount(
        customer_id="ACC-003",
        name="Saeed Al Ketbi",
        phone="+971-54-555-1212",
        email="saeed@outlook.com",
        product_type=ProductType.conventional,
        outstanding_principal=Decimal("5000.00"),
        accrued_interest=Decimal("200.00"),
        late_fees=Decimal("75.00"),
        total_outstanding=Decimal("5275.00"),
        dpd_days=10,
        current_bucket="curr",
        missed_payments=1,
        ptp_breaches=0,
        in_hardship_program=False,
        customer_since="2024-01-10",
        last_contact_date="2026-09-20",
    ),
}


# ─── Public API ────────────────────────────────────────────────────────────────


def get_bank_config(bank_id: str) -> Optional[BankConfig]:
    """
    Return the bank configuration for the given bank.
    Fixture backend: only EMIRATES_NBD is available.
    DB backend: queries the rule engine database.
    """
    if settings.rule_engine_backend == "db":
        # TODO: implement when Pratibha's model lands
        raise NotImplementedError("DB backend not yet implemented")

    if bank_id == "EMIRATES_NBD":
        return _FIXTURE_EMIRATES_NBD
    return None


def lookup_customer(
    identifier: str, bank_id: str = "EMIRATES_NBD"
) -> Optional[CustomerAccount]:
    """
    Look up a customer by account number, national ID, or phone.
    """
    # Fixture: match by customer_id directly
    for cid, account in _FIXTURE_CUSTOMERS.items():
        if (
            identifier == cid
            or identifier == account.phone
            or (account.email and identifier == account.email)
        ):
            return account
    return None


def get_bucket_for_dpd(dpd_days: int, bank_id: str = "EMIRATES_NBD") -> Optional[str]:
    """Return the bucket ID for a given DPD value."""
    config = get_bank_config(bank_id)
    if not config:
        return None
    for bucket in config.dpd_buckets:
        if bucket.dpd_min <= dpd_days <= bucket.dpd_max:
            return bucket.bucket_id
    return config.dpd_buckets[-1].bucket_id if config.dpd_buckets else None


def rank_solutions(
    customer: CustomerAccount,
    bank_id: str = "EMIRATES_NBD",
) -> list[SolutionItem]:
    """
    Pre-compute ranked payment solutions for a customer.
    This is the brain's core output — before the call is placed, the backend
    computes the possible settlement options so the ElevenLabs agent can
    present them without live lookups.
    """
    config = get_bank_config(bank_id)
    if not config:
        return []

    bucket_id = get_bucket_for_dpd(customer.dpd_days, bank_id)
    total = customer.total_outstanding

    # Find the right settlement authority
    authority = None
    if config.settlement_authority_matrix:
        for tier in config.settlement_authority_matrix:
            if not bucket_id or tier.tier_id.startswith(bucket_id[:2]):
                authority = tier
                break
        if not authority:
            authority = config.settlement_authority_matrix[-1]

    solutions: list[SolutionItem] = []

    # 1. Full settlement
    solutions.append(
        SolutionItem(
            solution_id="full",
            label="Full settlement",
            description="Pay the full outstanding amount and close the account.",
            estimated_payment=total,
            savings_vs_full=Decimal("0"),
            requires_human_approval=False,
            rank=1,
        )
    )

    # 2. Discounted settlement (authority-aware)
    if authority and authority.max_discount_pct and authority.max_discount_pct > 0:
        discount_amount = (
            total * authority.max_discount_pct / Decimal("100")
        ).quantize(Decimal("0.01"))
        discounted = (total - discount_amount).quantize(Decimal("0.01"))
        solutions.append(
            SolutionItem(
                solution_id="discounted",
                label="Discounted settlement",
                description=(
                    f"One-time payment with {authority.max_discount_pct}% discount "
                    f"({config.settlement_authority_matrix.index(authority) + 1} "
                    "tier authority)."
                ),
                estimated_payment=discounted,
                savings_vs_full=discount_amount,
                requires_human_approval=authority.requires_human_approval
                if customer.dpd_days < 90
                else False,
                rank=2,
            )
        )

    # 3. PTP — instalment plan
    instalment_amount = (total / Decimal("3")).quantize(Decimal("0.01"))
    solutions.append(
        SolutionItem(
            solution_id="ptp",
            label="Instalment plan (PTP)",
            description="Split into 3 monthly payments.",
            estimated_payment=instalment_amount,
            savings_vs_full=Decimal("0"),
            requires_human_approval=False,
            rank=3,
        )
    )

    # 4. Hardship program (if eligible)
    if customer.missed_payments >= 2:
        solutions.append(
            SolutionItem(
                solution_id="hardship",
                label="Hardship program",
                description="Reduced payments via financial hardship program.",
                estimated_payment=(total / Decimal("6")).quantize(Decimal("0.01")),
                savings_vs_full=total - (total / Decimal("6")).quantize(Decimal("0.01")),
                requires_human_approval=True,
                rank=4,
            )
        )

    # Re-rank and assign
    for i, s in enumerate(solutions):
        s.rank = i + 1

    return solutions