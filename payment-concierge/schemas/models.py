"""
Payment Concierge — 14-field data models.

Six of these fields are CBUAE regulatory constants (the compliance floor).
Eight are bank-configurable and come from Pratibha's rule engine.

Reference: analyst-priya memo (t_634a6c11 / bank-collections-parameter-memo.md)
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────


class ProductType(str, Enum):
    conventional = "conventional"
    islamic = "islamic"


class BucketLabel(str, Enum):
    current = "current"
    underperforming = "underperforming"
    substandard = "substandard"
    doubtful = "doubtful"
    write_off = "write_off"


class SettlementOutcome(str, Enum):
    full = "full"
    partial = "partial"
    ptp = "ptp"
    hardship = "hardship"
    failed = "failed"


# ─── Compliance-floor models (locked / non-configurable) ────────────────────────


class ContactWindow(BaseModel):
    """CBUAE-mandated contact window — 09:00—20:00, none wider."""

    start: time = time(9, 0)
    end: time = time(20, 0)

    @field_validator("start")
    @classmethod
    def start_not_before_0900(cls, v: time) -> time:
        if v < time(9, 0):
            raise ValueError("contact_window start must be >= 09:00 (CBUAE floor)")
        return v

    @field_validator("end")
    @classmethod
    def end_not_after_2000(cls, v: time) -> time:
        if v > time(20, 0):
            raise ValueError("contact_window end must be <= 20:00 (CBUAE floor)")
        return v


class RegulatoryTriggers(BaseModel):
    """CBUAE-mandated regulatory triggers — all three independent."""

    missed_payments_notice_at: int = 2
    mandatory_contact_at_dpd: int = 30
    mandatory_written_notice_at_dpd: int = 60
    monthly_notice_while_in_arrears: bool = True


class DisclosureScript(BaseModel):
    """Per-call disclosure required by CBUAE 5.2.5.6(d)."""

    institution_name: str
    department: str = ""
    contact_number: str
    working_hours: str
    calling_agent_name: str


class ThirdPartyDisclosure(BaseModel):
    """Populated only when a case is referred to a third-party agency."""

    assigned: bool = False
    agency_name: Optional[str] = None
    amount_being_collected: Optional[Decimal] = None
    authority_granted: Optional[str] = None


class HardshipOfferLog(BaseModel):
    """CBUAE 5.2.5.1 — must be logged before any enforcement action."""

    offered: bool = False
    timestamp: Optional[str] = None
    outcome: Optional[str] = None


class ComplianceFloor(BaseModel):
    """
    Aggregate of all six CBUAE-locked fields.
    Injected on every call as context for the ElevenLabs agent.
    """

    contact_window: ContactWindow = Field(default_factory=ContactWindow)
    regulatory_triggers: RegulatoryTriggers = Field(
        default_factory=RegulatoryTriggers
    )
    disclosure_script: Optional[DisclosureScript] = None
    third_party_disclosure: ThirdPartyDisclosure = Field(
        default_factory=ThirdPartyDisclosure
    )
    hardship_offer_log: HardshipOfferLog = Field(
        default_factory=HardshipOfferLog
    )
    call_recording_retention_years: int = 5


# ─── Bank-configurable models ──────────────────────────────────────────────────


class DPDBucket(BaseModel):
    """A single bucket in the bank's collections segmentation."""

    bucket_id: str
    dpd_min: int
    dpd_max: int
    label: BucketLabel
    contact_frequency_cap_per_day: int = 3
    contact_frequency_cap_per_week: int = 10


class EscalationTier(BaseModel):
    tier_id: str
    dpd_range: str  # e.g. "90-120"
    channel_mix: list[str] = []
    script_intensity_level: int = 1
    human_handoff_condition: Optional[str] = None


class SettlementAuthority(BaseModel):
    tier_id: str
    max_discount_pct: Optional[Decimal] = None
    max_waiver_amount: Optional[Decimal] = None
    requires_human_approval: bool = False


