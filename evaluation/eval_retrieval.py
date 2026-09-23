# -*- coding: utf-8 -*-
"""
eval_retrieval.py — Dimension 1: Retrieval Evaluation.

Measures, per search mode (hybrid / dense / bm25):
  - Recall@1, Recall@3, Recall@5  (expected article present in top-n)
  - MRR (Mean Reciprocal Rank)
  - Query-variation robustness: dialect vs MSA phrasings of the same intent
    must both succeed (Libyan-dialect expansion check).

Ground truth labels are verified against the corpus before scoring.
"""

from eval_common import (
    GROUND_TRUTH, ModuleResult, hit_rank, query_topk, verify_ground_truth,
)

TOPK = 10


def run(ctx, result: ModuleResult):
    problems = verify_ground_truth()
    if problems:
        for q in problems:
            result.fail(f"Ground truth exists in corpus for: {q}")
        return
    result.ok("All ground-truth labels verified in corpus",
              f"{len(GROUND_TRUTH)} labeled queries")

    per_mode = {}
    for mode in ("hybrid", "dense", "bm25"):
        r1 = r3 = r5 = 0
        rr_sum = 0.0
        misses = []
        for g in GROUND_TRUTH:
            res = query_topk(ctx, g["query"], top_k=TOPK, mode=mode)
            rank = hit_rank(res, g["doc_id"], g["articles"])
            rr_sum += 1.0 / rank if rank else 0.0
            r1 += rank == 1
            r3 += 1 <= rank <= 3
            r5 += 1 <= rank <= 5
            if rank == 0:
                misses.append(g["query"])
        n = len(GROUND_TRUTH)
        per_mode[mode] = {
            "recall@1": r1 / n, "recall@3": r3 / n, "recall@5": r5 / n,
            "mrr": rr_sum / n, "misses": misses,
        }

    result.info("Mode comparison (n=%d queries):" % len(GROUND_TRUTH))
    for mode, m in per_mode.items():
        result.info(
            f"  {mode.upper():7s} Recall@1={m['recall@1']:.2f} "
            f"Recall@3={m['recall@3']:.2f} Recall@5={m['recall@5']:.2f} "
            f"MRR={m['mrr']:.3f}"
        )
        if m["misses"]:
            result.info(f"    misses (outside top-{TOPK}): {m['misses']}")

    # ── Gates on the production mode (hybrid) ──
    h = per_mode["hybrid"]
    if h["recall@1"] >= 0.70:
        result.ok("Hybrid Recall@1 >= 0.70", f"got {h['recall@1']:.2f}")
    else:
        result.fail("Hybrid Recall@1 >= 0.70", f"got {h['recall@1']:.2f}")

    if h["recall@3"] >= 0.85:
        result.ok("Hybrid Recall@3 >= 0.85", f"got {h['recall@3']:.2f}")
    else:
        result.fail("Hybrid Recall@3 >= 0.85", f"got {h['recall@3']:.2f}")

    if h["recall@5"] >= 0.90:
        result.ok("Hybrid Recall@5 >= 0.90", f"got {h['recall@5']:.2f}")
    else:
        result.fail("Hybrid Recall@5 >= 0.90", f"got {h['recall@5']:.2f}")

    if h["mrr"] >= 0.75:
        result.ok("Hybrid MRR >= 0.75", f"got {h['mrr']:.3f}")
    else:
        result.fail("Hybrid MRR >= 0.75", f"got {h['mrr']:.3f}")

    # Hybrid must not be worse than the best single engine on Recall@3
    best_single = max(per_mode["dense"]["recall@3"], per_mode["bm25"]["recall@3"])
    if h["recall@3"] >= best_single - 0.01:
        result.ok("Hybrid >= best single engine on Recall@3",
                  f"hybrid {h['recall@3']:.2f} vs best single {best_single:.2f}")
    else:
        result.fail("Hybrid >= best single engine on Recall@3",
                    f"hybrid {h['recall@3']:.2f} vs best single {best_single:.2f}")

    # ── Query variation robustness ──
    # Same intent phrased in MSA and Libyan dialect should both hit top-5.
    tags = {}
    for g in GROUND_TRUTH:
        tags.setdefault(g["tag"], []).append(g)
    robust_ok = robust_total = 0
    for tag, variants in tags.items():
        if len(variants) < 2:
            continue
        robust_total += 1
        hits = []
        for v in variants:
            res = query_topk(ctx, v["query"], top_k=5, mode="hybrid")
            hits.append(hit_rank(res, v["doc_id"], v["articles"]) > 0)
        if all(hits):
            robust_ok += 1
        else:
            result.info(f"  Robustness miss in intent '{tag}': {variants[0]['tag']} hits={hits}")
    if robust_total:
        ratio = robust_ok / robust_total
        if ratio >= 0.80:
            result.ok("Query variation robustness >= 0.80",
                      f"{robust_ok}/{robust_total} intents survive all variants")
        else:
            result.fail("Query variation robustness >= 0.80",
                        f"{robust_ok}/{robust_total} intents survive all variants")
