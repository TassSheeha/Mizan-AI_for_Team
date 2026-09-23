# -*- coding: utf-8 -*-
"""
eval_answer.py — Dimension 2: Answer Quality Evaluation.

Checks over the full RAG pipeline (retrieval gate -> generation):
  - Grounded answer verification: every 'المادة (N)' reference in the answer
    must exist among the retrieved citations (anti-hallucination).
  - Answer correctness (automated part): the expected article must be cited
    or referenced for labeled queries.
  - Completeness: expected keywords for the intent appear in answer/citations.
  - "I don't know" handling: uncovered legal queries must produce the explicit
    no-answer refusal (never a fabricated answer).
  - Answer correctness (manual part): full answers for a curated subset are
    written to evaluation/manual_review_answers.md for human scoring.
"""

import os

from eval_common import (
    GROUND_TRUTH, ModuleResult, extract_article_refs, normalize_arabic,
)

# Queries whose full answers are exported for manual human scoring
MANUAL_REVIEW_TAGS = ["annual_leave", "sick_leave", "special_leave", "company_formation"]


def _answer_and_citations(ctx, query, chat_history=None):
    r = ctx.assistant.answer_question(query, top_k=3, chat_history=chat_history)
    return r


def run(ctx, result: ModuleResult):
    reviewed = []
    grounded_bad = []
    correct_bad = []
    completeness_bad = []

    for g in GROUND_TRUTH:
        r = _answer_and_citations(ctx, g["query"])
        citations = r.get("citations") or []
        answer = r.get("answer") or ""

        if r.get("no_match"):
            correct_bad.append((g["query"], "refused instead of answered"))
            continue

        # 1. Grounding: article refs in the answer must exist in citations
        cited_articles = {str(c.get("article")) for c in citations if c.get("article")}
        refs = extract_article_refs(answer)
        hallucinated = {ref for ref in refs if ref not in cited_articles}
        if hallucinated:
            grounded_bad.append((g["query"], sorted(hallucinated)))

        # 2. Correctness (automated): expected article cited or referenced.
        # doc_id=None labels are ambiguous questions — any law's article counts.
        if g["articles"] is not None:
            hit = cited_articles & set(g["articles"])
        else:
            hit = {c.get("doc_id") for c in citations} & {g["doc_id"]} if g["doc_id"] else cited_articles
        if not hit:
            correct_bad.append((g["query"], f"cited={cited_articles} expected={g['articles']}"))

        # 3. Completeness: expected keywords in answer or cited texts
        if g["keywords"]:
            corpus = normalize_arabic(answer) + " " + " ".join(
                normalize_arabic(c.get("text") or "") for c in citations
            )
            missing = [kw for kw in g["keywords"] if normalize_arabic(kw) not in corpus]
            if missing:
                completeness_bad.append((g["query"], missing))

        if g["tag"] in MANUAL_REVIEW_TAGS:
            reviewed.append((g["query"], g["tag"], answer, citations))

    # 1. Grounded answer verification
    if not grounded_bad:
        result.ok("All answers are grounded (article refs ⊆ citations)")
    else:
        result.fail("Grounded answer verification",
                    f"{len(grounded_bad)} answers reference un-cited articles: {grounded_bad}")

    # 2. Answer correctness (automated)
    answered = len(GROUND_TRUTH) - sum(1 for _, why in correct_bad if why.startswith("refused"))
    accuracy = 1 - len([b for b in correct_bad if not b[1].startswith("refused")]) / max(len(GROUND_TRUTH), 1)
    if not correct_bad:
        result.ok("Answer correctness (automated): expected article cited for all labeled queries",
                  f"{answered}/{len(GROUND_TRUTH)}")
    else:
        result.fail("Answer correctness (automated)",
                    f"accuracy={accuracy:.2f} problems={correct_bad}")

    # 3. Completeness assessment
    if not completeness_bad:
        result.ok("Completeness: expected keywords present in answer/citations")
    else:
        result.fail("Completeness assessment", f"missing keywords: {completeness_bad}")

    # 4. "I don't know" handling
    from eval_common import UNCOVERED_QUERIES
    idk_bad = []
    for u in UNCOVERED_QUERIES:
        r = _answer_and_citations(ctx, u["query"], u.get("chat_history"))
        answer = r.get("answer") or ""
        if not r.get("no_match"):
            idk_bad.append((u["query"], "answered instead of refusing"))
        elif "لا أعرف" not in answer:
            idk_bad.append((u["query"], "refusal lacks explicit 'لا أعرف' statement"))
    if not idk_bad:
        result.ok("'I don't know' handling: uncovered legal queries refused explicitly",
                  f"{len(UNCOVERED_QUERIES)} queries")
    else:
        result.fail("'I don't know' handling", f"{idk_bad}")

    # 5. Manual review export (documented human evaluation)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "manual_review_answers.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Manual Answer-Quality Review (Mizan AI)\n\n")
        f.write(f"Provider: `{ctx.provider}` (automated suite default: deterministic fallback)\n\n")
        f.write("Rate each answer 1-5 on: correctness, completeness, clarity, grounding.\n\n")
        for q, tag, answer, citations in reviewed:
            f.write(f"## [{tag}] {q}\n\n")
            f.write(f"**Answer:**\n\n{answer}\n\n")
            f.write("**Citations:** " + "; ".join(
                f"مادة {c.get('article')} — {c.get('document')} (ص{c.get('page')})"
                for c in citations) + "\n\n---\n\n")
    result.info(f"Manual review file written: evaluation/manual_review_answers.md "
                f"({len(reviewed)} answers for human scoring)")
