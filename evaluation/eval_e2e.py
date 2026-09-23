# -*- coding: utf-8 -*-
"""
eval_e2e.py — Dimension 6: End-to-End System Testing.

  - Full pipeline validation: labeled queries through answer_question must
    return the full result contract (answer/citations/confidence/provider).
  - Multi-turn conversation handling: follow-up questions with pronouns must
    resolve through history reformulation and retrieve the right articles.
  - Stress testing: rapid sequential mixed queries — zero exceptions,
    latency statistics reported, p95 under the SLA.
  - UI/UX: automated boot check is performed by the orchestrator; a manual
    checklist is printed for the human evaluation pass.
"""

import time

from eval_common import GROUND_TRUTH, ModuleResult, hit_rank, normalize_arabic

LATENCY_SLA_P95 = 30.0  # seconds, deterministic fallback provider

MULTI_TURN_SCRIPT = [
    {"query": "ما هي مدة الإجازة السنوية؟", "doc_id": "LAW_12_2010", "articles": ["30"]},
    {"query": "وماذا عن الإجازة المرضية؟", "doc_id": "LAW_12_2010", "articles": ["33"]},
    {"query": "وكم مدة إجازة الحج؟", "doc_id": "LAW_12_2010", "articles": ["34"]},
    {"query": "وهل تنقطع الإجازة أو يؤجلها صاحب العمل؟", "doc_id": "LAW_12_2010", "articles": ["30"]},
]

STRESS_QUERIES = [
    "ما هي مدة الإجازة السنوية؟",
    "من فاز بمباراة أمس؟",
    "شن شروط تأسيس شركة تجارية؟",
    "ما هو الطقس اليوم؟",
    "فصلوني تعسفياً شن حقي؟",
    "ما هي الإعفاءات الضريبية؟",
    "شن القانون؟",
    "ما حكم الربا؟",
    "المادة 34",
    "ما هي افضل مدرسة؟",
    "شن حقوق الطفل في التعليم؟",
    "كم معدل الرواتب في القطاع الخاص؟",
]


def run(ctx, result: ModuleResult):
    # ── 1. Full pipeline validation ──
    contract_bad, latency = [], []
    for g in GROUND_TRUTH:
        t0 = time.time()
        try:
            r = ctx.assistant.answer_question(g["query"], top_k=3)
        except Exception as e:
            contract_bad.append((g["query"], repr(e)))
            continue
        latency.append(time.time() - t0)
        for key in ("answer", "citations", "provider", "confidence", "no_match"):
            if key not in r:
                contract_bad.append((g["query"], f"missing key '{key}'"))
    if not contract_bad:
        result.ok("Full pipeline contract (answer/citations/confidence/provider)",
                  f"{len(GROUND_TRUTH)} queries, no exceptions")
    else:
        result.fail("Full pipeline validation", f"{contract_bad}")

    if latency:
        latency.sort()
        p95 = latency[max(0, int(len(latency) * 0.95) - 1)]
        result.info(f"  Pipeline latency: median={latency[len(latency)//2]:.2f}s p95={p95:.2f}s")

    # ── 2. Multi-turn conversation handling ──
    history = []
    mt_bad = []
    for turn in MULTI_TURN_SCRIPT:
        r = ctx.assistant.answer_question(turn["query"], top_k=3, chat_history=history)
        history.append({"role": "user", "content": turn["query"]})
        history.append({"role": "assistant", "content": r.get("answer", "")})
        if r.get("no_match"):
            mt_bad.append((turn["query"], "refused"))
            continue
        cited = {str(c.get("article")) for c in (r.get("citations") or [])}
        rank_hit = hit_rank(
            [{"doc_id": c.get("doc_id"), "article": str(c.get("article"))} for c in r.get("citations") or []],
            turn["doc_id"], turn["articles"],
        )
        if rank_hit == 0:
            mt_bad.append((turn["query"], f"cited={cited} expected={turn['articles']}"))
    if not mt_bad:
        result.ok("Multi-turn handling: follow-ups resolve to correct articles",
                  f"{len(MULTI_TURN_SCRIPT)} turns")
    else:
        result.fail("Multi-turn conversation handling", f"{mt_bad}")

    # ── 3. Stress testing ──
    errors, times = [], []
    for q in STRESS_QUERIES:
        t0 = time.time()
        try:
            r = ctx.assistant.answer_question(q, top_k=3)
            if not isinstance(r.get("answer"), str) or not r["answer"].strip():
                errors.append((q, "empty answer"))
        except Exception as e:
            errors.append((q, repr(e)))
        times.append(time.time() - t0)
    times.sort()
    p95 = times[max(0, int(len(times) * 0.95) - 1)]
    if not errors:
        result.ok("Stress test: 12 rapid mixed queries, zero exceptions",
                  f"median={times[len(times)//2]:.2f}s p95={p95:.2f}s max={times[-1]:.2f}s")
    else:
        result.fail("Stress testing", f"errors={errors}")

    if p95 > LATENCY_SLA_P95:
        result.fail(f"Stress p95 <= {LATENCY_SLA_P95}s", f"p95={p95:.2f}s")
    else:
        result.ok(f"Stress p95 <= {LATENCY_SLA_P95}s", f"p95={p95:.2f}s")

    # ── 4. UI/UX manual checklist ──
    result.info("UI/UX manual checklist (human pass):")
    result.info("  1. App boots and serves the chat UI (automated: orchestrator boot check)")
    result.info("  2. RTL layout renders correctly with Cairo font")
    result.info("  3. 👍/👎 feedback buttons appear under every assistant reply")
    result.info("  4. Feedback toggles and persists across a page rerun")
    result.info("  5. Citations expand with correct RTL card styling")
    result.info("  6. Voice input shows a spinner, then the transcript as the user bubble")
    result.info("  7. Audio reply icon plays TTS with autoplay after voice questions")
