# Payment Concierge — ElevenLabs Backend Integration

This is the backend service for the **Ignyte Payment Concierge** — an AI
voice agent for banking collections built on ElevenLabs Conversational AI.

## Architecture

```
ElevenLabs Agent                            Your Backend
┌────────────────────────┐     HTTP POST    ┌──────────────────────┐
│  TTS + STT + LLM      │ ────────────────> │  FastAPI web service  │
│                        │   X-Api-Key auth  │                      │
│  Tool: lookup_customer │                  │  /customer/lookup     │
│  Tool: get_outstanding │                  │  /outstanding/amount  │
│  Tool: rank_solutions  │                  │  /solutions/rank      │
│                        │                  │  /elevenlabs/webhook   │
│  14-field schema       │ <──────────────── │  /health              │
│  context injected      │    JSON response  └──────────┬───────────┘
└────────────────────────┘                               │
                                                         ▼
                                                ┌─────────────────┐
                                                │  Rule Engine     │
                                                │  (fixture / DB)  │
                                                │                  │
                                                │  14-field schema │
                                                │  (6 locked +     │
                                                │   8 configurable)│
                                                └─────────────────┘
```

**Key principle:** ElevenLabs is only the orchestrator (TTS, STT, LLM routing).
The main business logic stays in this backend. The agent calls our webhook
endpoints for tool execution; our backend does not run inside ElevenLabs.

## Quick start

```bash
# 1. Install dependencies
cd payment-concierge
uv pip install -r requirements.txt

# 2. Copy and configure environment
cp .env.example .env
# Edit .env → set ELEVENLABS_API_KEY

# 3. Run the server
uvicorn main:app --reload

# 4. Open the API docs
# http://localhost:8000/docs
```

## API endpoints

| Method | Path                    | Description                          |
|--------|-------------------------|--------------------------------------|
| POST   | /customer/lookup        | Look up a customer by identifier     |
| POST   | /outstanding/amount     | Get outstanding amount with breakdown|
| POST   | /solutions/rank         | Pre-compute ranked settlement options|
| POST   | /elevenlabs/webhook     | Unified webhook for agent tool calls |
| GET    | /elevenlabs/tools       | List registered tool names           |
| GET    | /health                 | Health check                         |

## Directory structure

```
payment-concierge/
├── main.py              # FastAPI app entry point
├── config/
│   └── settings.py      # Environment-based settings
├── schemas/
│   └── models.py        # 14-field schema (Pydantic models)
├── services/
│   ├── compliance.py    # CBUAE compliance floor enforcement
│   └── rule_engine.py   # Rule engine (fixture/DB backend)
├── routers/
│   ├── customer.py      # Customer lookup endpoint
│   ├── outstanding.py   # Outstanding amount endpoint
│   ├── solutions.py     # Solutions ranking endpoint
│   └── webhooks.py      # ElevenLabs webhook receiver
├── .env.example         # Environment template
└── requirements.txt     # Python dependencies
```

## The 14-field schema

6 locked CBUAE compliance fields (from analyst-priya's research):
1. `contact_window` — 09:00-20:00
2. `regulatory_triggers` — 2 missed payments, day-30/60 triggers
3. `disclosure_script` — per-call identification
4. `third_party_disclosure` — agency referral info
5. `hardship_offer_log` — pre-enforcement check
6. `call_recording_retention` — 5 years post-settlement

8 bank-configurable fields:
7. `product_type` — conventional / islamic
8. `dpd_buckets[]` — collections segmentation
9. `contact_frequency_cap` — per-bucket limits
10. `escalation_tiers[]` — escalation matrix
11. `settlement_authority_matrix[]` — discount/write-off authority
12. `ptp_policy` — promise-to-pay rules
13. `legal_referral_dpd` / `write_off_dpd` — exit points
14. `aecb_reporting` — credit bureau reporting config

See `payment_concierge/schemas/models.py` for the full definition.

## Connecting to ElevenLabs

1. In the ElevenLabs agent builder, create a **Tool** of type "Webhook"
2. Set the URL to `https://your-backend.com/elevenlabs/webhook`
3. Add the `X-Api-Key` header with your configured key
4. Register the tool names: `lookup_customer`, `get_outstanding_amount`,
   `rank_solutions`
5. The agent context should include the `compliance_floor` fields injected
   as system context so the agent knows the regulatory constraints

## Venkat's workstream

See `/docs/VENKAT_WORKFLOW.md` for the full workstream guide.