# ElevenLabs agent definitions

Place agent configuration files here. Expected format:

```json
{
  "agent_name": "collection-agent-emirates-nbd",
  "description": "Main collections voice agent for Emirates NBD",
  "language": "en",
  "voice": {
    "provider": "elevenlabs",
    "voice_id": "EXAVITQu4vr7SDsZ7KABjF"  // Rachel
  },
  "prompt": {
    "system_prompt": "You are a collections agent calling about an outstanding balance...",
    "tools": ["lookup_customer", "get_outstanding_amount", "rank_solutions"],
    "knowledge_base": []
  },
  "webhook": {
    "url": "https://your-backend.com/elevenlabs/webhook",
    "headers": {
      "X-Api-Key": "${ELEVENLABS_API_KEY}"
    }
  }
}
```

When exported from the ElevenLabs UI, save the config here for version control.