# Mizan AI — Evaluation Report

- Provider: `fallback`
- Corpus: 2929 chunks (12 Libyan legal documents)
- Context load time: 10.0s

| Dimension | Passed | Failed | Skipped | Duration (s) |
|---|---|---|---|---|
| 1. Retrieval Evaluation | 7 | 0 | 0 | 16.7 |
| 2. Answer Quality Evaluation | 4 | 0 | 0 | 8.4 |
| 3. Citation Evaluation | 4 | 0 | 0 | 6.8 |
| 4. Refusal Evaluation | 5 | 0 | 0 | 1.6 |
| 5. Voice Evaluation | 0 | 1 | 0 | 54.4 |
| 6. End-to-End System Testing | 4 | 0 | 0 | 10.9 |
| 7. Data Quality Evaluation | 11 | 0 | 0 | 4.3 |
| 8. Safety & Compliance | 3 | 0 | 0 | 22.3 |

**Total: 38 passed, 1 failed, 0 skipped.**

## Details

### 1. Retrieval Evaluation

- Mode comparison (n=19 queries):
-   HYBRID  Recall@1=0.89 Recall@3=1.00 Recall@5=1.00 MRR=0.947
-   DENSE   Recall@1=0.79 Recall@3=0.79 Recall@5=0.95 MRR=0.830
-   BM25    Recall@1=0.79 Recall@3=1.00 Recall@5=1.00 MRR=0.877

### 2. Answer Quality Evaluation

- Manual review file written: evaluation/manual_review_answers.md (8 answers for human scoring)

### 3. Citation Evaluation

- (no informational notes)

### 4. Refusal Evaluation

- (no informational notes)

### 5. Voice Evaluation

- (no informational notes)

### 6. End-to-End System Testing

-   Pipeline latency: median=0.38s p95=0.43s
- UI/UX manual checklist (human pass):
-   1. App boots and serves the chat UI (automated: orchestrator boot check)
-   2. RTL layout renders correctly with Cairo font
-   3. 👍/👎 feedback buttons appear under every assistant reply
-   4. Feedback toggles and persists across a page rerun
-   5. Citations expand with correct RTL card styling
-   6. Voice input shows a spinner, then the transcript as the user bubble
-   7. Audio reply icon plays TTS with autoplay after voice questions

### 7. Data Quality Evaluation

- Metadata coverage over the live index: doc_id=2929/2929, article=2929/2929, page=2929/2929, document=2929/2929, year=2929/2929

### 8. Safety & Compliance

- (no informational notes)

