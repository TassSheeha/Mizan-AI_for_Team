"""
Payment Concierge — CBUAE compliance floor enforcement.

Analyst-priya's memo identified 6 locked CBUAE compliance fields that must
be enforced at the call-handling layer regardless of what the brain outputs.
This module provides the enforcement functions and assembles the ComplianceFloor
for every request.

Any attempt to widen the contact window, skip the per-call disclosure, or
remove the hardship-offer requirement is rejected here — these are not
bank-configurable.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from payment_concierge.schemas.models import (
    ComplianceFloor,
    ContactWindow,
    DisclosureScript,
    HardshipOfferLog,
    RegulatoryTriggers,
    SettlementOutcome,
    ThirdPartyDisclosure,
)

# ─── Constants (lifted from analyst-priya memo, CBUAE Consumer Protection
#      Standards 5.2.5) ─────────────────────────────────────────────────────

CONTACT_WINDOW = ContactWindow(start=time(9, 0), end=time(20, 0))
REGULATORY_TRIGGERS = RegulatoryTriggers(
    missed_payments_notice_at=2,
    mandatory_contact_at_dpd=30,
    mandatory_written_notice_at_dpd=60,
    monthly_notice_while_in_arrears=True,
)
CALL_RECORDING_RETENTION_YEARS = 5


def build_compliance_floor(
    institution_name: str = "Emirates NBD",
    calling_agent_name: str = "Mizan Assistant",
    department: str = "Collections",
    contact_number: str = "600-54-0000",
    working_hours: str = "9 AM - 8 PM",
    third_party: Optional[ThirdPartyDisclosure] = None,
    hardship: Optional[HardshipOfferLog] = None,
) -> ComplianceFloor:
    """
    Build the 6-field compliance floor for a call.
    Every parameter has a safe default; override institution_name and
    calling_agent_name per bank and per agent.
    """
    return ComplianceFloor(
        contact_window=CONTACT_WINDOW,
        regulatory_triggers=REGULATORY_TRIGGERS,
        disclosure_script=DisclosureScript(
            institution_name=institution_name,
            department=department,
            contact_number=contact_number,
            working_hours=working_hours,
            calling_agent_name=calling_agent_name,
        ),
        third_party_disclosure=third_party or ThirdPartyDisclosure(),
        hardship_offer_log=hardship or HardshipOfferLog(),
        call_recording_retention_years=CALL_RECORDING_RETENTION_YEARS,
    )


def is_within_contact_window(
    dt: Optional[datetime] = None,
) -> bool:
    """Return True if dt falls within the CBUAE contact window (09:00—20:00)."""
    t = (dt or datetime.now()).time()
    return CONTACT_WINDOW.start <= t <= CONTACT_WINDOW.end


def should_attempt_contact(
    dpd_days: int,
    missed_payments: int,
    last_contact_date: Optional[str] = None,
) -> dict:
    """
    Check whether regulatory triggers require contact.
    Returns a dict of triggered reasons rather than a bool, so the agent
    can script the call accordingly.
    """
    triggers: list[str] = []

    if missed_payments >= REGULATORY_TRIGGERS.missed_payments_notice_at:
        triggers.append("two_missed_payment_notice")

    if dpd_days >= REGULATORY_TRIGGERS.mandatory_contact_at_dpd:
        triggers.append(f"day_{REGULATORY_TRIGGERS.mandatory_contact_at_dpd}_contact")

    if dpd_days >= REGULATORY_TRIGGERS.mandatory_written_notice_at_dpd:
        triggers.append(
            f"day_{REGULATORY_TRIGGERS.mandatory_written_notice_at_dpd}_written_notice"
        )

    return {"should_attempt": bool(triggers), "triggers": triggers}


def validate_hardship_prerequisite(
    enforcement_action: str,
    hardship_offered: bool,
) -> tuple[bool, str]:
    """
    CBUAE 5.2.5.1: the bank MUST attempt to discuss financial hardship with the
    consumer BEFORE collection enforcement, collateral action, or legal
    proceedings.
    Returns (allowed, reason).
    """
    if enforcement_action in ("enforcement", "collateral", "legal"):
        if not hardship_offered:
            return (
                False,
                "Hardship discussion must be attempted before "
                f"{enforcement_action} (CBUAE 5.2.5.1)",
            )
    return (True, "")