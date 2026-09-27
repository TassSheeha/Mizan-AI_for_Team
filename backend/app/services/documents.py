"""
app.services.documents — Knowledge-base management (admin).

Manages the legal-document registry stored in `legal_documents` (DB) and keeps
the two existing indexes in sync WITHOUT touching the mizan package:

  - Dense index : data/chroma_db (ChromaDB collection)
  - Sparse index: data/chunks/all_chunks.json (BM25 corpus)

Supported operations:
  - ingest_chunks_file : register a ready chunks JSON (same schema as
    data/chunks/*.json produced by the existing pipeline) and index it
  - ingest_pdf         : extract a text-layer PDF with PyMuPDF, split it into
    article chunks using the same schema, then index it
  - delete_document    : remove all chunks of a doc from both indexes
  - rebuild_document   : re-index a doc from its stored chunks file

After every index mutation the AI layer is reloaded so the change is live.
"""

import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from app.core.config import PROJECT_ROOT

logger = logging.getLogger("mizan.docs")

DATA_DIR = PROJECT_ROOT / "data"
CHUNKS_DIR = DATA_DIR / "chunks"
CHROMA_DIR = DATA_DIR / "chroma_db"
RAW_DIR = DATA_DIR / "raw"
UPLOADS_DIR = PROJECT_ROOT / "backend" / "uploads"
COLLECTION_NAME = "libyan_labor_law"

CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_ARTICLE_RE = re.compile(r"^\s*المادة\s*(?:\(?([\d\u0660-\u0669]+|[أ-ي]+)\)?)?")

# ─── Embedder (module-level singleton, same ONNX model as the pipeline) ───────
_embedder = None
_embedder_lock = None


def _get_embedder():
    global _embedder, _embedder_lock
    import threading

    if _embedder is None:
        with threading.Lock():
            if _embedder is not None:
                return _embedder
            from tokenizers import Tokenizer
            from huggingface_hub import hf_hub_download
            import onnxruntime as ort

            repo = "Xenova/multilingual-e5-small"
            model_path = hf_hub_download(repo_id=repo, filename="onnx/model_quantized.onnx")
            tok_path = hf_hub_download(repo_id=repo, filename="tokenizer.json")
            tokenizer = Tokenizer.from_file(tok_path)
            tokenizer.enable_truncation(max_length=512)
            tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=512)
            session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            input_names = [i.name for i in session.get_inputs()]
            _embedder = (tokenizer, session, input_names)
    return _embedder


def _encode_passages(texts: list[str]) -> np.ndarray:
    tokenizer, session, input_names = _get_embedder()
    prefixed = [f"passage: {t}" for t in texts]
    encoded = [tokenizer.encode(t) for t in prefixed]
    input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    onnx_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in input_names:
        onnx_inputs["token_type_ids"] = np.zeros_like(input_ids)
    outputs = session.run(None, onnx_inputs)
    last_hidden = outputs[0]
    mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
    embeddings = (last_hidden * mask_expanded).sum(axis=1) / np.clip(
        mask_expanded.sum(axis=1), a_min=1e-9, a_max=None
    )
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return (embeddings / np.clip(norms, a_min=1e-9, a_max=None)).astype(np.float32)


# ─── Chunk-file helpers ───────────────────────────────────────────────────────
def _all_chunks_path() -> Path:
    return CHUNKS_DIR / "all_chunks.json"


def _load_all_chunks() -> list[dict]:
    with open(_all_chunks_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _save_all_chunks(chunks: list[dict]) -> None:
    tmp = _all_chunks_path().with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _all_chunks_path())


def _collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_collection(COLLECTION_NAME)