class PTPPolicy(BaseModel):
    """Promise-To-Pay policy per bank."""

    max_ptp_per_cycle: int = 2
    ptp_window_days: int = 7
    re_ptp_allowed: bool = True
    breach_action: str = "escalate"


class AECBReporting(BaseModel):
    enabled: bool = True
    frequency: str = "monthly"


class BankConfig(BaseModel):
    """
    Per-bank configuration: the 8 bank-configurable fields.
    Default values are Emirates NBD-plausible assumptions, not verified facts.
    """

    bank_id: str
    product_type: ProductType = ProductType.conventional
    dpd_buckets: list[DPDBucket] = []
    escalation_tiers: list[EscalationTier] = []
    settlement_authority_matrix: list[SettlementAuthority] = []
    ptp_policy: PTPPolicy = Field(default_factory=PTPPolicy)
    legal_referral_dpd: int = 120
    write_off_dpd: int = 180
    aecb_reporting: AECBReporting = Field(default_factory=AECBReporting)


# ─── Customer models ────────────────────────────────────────────────────────────


class CustomerAccount(BaseModel):
    """A customer account with collections-relevant data."""

    customer_id: str
    name: str
    phone: str
    email: Optional[str] = None
    product_type: ProductType = ProductType.conventional
    outstanding_principal: Decimal = Decimal("0.00")
    accrued_interest: Decimal = Decimal("0.00")
    late_fees: Decimal = Decimal("0.00")
    total_outstanding: Decimal = Decimal("0.00")
    dpd_days: int = 0
    current_bucket: Optional[str] = None
    missed_payments: int = 0
    ptp_breaches: int = 0
    in_hardship_program: bool = False
    customer_since: Optional[str] = None
    last_contact_date: Optional[str] = None


# ─── Request / response models ─────────────────────────────────────────────────


class CustomerLookupRequest(BaseModel):
    customer_identifier: str = Field(
        ..., description="Account number, national ID, or phone number"
    )
    bank_id: str = "EMIRATES_NBD"


class CustomerLookupResponse(BaseModel):
    found: bool
    customer: Optional[CustomerAccount] = None
    compliance_floor: ComplianceFloor = Field(default_factory=ComplianceFloor)
    bank_config: Optional[BankConfig] = None


class OutstandingRequest(BaseModel):
    customer_id: str
    bank_id: str = "EMIRATES_NBD"
    include_breakdown: bool = True


class OutstandingResponse(BaseModel):
    customer_id: str
    customer_name: str
    total_outstanding: Decimal
    principal: Decimal
    interest: Decimal
    fees: Decimal
    currency: str = "AED"
    dpd_days: int
    compliance_floor: ComplianceFloor = Field(default_factory=ComplianceFloor)


class SolutionItem(BaseModel):
    solution_id: str
    label: str
    description: str
    estimated_payment: Decimal
    savings_vs_full: Decimal = Decimal("0.00")
    requires_human_approval: bool = False
    rank: int = 0


class RankSolutionsRequest(BaseModel):
    customer_id: str
    total_outstanding: Decimal
    dpd_days: int
    missed_payments: int
    prior_ptp_breaches: int = 0
    in_hardship_program: bool = False
    bank_id: str = "EMIRATES_NBD"
    product_type: ProductType = ProductType.conventional


class RankSolutionsResponse(BaseModel):
    solutions: list[SolutionItem] = []
    compliance_floor: ComplianceFloor = Field(default_factory=ComplianceFloor)


# ─── ElevenLabs webhook models ────────────────────────────────────────────────


class ElevenLabsWebhookPayload(BaseModel):
    """Standard payload from an ElevenLabs agent tool call."""

    tool_name: str
    tool_id: str = ""
    arguments: dict = {}
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None


class ElevenLabsWebhookResponse(BaseModel):
    result: dict = {}
    error: Optional[str] = None