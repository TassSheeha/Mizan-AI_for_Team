"""
app.api.routes.voice — Speech-to-text endpoint (Libyan dialect).

Uses the SAME Whisper model as the Streamlit app: Tass02/whisper-small-libyan,
loaded through mizan.stt (unchanged). The model is heavy (~250 MB on first
run) so it is preloaded once in a background thread; the endpoint runs the
transcription in a threadpool to keep the event loop free.
"""

import logging
import os
import re
import tempfile
import threading

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.api.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import limiter
from app.db.models import User

router = APIRouter(prefix="/api/voice", tags=["voice"])
logger = logging.getLogger("mizan.voice")

MAX_AUDIO_MB = 15
_state = {"status": "starting", "error": None}
_lock = threading.Lock()


def preload() -> None:
    """Start background loading of the Whisper STT model."""
    if os.environ.get("MIZAN_TEST_MODE") == "1":
        _state["status"] = "ready"
        return

    def _load():
        try:
            from mizan.stt import load_stt_model

            load_stt_model()
            with _lock:
                _state["status"] = "ready"
                _state["error"] = None
            logger.info("STT model ready (Tass02/whisper-small-libyan)")
        except Exception as exc:
            with _lock:
                _state["status"] = "failed"
                _state["error"] = str(exc)
            logger.exception("STT model failed to load")

    threading.Thread(target=_load, daemon=True, name="stt-init").start()


@router.get("/status")
def status():
    return {"status": _state["status"]}


def _transcribe_sync(path: str) -> str:
    from mizan.stt import transcribe_audio

    return transcribe_audio(path)


# ─── Text-to-speech (same voice + cleaning as the Streamlit app) ─────────────
# NOTE: we deliberately do NOT import mizan.tts here because that module pulls
# in streamlit (st.error) which must never run inside the FastAPI process.
TTS_VOICE = "ar-SA-HamedNeural"
TTS_MAX_CHARS = 4000

_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]+", flags=re.UNICODE
)


def clean_text_for_speech(text: str) -> str:
    """Mirror of mizan.tts.clean_text_for_tts (markdown/emoji/newline cleanup)."""
    if not text:
        return ""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"^\s*[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text, _ = re.subn(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s+", "", text, flags=re.MULTILINE)
    text = text.replace("`", "").replace("_", " ")
    text = text.replace("-\n", " ")
    text = re.sub(r"\n+", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=TTS_MAX_CHARS)


def _synthesize_sync(cleaned: str, out_path: str) -> None:
    import asyncio

    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(cleaned, TTS_VOICE).save(out_path)

    asyncio.run(_run())


@router.post("/transcribe")
@limiter.limit("10/minute")
async def transcribe(request: Request, file: UploadFile, user: User = Depends(get_current_user)):
    if _state["status"] == "starting":
        raise ApiError(503, "stt_loading", "محرك التعرف على الصوت قيد التحميل، حاول بعد لحظات.")
    if _state["status"] == "failed":
        raise ApiError(503, "stt_unavailable", "خدمة الصوت غير متاحة حالياً.")

    data = await file.read()
    if len(data) > MAX_AUDIO_MB * 1024 * 1024:
        raise ApiError(413, "too_large", "حجم التسجيل كبير جداً (الحد 15 ميجابايت).")
    if len(data) < 1000:
        raise ApiError(422, "empty_audio", "التسجيل فارغ أو قصير جداً. تحدث لمدة 2-10 ثوانٍ.")

    suffix = ".wav" if (file.filename or "").lower().endswith(".wav") else ".webm"
    fd, path = tempfile.mkstemp(prefix="mizan_voice_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        text = await run_in_threadpool(_transcribe_sync, path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not text:
        return {
            "text": "",
            "message": "لم نتمكن من فهم التسجيل بوضوح. حاول التحدث أقرب للميكروفون في مكان هادئ.",
        }
    return {"text": text}


@router.post("/speak")
@limiter.limit("10/minute")
async def speak(request: Request, body: SpeakRequest, user: User = Depends(get_current_user)):
    """Synthesize an assistant answer to MP3 (same voice as app.py).

    The frontend shows a 🔊 button per answer and auto-plays when the query
    itself came from the microphone — mirroring Streamlit's
    render_audio_icon(autoplay=is_audio_input).
    """
    cleaned = clean_text_for_speech(body.text)
    if not cleaned:
        raise ApiError(422, "empty_text", "لا يوجد نص صالح للتحويل إلى صوت.")
    # Edge-TTS bills per character; truncate very long answers gracefully.
    if len(cleaned) > TTS_MAX_CHARS:
        cleaned = cleaned[:TTS_MAX_CHARS]

    if os.environ.get("MIZAN_TEST_MODE") == "1":
        from fastapi.responses import Response

        return Response(content=b"ID3\x04\x00\x00\x00\x00\x01\x02\x03fake-mp3",
                        media_type="audio/mpeg")

    fd, path = tempfile.mkstemp(prefix="mizan_tts_", suffix=".mp3")
    os.close(fd)
    try:
        await run_in_threadpool(_synthesize_sync, cleaned, path)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        logger.exception("TTS synthesis failed")
        raise ApiError(502, "tts_failed", "تعذر توليد الصوت حالياً. حاول مجدداً.")

    def _cleanup(p: str) -> None:
        try:
            os.remove(p)
        except OSError:
            pass

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename="mizan_answer.mp3",
        background=BackgroundTask(_cleanup, path),
    )
