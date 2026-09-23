# -*- coding: utf-8 -*-
"""
eval_data.py — Dimension 7: Data Quality Evaluation.

  - Data integrity: all_chunks.json matches the ChromaDB index in count and
    ids; metadata completeness (doc_id / article / page / document).
  - Duplicate detection: exact duplicate texts and near-duplicates
    (adjacent-window Jaccard) inside the corpus.
  - Scalability for new legal domains: a synthetic new-domain document
    appended to a temporary chunks file must build an index and be retrievable
    (proves the ingestion path generalizes beyond the 12 shipped laws).
"""

import json
import os
import tempfile
import time

from eval_common import CHUNKS_PATH, ModuleResult, tokenize_arabic, normalize_arabic
from mizan.bm25_search import ArabicBM25Search

NEAR_DUP_JACCARD = 0.92


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def run(ctx, result: ModuleResult):
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = json.load(f)

    # ── 1. Data integrity: chunks file vs ChromaDB ──
    n_json = len(chunks)
    n_chroma = ctx.retriever.collection.count()
    if n_json == n_chroma:
        result.ok("Corpus count matches ChromaDB index", f"{n_chroma} chunks")
    else:
        result.fail("Corpus count matches ChromaDB", f"json={n_json} chroma={n_chroma}")

    chroma = ctx.retriever.collection.get(include=["metadatas"])
    ids_json = {c["chunk_id"] for c in chunks}
    ids_chroma = set(chroma["ids"])
    if ids_json == ids_chroma:
        result.ok("Chunk ids identical between file and index", f"{len(ids_chroma)} ids")
    else:
        only_json = list(ids_json - ids_chroma)[:5]
        only_chroma = list(ids_chroma - ids_json)[:5]
        result.fail("Chunk ids identical", f"only in json={only_json} only in chroma={only_chroma}")

    if len(ids_json) == n_json:
        result.ok("No duplicate chunk ids", f"{n_json} unique ids")
    else:
        result.fail("Duplicate chunk ids present", f"{n_json - len(ids_json)} duplicates")

    metas = chroma["metadatas"]
    total = len(metas)
    coverage = {
        key: sum(1 for m in metas if m.get(key) not in (None, "", 0))
        for key in ("doc_id", "article", "page", "document", "year")
    }
    result.info("Metadata coverage over the live index: " +
                ", ".join(f"{k}={v}/{total}" for k, v in coverage.items()))
    for key in ("doc_id", "document", "page"):
        if coverage[key] == total:
            result.ok(f"Metadata '{key}' complete", f"{coverage[key]}/{total}")
        else:
            result.fail(f"Metadata '{key}' complete", f"{coverage[key]}/{total}")
    for key in ("article", "year"):
        ratio = coverage[key] / total
        if ratio >= 0.99:
            result.ok(f"Metadata '{key}' coverage >= 99%", f"{coverage[key]}/{total}")
        else:
            result.fail(f"Metadata '{key}' coverage >= 99%", f"{coverage[key]}/{total}")

    # ── 2. Duplicate detection ──
    seen_hashes = {}
    exact_dups = 0
    for c in chunks:
        h = hash(normalize_arabic(c["text_with_context"]))
        if h in seen_hashes:
            exact_dups += 1
        seen_hashes[h] = c["chunk_id"]
    if exact_dups == 0:
        result.ok("No exact duplicate texts in corpus", f"{n_json} chunks scanned")
    else:
        result.fail("Exact duplicate texts found", f"{exact_dups}")

    near_dups = []
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c.get("doc_id"), []).append(c)
    for doc_id, group in by_doc.items():
        group.sort(key=lambda c: (int(c.get("page") or 0), str(c.get("article"))))
        token_sets = [set(tokenize_arabic(c["text_with_context"])) for c in group]
        for i in range(len(group) - 1):
            if _jaccard(token_sets[i], token_sets[i + 1]) > NEAR_DUP_JACCARD:
                near_dups.append((doc_id, group[i]["chunk_id"], group[i + 1]["chunk_id"]))
    if not near_dups:
        result.ok(f"No near-duplicate chunks (Jaccard > {NEAR_DUP_JACCARD}) within documents")
    else:
        result.fail("Near-duplicate chunks found", f"{near_dups[:6]}")

    # ── 3. Scalability: new legal domain ingestion ──
    synthetic = [
        {
            "chunk_id": f"SYN_{i:03d}",
            "article": str(i + 1),
            "page": i + 1,
            "section": "الباب الأول",
            "chapter": "الفصل الأول",
            "document": "قانون الاستثمار الجديد",
            "doc_id": "SYNTHETIC_INVESTMENT_LAW",
            "doc_type": "law",
            "year": 2026,
            "text_with_context": (
                "قانون الاستثمار الجديد الباب الأول الفصل الأول "
                f"المادة {i + 1}: مادة ({i + 1}) تمنح الحوافز الضريبية للمشاريع الاستثمارية "
                "المسجلة لدى المركز الليبي للاستثمار وتعفى من الرسوم الجمركية على المعدات."
            ),
        }
        for i in range(300)
    ]
    tmp = os.path.join(tempfile.gettempdir(), "mizan_eval_synth_chunks.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(chunks + synthetic, f, ensure_ascii=False)

    t0 = time.time()
    try:
        synth = ArabicBM25Search(chunks_path=tmp)
        build_s = time.time() - t0
        hits = synth.search("حوافز ضريبية للمشاريع الاستثمارية", top_k=3)
        if build_s < 60 and hits and all(
            h.get("doc_id") == "SYNTHETIC_INVESTMENT_LAW" for h in hits
        ):
            result.ok("Scalability: new legal domain indexed and retrieved",
                      f"3229 chunks rebuilt in {build_s:.1f}s, top-3 all from new domain")
        else:
            result.fail("Scalability for new legal domains",
                        f"build={build_s:.1f}s hits={[(h['doc_id'], h['article']) for h in hits]}")
    except Exception as e:
        result.fail("Scalability for new legal domains", repr(e))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