# ─── PDF → chunks (text-layer PDFs) ──────────────────────────────────────────
def pdf_to_chunks(pdf_path: Path, meta: dict) -> list[dict]:
    """
    Extract a text-layer Arabic legal PDF into chunks using the SAME schema as
    the existing pipeline. Articles are split on 'المادة' headers; page numbers
    are tracked per page. Scanned PDFs (no text layer) raise ValueError.
    """
    import fitz  # pymupdf

    doc = fitz.open(str(pdf_path))
    pages: list[tuple[int, str]] = []
    total_chars = 0
    for pno in range(len(doc)):
        text = doc[pno].get_text("text")
        pages.append((pno + 1, text))
        total_chars += len(text.strip())
    doc.close()

    if total_chars < 200:
        raise ValueError(
            "الملف الممسوح ضوئياً لا يحتوي طبقة نصية. استخدم خط المعالجة المحلي "
            "(scripts/run_pipeline.py مع OCR) لإعداد ملف chunks ثم ارفعه بصيغة JSON."
        )

    doc_title = meta["title"]
    doc_id = meta["doc_id"]
    chunks: list[dict] = []

    # Build a flat list of (page, line) then group into articles.
    article_blocks: list[dict] = []
    current: dict | None = None
    for page_no, text in pages:
        for line in text.splitlines():
            m = _ARTICLE_RE.match(line)
            if m:
                if current and current["lines"]:
                    article_blocks.append(current)
                current = {
                    "article": m.group(1) or "نص",
                    "page": page_no,
                    "lines": [],
                }
            if current is not None:
                current["lines"].append(line)
    if current and current["lines"]:
        article_blocks.append(current)

    # Fallback: no explicit article headers → chunk by fixed-size windows.
    if not article_blocks:
        window = 1200
        for page_no, text in pages:
            clean = text.strip()
            for i in range(0, len(clean), window):
                piece = clean[i:i + window]
                if len(piece.strip()) < 50:
                    continue
                article_blocks.append({
                    "article": "مقطع",
                    "page": page_no,
                    "lines": piece.splitlines(),
                })

    for idx, block in enumerate(article_blocks, 1):
        body = "\n".join(block["lines"]).strip()
        if len(body) < 30:
            continue
        context = f"{doc_title}\nالمادة {block['article']}:"
        chunk = {
            "chunk_id": f"{doc_id}_{uuid.uuid4().hex[:8]}",
            "document": doc_title,
            "doc_id": doc_id,
            "doc_type": meta.get("doc_type", "law"),
            "year": meta.get("year", 0),
            "section": "",
            "chapter": None,
            "article": block["article"],
            "page": block["page"],
            "text": body,
            "context": context,
            "text_with_context": f"{context}\n\n{body}",
            "source": pdf_path.name,
            "char_count": len(body),
        }
        chunks.append(chunk)

    if not chunks:
        raise ValueError("لم يتم استخراج أي مواد قانونية من الملف.")
    return chunks


# ─── Indexing primitives ──────────────────────────────────────────────────────
def index_chunks(new_chunks: list[dict]) -> int:
    """Append chunks to BM25 corpus + embed into ChromaDB. Returns count added."""
    all_chunks = _load_all_chunks()
    existing_ids = {c["chunk_id"] for c in all_chunks}
    to_add = [c for c in new_chunks if c["chunk_id"] not in existing_ids]
    if not to_add:
        return 0

    all_chunks.extend(to_add)
    _save_all_chunks(all_chunks)

    collection = _collection()
    batch = 32
    for i in range(0, len(to_add), batch):
        part = to_add[i:i + batch]
        embeddings = _encode_passages([c["text_with_context"] for c in part])
        collection.add(
            ids=[c["chunk_id"] for c in part],
            embeddings=embeddings.tolist(),
            documents=[c["text_with_context"] for c in part],
            metadatas=[{
                "chunk_id": str(c["chunk_id"]),
                "article": str(c.get("article") or ""),
                "page": int(c.get("page") or 0),
                "section": str(c.get("section") or ""),
                "chapter": str(c.get("chapter") or ""),
                "document": str(c.get("document") or ""),
                "doc_id": str(c.get("doc_id") or ""),
                "source": str(c.get("source") or ""),
                "year": int(c.get("year") or 0),
                "doc_type": str(c.get("doc_type") or "law"),
            } for c in part],
        )
    return len(to_add)


def remove_document_from_index(doc_id: str) -> int:
    """Remove every chunk belonging to doc_id from ChromaDB and BM25 corpus."""
    removed = 0
    try:
        collection = _collection()
        result = collection.get(where={"doc_id": doc_id})
        ids = result.get("ids") or []
        if ids:
            collection.delete(ids=ids)
            removed = len(ids)
    except Exception:
        logger.exception("ChromaDB removal failed for doc %s", doc_id)
        raise

    all_chunks = _load_all_chunks()
    kept = [c for c in all_chunks if c.get("doc_id") != doc_id]
    if len(kept) != len(all_chunks):
        _save_all_chunks(kept)
    return removed


