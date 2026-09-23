import os
import re
import subprocess
import tempfile
import time
import wave

import streamlit as st
from transformers import pipeline

@st.cache_resource
def load_stt_model():
    """
    Load the fine-tuned Libyan Whisper model from the local project directory.
    """
    # Define the local directory path for the Libyan dialect model
    local_model_path = "./models/whisper-small-libyan"

    # Check if the local directory exists, otherwise fallback to Tasneem's model online as a backup
    model_path = local_model_path if os.path.exists(local_model_path) else "Tass02/whisper-small-libyan"

    # Load the pipeline passing the local model
    stt_pipeline = pipeline("automatic-speech-recognition", model=model_path)
    return stt_pipeline


# ─── Audio decoding helpers ───────────────────────────────────────────────────
# Streamlit's microphone recorder returns WebM/Opus bytes, NOT a WAV file.
# Whisper reads 16 kHz mono PCM WAV reliably; anything else must be converted
# with ffmpeg first. Decoding is decided by the file CONTENT (magic bytes),
# never by its extension.

def _is_riff_wav(path: str) -> bool:
    """True if the file content is a real RIFF/WAVE (PCM) container."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        return header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    except Exception:
        return False


def _convert_to_wav(path: str) -> str | None:
    """
    Convert any ffmpeg-decodable audio (webm/opus, mp4/aac, ogg...) to a
    16 kHz mono PCM WAV file in the system temp folder.
    Returns the new path, or None if ffmpeg is unavailable / conversion fails.
    """
    out_path = os.path.join(
        tempfile.gettempdir(), f"mizan_stt_{int(time.time() * 1000)}.wav"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", path, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", out_path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 44:
            return out_path
    except FileNotFoundError:
        print("[STT] ffmpeg was not found on PATH — cannot decode non-WAV audio.")
    except Exception as e:
        print(f"[STT] ffmpeg conversion failed: {e}")
    return None


def _ensure_wav(path: str) -> str:
    """Return a path Whisper can read: converts non-RIFF files via ffmpeg."""
    if _is_riff_wav(path):
        return path
    converted = _convert_to_wav(path)
    return converted if converted else path


# ─── Transcription sanity check ───────────────────────────────────────────────
# Whisper (small models, short/noisy clips) sometimes produces hallucinated
# loops instead of speech, e.g. "أَلَّا وَـٰٰٰٰٰٰٰٰٰ..." — one character or
# syllable repeated for hundreds of tokens. Such output must be rejected so
# the user is asked to retry instead of receiving garbage as their "question".

# Any character repeated more than this many times in a row is pathological
# (real Arabic speech never repeats the same letter 3+ times consecutively).
_MAX_CHAR_RUN = 3
_MAX_TOP_CHAR_RATIO = 0.35  # one char dominating >35% of the text => garbage


def _sanitize_transcription(text: str) -> str:
    """Collapse pathological character runs and strip the result if it is garbage."""
    if not text:
        return ""

    # 1. Collapse runs of the same character (incl. tatweel & superscript alef)
    collapsed = re.sub(r"(.)\1{%d,}" % _MAX_CHAR_RUN, r"\1" * _MAX_CHAR_RUN, text)

    # 2. Garbage detection on the letter content
    letters_only = re.sub(r"[^\u0600-\u06FF]", "", collapsed)
    if len(letters_only) < 3:
        return ""

    top_char = max(set(letters_only), key=letters_only.count)
    if letters_only.count(top_char) / len(letters_only) > _MAX_TOP_CHAR_RATIO:
        return ""

    # 3. Word-level diversity: hallucination loops repeat 1-2 words endlessly
    words = [w for w in collapsed.split() if len(w) >= 2]
    if len(words) >= 8 and len(set(words)) / len(words) < 0.2:
        return ""

    return " ".join(collapsed.split())


def transcribe_audio(audio_file_path):
    """
    Transcribe the recorded audio file into text using the Libyan dialect STT pipeline.
    Accepts WAV as well as compressed recordings (WebM/Opus, MP4/AAC...);
    non-WAV input is converted to 16 kHz mono WAV with ffmpeg before decoding.
    Returns "" when the recording is unreadable or the model produced
    hallucinated/garbage output instead of speech.
    """
    try:
        stt_model = load_stt_model()

        # Configure generation parameters for Arabic to achieve precise Libyan dialect transcription
        result = stt_model(
            _ensure_wav(audio_file_path),
            generate_kwargs={"language": "arabic", "task": "transcribe"},
        )

        raw_text = result.get("text", "")
        cleaned = _sanitize_transcription(raw_text)
        if raw_text and not cleaned:
            print(f"[STT] Rejected hallucinated/garbled transcription: {raw_text[:80]!r}")
        return cleaned
    except Exception as e:
        st.error(f"Error during transcription: {e}")
        return ""
