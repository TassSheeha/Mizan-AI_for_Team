# ElevenLabs — Agent definitions for the Payment Concierge

This directory holds the agent definitions that configure how ElevenLabs
Conversational AI agents behave during collections calls.

## Structure

```
elevenlabs/
├── agents/           # Agent YAML/JSON definitions
│   └── README.md
└── workflows/        # Workflow definitions
    └── README.md
```

## Workflow

1. Agent definitions are authored here (or exported from the ElevenLabs UI)
2. Each agent references one or more webhook tools from the backend
3. Agents are deployed to ElevenLabs and configured with the backend URL

## Current agents

- **collection-agent** — Main collections voice agent for Emirates NBD

## Adding a new agent

1. Create a JSON/YAML file in `agents/` describing the agent config
2. Define the tools it uses (must match `_TOOL_HANDLERS` in the backend)
3. Test against the backend's `/elevenlabs/webhook` endpoint