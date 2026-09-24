r"""Voice evaluation for Mizan AI.

Dataset layout:
  evaluation/voice_data/clean/*.wav       + matching .txt references
  evaluation/voice_data/dialect/*.wav     + matching .txt references
  evaluation/voice_data/noisy/*.wav       + matching .txt references

Run on Windows:
  .venv\Scripts\python.exe evaluation\voice_evaluation.py \
      --audio-dir evaluation\voice_data --output evaluation\voice_report.json

TTS-only smoke test:
  .venv\Scripts\python.exe evaluation\voice_evaluation.py \
      --tts-text "ما هي حقوق العامل وفق القانون الليبي؟"
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
PUNCTUATION = re.compile(r"[؟?!.,،؛:;()\[\]{}\"'`*_/#\\|<>—–-]")


def normalize_arabic(text: str) -> list[str]:
    text = text or ""
    text = ARABIC_DIACRITICS.sub("", text)
    text = text.replace("إ", "ا").replace("أ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = PUNCTUATION.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.split() if text else []


def edit_distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int, int]:
    # Returns substitutions, deletions, insertions, total errors.
    rows = len(ref) + 1
    cols = len(hyp) + 1
    dp = [[0] * cols for _ in range(rows)]
    back = [[None] * cols for _ in range(rows)]
    for i in range(1, rows):
        dp[i][0] = i
        back[i][0] = "D"
    for j in range(1, cols):
        dp[0][j] = j
        back[0][j] = "I"
    for i in range(1, rows):
        for j in range(1, cols):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                back[i][j] = "C"
            else:
                choices = [
                    (dp[i - 1][j - 1] + 1, "S"),
                    (dp[i - 1][j] + 1, "D"),
                    (dp[i][j - 1] + 1, "I"),
                ]
                dp[i][j], back[i][j] = min(choices, key=lambda x: x[0])
    i, j = len(ref), len(hyp)
    s = d = ins = 0
    while i or j:
        op = back[i][j]
        if op == "S":
            s += 1; i -= 1; j -= 1
        elif op == "D":
            d += 1; i -= 1
        elif op == "I":
            ins += 1; j -= 1
        else:
            i -= 1; j -= 1
    return s, d, ins, dp[-1][-1]


def transcribe(path: Path) -> str:
    # Import lazily so TTS-only and empty-dataset checks do not load Whisper.
    from mizan.stt import transcribe_audio
    return transcribe_audio(str(path)) or ""


def evaluate_split(split_dir: Path) -> dict:
    audio_files = sorted(p for p in split_dir.glob("*") if p.suffix.lower() in {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"})
    rows = []
    total_s = total_d = total_i = total_err = total_words = 0
    for audio in audio_files:
        ref_path = audio.with_suffix(".txt")
        if not ref_path.exists():
            rows.append({"file": audio.name, "status": "missing_reference"})
            continue
        reference = ref_path.read_text(encoding="utf-8").strip()
        started = time.perf_counter()
        try:
            hypothesis = transcribe(audio)
            elapsed = round(time.perf_counter() - started, 3)
            ref_tokens = normalize_arabic(reference)
            hyp_tokens = normalize_arabic(hypothesis)
            s, d, ins, errors = edit_distance(ref_tokens, hyp_tokens)
            total_s += s; total_d += d; total_i += ins; total_err += errors; total_words += len(ref_tokens)
            rows.append({"file": audio.name, "status": "ok", "reference": reference, "hypothesis": hypothesis, "wer": round(errors / max(1, len(ref_tokens)), 4), "substitutions": s, "deletions": d, "insertions": ins, "latency_seconds": elapsed})
        except Exception as exc:
            rows.append({"file": audio.name, "status": "error", "error": str(exc)})
    return {"files": len(audio_files), "evaluated": sum(r.get("status") == "ok" for r in rows), "wer": round(total_err / max(1, total_words), 4), "substitutions": total_s, "deletions": total_d, "insertions": total_i, "rows": rows}


def evaluate_tts(text: str, output: Path | None) -> dict:
    from mizan.tts import text_to_speech, clean_text_for_tts
    out = output or Path.cwd() / "evaluation" / "tts_smoke_test.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result_path = text_to_speech(text, str(out))
    elapsed = round(time.perf_counter() - started, 3)
    result = {"text": text, "cleaned_text": clean_text_for_tts(text), "output": str(result_path or out), "latency_seconds": elapsed, "exists": bool(result_path and Path(result_path).exists())}
    if result["exists"]:
        result["bytes"] = Path(result_path).stat().st_size
    result["human_clarity_required"] = True
    result["note"] = "Automated checks confirm generation and file integrity; clarity, pronunciation and naturalness require listening review."
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", type=Path, default=Path("evaluation/voice_data"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/voice_report.json"))
    parser.add_argument("--tts-text")
    parser.add_argument("--tts-output", type=Path)
    args = parser.parse_args()
    report = {"normalization": "Arabic diacritics/punctuation removed; alef/yaa/taa marbuta normalized", "stt_model": "local models/whisper-small-libyan if present, otherwise Tass02/whisper-small-libyan", "splits": {}}
    if args.audio_dir.exists():
        for name in ("clean", "dialect", "noisy"):
            split = args.audio_dir / name
            if split.exists():
                report["splits"][name] = evaluate_split(split)
    else:
        report["dataset_status"] = "missing_audio_dataset"
    if args.tts_text:
        report["tts"] = evaluate_tts(args.tts_text, args.tts_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
