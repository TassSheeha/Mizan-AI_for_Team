# Payment Concierge — Architecture overview

## System

```
┌─────────────────────────────────────────────────────────────────┐
│                       ElevenLabs Cloud                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Conversational AI Agent                                  │    │
│  │  ┌────────┐  ┌────────┐  ┌────────┐                     │    │
│  │  │  TTS   │  │  STT   │  │  LLM   │                     │    │
│  │  └────────┘  └────────┘  └────────┘                     │    │
│  │                     │                                     │    │
│  │         Tool: lookup_customer    ─── HTTP POST ───        │    │
│  │         Tool: get_outstanding    ─── HTTP POST ───        │    │
│  │         Tool: rank_solutions     ─── HTTP POST ───        │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    HTTPS / X-Api-Key
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   Your Backend (FastAPI)                         │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  /elevenlabs/webhook  →  tool router                      │    │
│  │  /customer/lookup     →  rule_engine.lookup_customer()     │    │
│  │  /outstanding/amount  →  rule_engine + compliance          │    │
│  │  /solutions/rank      →  rule_engine.rank_solutions()      │    │
│  │  /health              →  health check                      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                        │                                        │
│  ┌─────────────────────▼───────────────────────────────────┐     │
│  │  Rule Engine                                            │     │
│  │  ┌──────────────┐    ┌──────────────────────────────┐   │     │
│  │  │ Compliance   │    │ Bank Configurations           │   │     │
│  │  │ Floor (6     │    │ ┌──────────────────────────┐ │   │     │
│  │  │ locked       │    │ │ EMIRATES_NBD (fixture)  │ │   │     │
│  │  │ CBUAE fields)│    │ │ ADCB (when DB active)   │ │   │     │
│  │  └──────────────┘    │ │ ...                     │ │   │     │
│  │                      │ └──────────────────────────┘ │   │     │
│  │                      └──────────────────────────────┘   │     │
│  └──────────────────────────────────────────────────────────┘     │
│                        │                                        │
│  ┌─────────────────────▼───────────────────────────────────┐     │
│  │  Pratibha's Rule Engine (Excel → DB)                     │     │
│  │  Due 7-8 Oct, hard deadline 9 Oct                        │     │
│  └──────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────┘
```

## Key design decisions

### 1. Pre-computed solutions, no live lookups

The brain pre-computes the exact outstanding amount + ranked options _before_
the call. The call itself is pure execution/persuasion with no live lookups.
This makes the ElevenLabs agent fast and deterministic — it already has
everything it needs in context.

### 2. Compliance floor is enforced at the backend, not in the agent

The 6 CBUAE-locked fields (contact window, disclosure, hardship, etc.) are
enforced by the compliance service. The agent is told about them via system
context, but the backend refuses any request that violates them. This ensures
regulatory compliance even if the agent's LLM produces an unconstrained output.

### 3. Fixture → DB migration path

Until Pratibha's Excel model is built (7-8 Oct), the rule engine runs in
`fixture` mode with in-memory test data (3 sample customers, Emirates NBD
config). When the DB is ready, set `RULE_ENGINE_BACKEND=db` and the same
service layer switches to database queries with no code changes in the routers.

### 4. ElevenLabs owns TTS, STT, and LLM routing

The agent handles voice transcription (STT), speech generation (TTS), and
the conversational LLM. This backend is not involved in voice processing.
It only serves structured data via webhook tools.

## Data flow for a typical call

1. ElevenLabs agent starts the call (outbound dial via Telco API)
2. Agent greets customer, discloses per CBUAE requirements
3. Agent calls `lookup_customer` tool → backend returns customer + compliance
4. Agent calls `get_outstanding_amount` → backend returns balance with breakdown
5. Agent calls `rank_solutions` → backend returns ranked settlement options
6. Agent presents options, negotiates, handles objections (all LLM-driven)
7. If customer agrees to PTP/settlement, agent logs the outcome
8. Agent closes the call with recording-disclosure script