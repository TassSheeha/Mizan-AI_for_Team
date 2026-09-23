"""
bm25_search.py — Sparse Keyword Search engine using BM25 with Arabic normalization.

Provides ArabicBM25Search:
  - Normalizes Arabic letters (alef variants, taa marbuta, alif maqsura, tatweel).
  - Builds BM25Okapi inverted index over all legal chunks.
  - Returns ranked results with BM25 scores for keyword queries.
"""

import os
import re
import json
from rank_bm25 import BM25Okapi

from config import CHUNKS_DIR

# Arabic normalization maps
ALEF_PATTERN = re.compile(r"[إأآٱ]")
DIACRITICS_PATTERN = re.compile(r"[\u064B-\u0653\u0670]")
# Strip everything that is not a word character or whitespace. \w covers
# Arabic letters AND digits (any script); this also removes Arabic punctuation
# (؟ ، ؛) which sits inside the Arabic Unicode block — previously it survived
# and glued itself to words ('السنويه؟'), silently breaking all matching.
PUNCTUATION_PATTERN = re.compile(r"[^\w\s]")

# Attached prefixes stripped iteratively from token starts (query and corpus
# undergo the SAME transformation, so matching stays consistent even when a
# stripped form is not linguistically perfect).
_TOKEN_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")


def _strip_token_prefixes(t: str) -> str:
    while len(t) > 4:
        for p in _TOKEN_PREFIXES:
            if t.startswith(p) and len(t) - len(p) >= 3:
                t = t[len(p):]
                break
        else:
            return t
    return t


def tokenize_arabic(text: str) -> list[str]:
    """
    Normalizes and tokenizes Arabic legal text for BM25 keyword matching.
    """
    # 1. Strip diacritics
    text = DIACRITICS_PATTERN.sub("", text)
    # 2. Normalize alef variants to bare alef
    text = ALEF_PATTERN.sub("ا", text)
    # 3. Normalize taa marbuta to haa
    text = text.replace("ة", "ه")
    # 4. Normalize alif maqsura to yaa
    text = text.replace("ى", "ي")
    # 5. Remove tatweel
    text = text.replace("ـ", "")
    # 6. Replace punctuation with space
    text = PUNCTUATION_PATTERN.sub(" ", text)

    # 7. Tokenize, strip attached prefixes (ال/وال/بال/...) and drop
    #    single characters
    tokens = []
    for t in text.lower().split():
        t = _strip_token_prefixes(t)
        if len(t) > 1:
            tokens.append(t)
    return tokens


def expand_with_bigrams(tokens: list[str]) -> list[str]:
    """
    Append adjacent-token bigrams (marked with '~') to a unigram token list.

    Pure unigram BM25 rewards documents that repeat a single query word many
    times, which can outrank the document containing the exact legal phrase
    (e.g. 'الإجازة السنوية' losing to a sick-leave article that repeats
    'إجازة'). Bigrams carry precise-phrase matches with high IDF so exact
    legal terms ('اجازه~سنويه', 'غسل~اموال', 'اوراق~ماليه') dominate ranking.
    """
    if len(tokens) < 2:
        return tokens
    return tokens + [f"{a}~{b}" for a, b in zip(tokens, tokens[1:])]


class ArabicBM25Search:
    def __init__(self, chunks_path: str = None):
        if chunks_path is None:
            chunks_path = os.path.join(CHUNKS_DIR, "all_chunks.json")

        if not os.path.exists(chunks_path):
            raise FileNotFoundError(f"Chunks file not found at: {chunks_path}")

        with open(chunks_path, "r", encoding="utf-8") as f:
            self.chunks = json.load(f)

        # Tokenize corpus for BM25 (unigrams + phrase bigrams)
        print(f"Building BM25 index over {len(self.chunks)} legal chunks...")
        self.corpus_tokens = [
            expand_with_bigrams(tokenize_arabic(c["text_with_context"]))
            for c in self.chunks
        ]
        self.bm25 = BM25Okapi(self.corpus_tokens)
        print("✓ BM25 index built successfully.")

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search corpus using BM25 algorithm.
        Returns top-k results sorted by BM25 score.
        """
        query_tokens = expand_with_bigrams(tokenize_arabic(query))
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= 0:
                continue
            c = self.chunks[idx]
            results.append({
                "chunk_id": c["chunk_id"],
                "article": c.get("article"),
                "page": c.get("page"),
                "section": c.get("section"),
                "chapter": c.get("chapter"),
                "document": c.get("document"),
                "doc_id": c.get("doc_id"),
                "doc_type": c.get("doc_type"),
                "year": c.get("year"),
                "bm25_score": round(score, 4),
                "text": c["text_with_context"],
            })

        return results
