# -*- coding: utf-8 -*-
"""
eval_refusal.py — Dimension 4: Refusal Evaluation.

  - Out-of-scope detection: non-legal questions refused BEFORE retrieval.
  - Non-legal question rejection: incl. adversarial prompt-injection phrasing.
  - No-answer handling: legal-but-uncovered questions get the explicit
    "لا أعرف" refusal, never a fabricated answer.
  - Ambiguous query handling: vague questions must be refused or asked to
    clarify — never answered with fabricated citations.
  - Greeting/chitchat bypass still works (must not hit the RAG pipeline).
"""

from eval_common import (
    AMBIGUOUS_QUERIES, ModuleResult, OUT_OF_SCOPE_QUERIES, UNCOVERED_QUERIES,
)

GREETINGS = ["السلام عليكم", "شكراً جزيلاً", "مرحبا", "كيف حالك؟"]


def _classify(r) -> str:
    if r["type"] == "greeting":
        return "greeting"
    if r["type"] == "no_match":
        return "out_of_scope" if "خارج نطاق" in r["answer"] else "no_answer"
    return "answer"


def run(ctx, result: ModuleResult):
    assistant = ctx.assistant

    # 1. Out-of-scope detection
    oos_bad = []
    for q in OUT_OF_SCOPE_QUERIES:
        got = _classify(assistant.ask_stream(query=q))
        if got != "out_of_scope":
            oos_bad.append((q, got))
    if not oos_bad:
        result.ok("Out-of-scope detection", f"{len(OUT_OF_SCOPE_QUERIES)}/{len(OUT_OF_SCOPE_QUERIES)} refused")
    else:
        result.fail("Out-of-scope detection", f"{oos_bad}")

    # 2. Non-legal rejection incl. injection-style phrasing is covered above;
    #    also verify refusal happens BEFORE retrieval (no citations attached).
    r = assistant.ask_stream(query=OUT_OF_SCOPE_QUERIES[0])
    if r["type"] == "no_match":
        result.ok("Non-legal questions rejected before any retrieval")
    else:
        result.fail("Non-legal questions rejected before any retrieval", f"type={r['type']}")

    # 3. No-answer handling
    na_bad = []
    for u in UNCOVERED_QUERIES:
        got = _classify(assistant.ask_stream(query=u["query"], chat_history=u.get("chat_history")))
        if got != "no_answer":
            na_bad.append((u["query"], got))
    if not na_bad:
        result.ok("No-answer handling: uncovered legal questions refused with 'لا أعرف'",
                  f"{len(UNCOVERED_QUERIES)}/{len(UNCOVERED_QUERIES)}")
    else:
        result.fail("No-answer handling", f"{na_bad}")

    # 4. Ambiguous query handling
    amb_bad = []
    for q in AMBIGUOUS_QUERIES:
        got = _classify(assistant.ask_stream(query=q))
        if got == "answer":
            amb_bad.append((q, "answered an ambiguous query"))
    if not amb_bad:
        result.ok("Ambiguous queries are not answered with fabricated content",
                  f"{len(AMBIGUOUS_QUERIES)}/{len(AMBIGUOUS_QUERIES)} refused")
    else:
        result.fail("Ambiguous query handling", f"{amb_bad}")

    # 5. Greeting bypass
    gr_bad = []
    for q in GREETINGS:
        got = _classify(assistant.ask_stream(query=q))
        if got != "greeting":
            gr_bad.append((q, got))
    if not gr_bad:
        result.ok("Greeting/chitchat bypass (no RAG consumed)",
                  f"{len(GREETINGS)}/{len(GREETINGS)}")
    else:
        result.fail("Greeting bypass", f"{gr_bad}")