# ─── High-level operations (used by admin routes) ────────────────────────────
def _normalize_chunks_payload(raw: object, meta: dict) -> list[dict]:
    """Validate + normalize an uploaded chunks JSON payload.

    Accepts a plain list of chunk dicts, or a dict wrapping the list under
    one of the common keys (chunks/data/items). Every returned chunk is
    guaranteed to carry: chunk_id (unique), document, doc_id, doc_type,
    year, article, page, section, chapter, text, context,
    text_with_context, source, char_count.
    """
    data = raw
    if isinstance(data, dict):
        for key in ("chunks", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ValueError(
                "ملف JSON غير صالح: يجب أن يحتوي على قائمة مقاطع "
                "(list) أو كائن يحمل القائمة تحت مفتاح chunks."
            )
    if not isinstance(data, list):
        raise ValueError("ملف JSON غير صالح: البنية المتوقعة هي قائمة (list) من المقاطع.")
    if not data:
        raise ValueError("ملف المقاطع فارغ: لا توجد مقاطع للفهرسة.")

    doc_id = str(meta["doc_id"])
    title = str(meta.get("title") or doc_id)
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"المقطع رقم {i + 1} غير صالح: يجب أن يكون كائناً.")
        chunk = dict(item)
        text = str(chunk.get("text") or "").strip()
        if len(text) < 10:
            # Skip degenerate entries instead of failing the whole file.
            continue
        chunk["doc_id"] = doc_id
        chunk["document"] = str(chunk.get("document") or title)
        chunk["doc_type"] = str(chunk.get("doc_type") or meta.get("doc_type", "law"))
        try:
            chunk["year"] = int(chunk.get("year") if chunk.get("year") not in (None, "") else meta.get("year", 0))
        except (TypeError, ValueError):
            chunk["year"] = int(meta.get("year", 0) or 0)
        chunk["article"] = str(chunk.get("article") or "مقطع")
        try:
            chunk["page"] = int(chunk.get("page") or 0)
        except (TypeError, ValueError):
            chunk["page"] = 0
        chunk["section"] = str(chunk.get("section") or "")
        chapter = chunk.get("chapter")
        chunk["chapter"] = None if chapter in (None, "") else str(chapter)
        chunk["context"] = str(chunk.get("context") or f"{chunk['document']}\nالمادة {chunk['article']}:")
        chunk["text"] = text
        chunk["text_with_context"] = str(
            chunk.get("text_with_context") or f"{chunk['context']}\n\n{text}"
        )
        chunk["source"] = str(chunk.get("source") or "")
        chunk["char_count"] = int(chunk.get("char_count") or len(text))

        cid = str(chunk.get("chunk_id") or "").strip()
        if not cid or cid in seen_ids:
            cid = f"{doc_id}_{uuid.uuid4().hex[:8]}"
        chunk["chunk_id"] = cid
        seen_ids.add(cid)
        normalized.append(chunk)

    if not normalized:
        raise ValueError("لم يتم العثور على أي مقطع صالح للفهرسة في الملف.")
    return normalized


def ingest_chunks_file(chunks_path: Path, meta: dict) -> int:
    raw = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunks = _normalize_chunks_payload(raw, meta)

    # Avoid silent no-ops when uploaded chunk_ids collide with the live index
    # (e.g. re-uploading a copy of another document's chunks file): regenerate
    # any id that already exists so the new document is actually indexed.
    try:
        existing_ids = {c["chunk_id"] for c in _load_all_chunks()}
    except Exception:
        existing_ids = set()
    for chunk in chunks:
        if chunk["chunk_id"] in existing_ids:
            chunk["chunk_id"] = f"{meta['doc_id']}_{uuid.uuid4().hex[:8]}"
            # Rebuild derived text fields that embed nothing id-dependent;
            # chunk_id itself is the only changed field, so nothing else to fix.
        existing_ids.add(chunk["chunk_id"])

    count = index_chunks(chunks)

    # Persist a normalized copy under CHUNKS_DIR so future reindex operations
    # never depend on the original upload file surviving in UPLOADS_DIR.
    try:
        canonical = CHUNKS_DIR / f"{meta['doc_id']}_chunks.json"
        with open(canonical, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to persist canonical chunks for %s", meta.get("doc_id"))

    return count


def ingest_pdf(pdf_path: Path, meta: dict) -> int:
    chunks = pdf_to_chunks(pdf_path, meta)
    doc_chunks_file = CHUNKS_DIR / f"{meta['doc_id']}_chunks.json"
    with open(doc_chunks_file, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    meta = dict(meta)
    meta["chunks_file"] = doc_chunks_file.name
    return index_chunks(chunks)


def full_rebuild_status() -> dict:
    try:
        collection = _collection()
        return {"indexed_chunks": collection.count()}
    except Exception as exc:
        return {"indexed_chunks": -1, "error": str(exc)}


def backup_paths() -> list[Path]:
    return [_all_chunks_path(), CHROMA_DIR, PROJECT_ROOT / "backend" / "mizan.db"]
