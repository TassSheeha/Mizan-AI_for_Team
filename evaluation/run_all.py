# -*- coding: utf-8 -*-
"""
run_all.py — Orchestrator for the Mizan AI Testing & Evaluation suite.

Runs all 8 evaluation dimensions with a single shared model load:

  1. Retrieval Evaluation        (Recall@1/3/5, MRR, variation robustness)
  2. Answer Quality Evaluation   (grounding, correctness, completeness, IDK)
  3. Citation Evaluation         (presence, completeness, correctness@1, consistency)
  4. Refusal Evaluation          (out-of-scope, no-answer, ambiguous, greetings)
  5. Voice Evaluation            (WER, dialect, noise, TTS clarity)
  6. End-to-End System Testing   (pipeline, multi-turn, stress)
  7. Data Quality Evaluation     (integrity, duplicates, scalability)
  8. Safety & Compliance         (disclaimer, conflicts, outdated info)

Usage:
    python evaluation/run_all.py                 # full suite
    python evaluation/run_all.py --skip-voice    # skip audio checks (fast)
    python evaluation/run_all.py --module voice  # a single dimension

Environment:
    MIZAN_EVAL_PROVIDER  groq | ollama | fallback  (default: fallback —
                         deterministic, offline-safe generation provider)

Exit code 0 only when every check passes (skips are allowed and reported).
A Markdown report is written to evaluation/report.md.
"""

import argparse
import importlib
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from eval_common import EvalContext, ModuleResult  # noqa: E402

MODULES = [
    ("retrieval", "eval_retrieval", "1. Retrieval Evaluation"),
    ("answer", "eval_answer", "2. Answer Quality Evaluation"),
    ("citations", "eval_citations", "3. Citation Evaluation"),
    ("refusal", "eval_refusal", "4. Refusal Evaluation"),
    ("voice", "eval_voice", "5. Voice Evaluation"),
    ("e2e", "eval_e2e", "6. End-to-End System Testing"),
    ("data", "eval_data", "7. Data Quality Evaluation"),
    ("safety", "eval_safety", "8. Safety & Compliance"),
]


def main():
    parser = argparse.ArgumentParser(description="Mizan AI evaluation suite")
    parser.add_argument("--skip-voice", action="store_true",
                        help="skip dimension 5 (audio checks; slow / needs TTS+STT models)")
    parser.add_argument("--module", choices=[m[0] for m in MODULES],
                        help="run a single evaluation module")
    args = parser.parse_args()

    selected = [m for m in MODULES if m[0] == args.module] if args.module else [
        m for m in MODULES if not (args.skip_voice and m[0] == "voice")
    ]

    print("=" * 74)
    print("⚖️  MIZAN AI — TESTING & EVALUATION SUITE (8 dimensions)")
    print("=" * 74)

    ctx = EvalContext()

    results = []
    for key, mod_name, title in selected:
        print(f"\n{'#' * 74}")
        print(f"# {title}")
        print(f"{'#' * 74}")
        result = ModuleResult(name=title)
        module = importlib.import_module(mod_name)
        t0 = time.time()
        try:
            module.run(ctx, result)
        except Exception:
            result.fail("Module crashed", traceback.format_exc(limit=3).replace("\n", " | "))
        result.duration_s = round(time.time() - t0, 1)
        results.append(result)
        print(f"  → {result.passed} passed, {result.failed} failed, "
              f"{result.skipped} skipped ({result.duration_s}s)")

    # ── Summary ──
    total_pass = sum(r.passed for r in results)
    total_fail = sum(r.failed for r in results)
    total_skip = sum(r.skipped for r in results)

    print(f"\n{'=' * 74}")
    print("SUMMARY")
    print(f"{'=' * 74}")
    for r in results:
        status = "✅" if r.failed == 0 else "❌"
        print(f"  {status} {r.name:38s} pass={r.passed:3d} fail={r.failed:3d} "
              f"skip={r.skipped:2d} ({r.duration_s}s)")
    print(f"\n  TOTAL: {total_pass} passed, {total_fail} failed, {total_skip} skipped")
    verdict = "ALL CHECKS PASSED" if total_fail == 0 else "FAILURES PRESENT — SEE ABOVE"
    print(f"  VERDICT: {verdict}")

    # ── Markdown report ──
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Mizan AI — Evaluation Report\n\n")
        f.write(f"- Provider: `{ctx.provider}`\n")
        f.write(f"- Corpus: {len(ctx.chunks)} chunks (12 Libyan legal documents)\n")
        f.write(f"- Context load time: {ctx.load_seconds}s\n\n")
        f.write("| Dimension | Passed | Failed | Skipped | Duration (s) |\n")
        f.write("|---|---|---|---|---|\n")
        for r in results:
            f.write(f"| {r.name} | {r.passed} | {r.failed} | {r.skipped} | {r.duration_s} |\n")
        f.write(f"\n**Total: {total_pass} passed, {total_fail} failed, {total_skip} skipped.**\n\n")
        f.write("## Details\n\n")
        for r in results:
            f.write(f"### {r.name}\n\n")
            for note in r.notes:
                f.write(f"- {note}\n")
            if not r.notes:
                f.write("- (no informational notes)\n")
            f.write("\n")
    print(f"\n  Report written to: {report_path}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
