# Venkat Sairam — ElevenLabs Agent Workflow Guide

## What you own

You are building the **ElevenLabs agent workflows** for the Payment Concierge
— the conversational AI layer that handles collections calls. Your workstream
lives in these directories:

| Directory | What it's for |
|-----------|---------------|
| `elevenlabs/agents/` | Agent definition files (JSON/YAML) |
| `elevenlabs/workflows/` | Workflow definitions (call flow scripts) |
| `payment-concierge/routers/webhooks.py` | The webhook endpoints your agents call |

## How the backend works

The backend (`payment-concierge/`) is a FastAPI service that exposes endpoints
for the ElevenLabs agent to call as tools. Here's what you need to know:

```
Your Agent (ElevenLabs)                     Backend (this repo)
    │                                              │
    │  POST /elevenlabs/webhook                    │
    │  { tool_name:"lookup_customer",              │
    │    arguments:{customer_identifier:"ACC-001"} }│
    │ ─────────────────────────────────────────►    │
    │                                              │
    │  { result: { found: true, customer: {...} } }│
    │ ◄─────────────────────────────────────────    │
```

**Currently in fixture mode** — the backend returns test data for 3 sample
customers (ACC-001, ACC-002, ACC-003). No real bank data or DB needed yet.

## Your setup

### Prerequisites

- Python 3.10+
- `uv` package manager (recommended) or `pip`
- Access to ElevenLabs Conversational AI (ask Shameer for the shared workspace)

### Getting started

```bash
# From the repo root
cd payment-concierge

# Install backend dependencies
uv pip install -r requirements.txt

# Copy and configure .env
cp .env.example .env
# Ask Shameer for the ELEVENLABS_API_KEY value

# Start the backend
uvicorn main:app --reload --port 8000
```

### Verify the backend works

```bash
# Health check
curl http://localhost:8000/health

# Customer lookup
curl -X POST http://localhost:8000/customer/lookup \
  -H "Content-Type: application/json" \
  -d '{"customer_identifier":"ACC-001"}'

# List registered tools
curl http://localhost:8000/elevenlabs/tools
```

### Connecting the ElevenLabs agent

1. In the ElevenLabs agent builder, create a new Conversation AI agent
2. Add a **Tool** of type "Webhook" for each endpoint you need:
   - `lookup_customer` → `/elevenlabs/webhook`
   - `get_outstanding_amount` → `/elevenlabs/webhook`
   - `rank_solutions` → `/elevenlabs/webhook`
3. Add the `X-Api-Key` header with your backend's API key
4. Configure the system prompt with compliance floor context
5. Deploy and test with a voice call

## The 14-field schema (quick reference)

**6 locked (CBUAE — not bank-editable):**
`contact_window`, `regulatory_triggers`, `disclosure_script`,
`third_party_disclosure`, `hardship_offer_log`, `call_recording_retention`

**8 configurable (per-bank):**
`product_type`, `dpd_buckets[]`, `contact_frequency_cap`, `escalation_tiers[]`,
`settlement_authority_matrix[]`, `ptp_policy`, `legal_referral_dpd`,
`write_off_dpd`, `aecb_reporting`

See `payment-concierge/schemas/models.py` for the full Pydantic definitions.

## Dependencies you're waiting on

| Dependency | Owner | Status | Notes |
|------------|-------|--------|-------|
| ElevenLabs API key + workspace | Shameer | Running | Shared workspace invite sent; full API key pending |
| Narayan's starter package | Narayan | Running | PR and package coming; check for updates |
| Agent definition export method | You | — | Once the backend is stable, decide agent file format |
| Pratibha's rule engine (Excel → DB) | Pratibha | Due 7-8 Oct | Backend will switch to DB mode; router APIs won't change |

## Your workstream

1. **Week 1 (3-4 Oct):** Learn ElevenLabs agent builder, validate against the
   backend fixture data. Confirm the webhook flow works end-to-end.
2. **Week 1 (5-7 Oct):** Build the agent workflow — call flow, scripts,
   escalation logic. Coordinate with Layla on product-level stories.
3. **Week 2 (8-9 Oct):** Integrate with Pratibha's rule engine (DB mode).
   Stable build target: **9 Oct**.
4. **Demo prep (26-27 Oct):** Voice agent demo at the Ignyte Banking Hackathon.

## Questions?

- **Backend questions** — Check the code in `payment-concierge/` or ask Coder John
- **ElevenLabs workspace** — Ask Shameer for the shared workspace invite
- **PRD / scope** — Ask Shameer for the shared Drive link to
  "Payment Concierge PRD version 0.3"
- **Product-level stories** — Coordinate with Layla (writer profile)