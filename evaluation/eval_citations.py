# -*- coding: utf-8 -*-
"""
eval_citations.py — Dimension 3: Citation Evaluation.

For every labeled query answered by the pipeline:
  - Citation presence: an answered query must carry citations.
  - Citation completeness: each citation has article/document/page/year/text.
  - Citation correctness@1: the TOP citation matches the expected article/doc.
  - Multi-citation consistency: no duplicated (article, document) pairs;
    for doc-level labels all citations come from the expected document.
"""

from eval_common import GROUND_TRUTH, ModuleResult


def run(ctx, result: ModuleResult):
    presence_bad, completeness_bad, correctness1_bad, consistency_bad = [], [], [], []
    answered = 0

    for g in GROUND_TRUTH:
        r = ctx.assistant.answer_question(g["query"], top_k=3)
        if r.get("no_match"):
            continue
        answered += 1
        citations = r.get("citations") or []

        # 1. Presence
        if not citations:
            presence_bad.append(g["query"])
            continue

        # 2. Completeness of every citation record
        for c in citations:
            missing = [k for k in ("article", "document", "page", "text") if not c.get(k)]
            if missing:
                completeness_bad.append((g["query"], c.get("article"), missing))

        # 3. Correctness@1 — top citation hits the expected article/doc
        top = citations[0]
        if g["articles"] is not None:
            if g["doc_id"] is None:
                ok1 = str(top.get("article")) in g["articles"]
            else:
                ok1 = str(top.get("article")) in g["articles"] and top.get("doc_id") == g["doc_id"]
        else:
            ok1 = top.get("doc_id") == g["doc_id"]
        if not ok1:
            correctness1_bad.append((g["query"], f"top={top.get('article')}@{top.get('doc_id')}"))

        # 4. Multi-citation consistency
        pairs = [(str(c.get("article")), c.get("document")) for c in citations]
        if len(set(pairs)) != len(pairs):
            consistency_bad.append((g["query"], f"duplicate pairs {pairs}"))
        if g["articles"] is None and g["doc_id"] is not None:
            doc_ids = {c.get("doc_id") for c in citations}
            if doc_ids != {g["doc_id"]}:
                consistency_bad.append((g["query"], f"mixed docs {doc_ids}"))

    if answered == 0:
        result.fail("Citation presence", "no labeled query was answered")
        return

    if not presence_bad:
        result.ok("Citation presence: every answered query carries citations",
                  f"{answered}/{len(GROUND_TRUTH)} answered")
    else:
        result.fail("Citation presence", f"{presence_bad}")

    if not completeness_bad:
        result.ok("Citation completeness: article/document/page/text present in all citations")
    else:
        result.fail("Citation completeness", f"{completeness_bad[:6]}")

    c1_ratio = 1 - len(correctness1_bad) / answered
    if not correctness1_bad:
        result.ok("Citation correctness@1: top citation matches ground truth",
                  f"{answered}/{answered}")
    elif c1_ratio >= 0.80:
        result.ok(f"Citation correctness@1 >= 0.80", f"{c1_ratio:.2f} — problems: {correctness1_bad}")
    else:
        result.fail("Citation correctness@1", f"ratio={c1_ratio:.2f} problems={correctness1_bad}")

    if not consistency_bad:
        result.ok("Multi-citation consistency: unique pairs, no off-topic documents")
    else:
        result.fail("Multi-citation consistency", f"{consistency_bad}")
