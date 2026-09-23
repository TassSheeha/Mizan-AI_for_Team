# -*- coding: utf-8 -*-
"""
eval_voice.py — Dimension 5: Voice Evaluation.

  - Speech recognition accuracy: WER (word error rate) on clean TTS-generated
    MSA speech clips through the full STT path (mizan.stt.transcribe_audio).
  - Dialect robustness: the real Libyan-dialect microphone recording shipped
    with the project (temp_input_audio.wav) must produce a sane transcript or
    be cleanly rejected — never hallucinated garbage.
  - Noise robustness: white noise mixed at ~20 dB SNR must not crash the
    pipeline (WER reported informationally).
  - TTS clarity: generated audio exists, is long enough, and is not silent.

Offline handling: if edge-tts (needs internet) fails, TTS-dependent checks are
SKIPPED with a recorded reason; the suite stays green/red for what it could
actually measure.
"""

import os
import subprocess
import sys
import tempfile
import wave

from eval_common import ModuleResult, wer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_AUDIO = os.path.join(PROJECT_ROOT, "temp_input_audio.wav")

WER_PHRASES = [
    "قانون علاقات العمل الليبي ينظم إجازة سنوية مدفوعة الأجر",
    "يحق للعامل الحصول على إجازة مرضية بتقرير من طبيب معتمد",
    "تنظم قواعد العمل ساعات العمل اليومية والأجر الإضافي",
]


def _ffmpeg(args, timeout=60):
    return subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
        capture_output=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _mp3_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _mean_volume(path):
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in out.stderr.splitlines():
            if "mean_volume" in line:
                return float(line.split("mean_volume:")[1].replace("dB", "").strip())
    except Exception:
        pass
    return -120.0


def _mp3_to_wav16(mp3_path):
    wav_path = mp3_path.rsplit(".", 1)[0] + "_16k.wav"
    proc = _ffmpeg(["-i", mp3_path, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", wav_path])
    return wav_path if proc.returncode == 0 else None


def _add_noise(wav_path):
    """Mix white noise at roughly 20 dB SNR into a copy of the wav."""
    noisy_path = wav_path.replace(".wav", "_noisy.wav")
    proc = _ffmpeg([
        "-i", wav_path,
        "-filter_complex",
        "anoisesrc=color=white:amplitude=0.02:duration=30[a];"
        "[0:a][a]amix=inputs=2:duration=first:normalize=0",
        "-ac", "1", "-ar", "16000", noisy_path,
    ])
    return noisy_path if proc.returncode == 0 else None


def run(ctx, result: ModuleResult):
    from mizan.stt import transcribe_audio
    from mizan.tts import text_to_speech

    tmpdir = tempfile.mkdtemp(prefix="mizan_eval_voice_")

    # ── 1. Dialect robustness: real Libyan mic sample must be sane or rejected ──
    if os.path.exists(SAMPLE_AUDIO):
        try:
            transcript = transcribe_audio(SAMPLE_AUDIO)
        except Exception as e:
            result.fail("Dialect sample transcription runs", repr(e))
        else:
            if transcript == "":
                result.ok("Dialect sample: unreadable/garbled input cleanly rejected",
                          "transcription returned '' (user will be asked to retry)")
            else:
                words = transcript.split()
                uniq = len(set(words)) / max(len(words), 1)
                if len(words) >= 2 and uniq >= 0.5:
                    result.ok("Dialect sample: sane transcript produced",
                              f"{transcript[:80]!r}")
                else:
                    result.fail("Dialect sample produced garbage",
                                f"{transcript[:80]!r}")
    else:
        result.skip("Dialect sample transcription", "temp_input_audio.wav not found")

    # ── 2. WER on clean TTS speech + 3. TTS clarity ──
    wav_paths = []
    tts_ok = True
    for i, phrase in enumerate(WER_PHRASES):
        mp3 = text_to_speech(phrase, output_file_path=os.path.join(tmpdir, f"phrase_{i}.mp3"))
        if not mp3 or not os.path.exists(mp3) or os.path.getsize(mp3) < 2048:
            tts_ok = False
            break
        dur = _mp3_duration(mp3)
        vol = _mean_volume(mp3)
        if dur >= 1.5 and vol > -45:
            result.ok(f"TTS clarity phrase {i + 1}",
                      f"duration={dur:.1f}s mean_volume={vol:.1f}dB")
        else:
            result.fail(f"TTS clarity phrase {i + 1}",
                        f"duration={dur:.1f}s mean_volume={vol:.1f}dB")
        wav = _mp3_to_wav16(mp3)
        if wav:
            wav_paths.append((phrase, wav))

    if not tts_ok:
        result.skip("TTS clarity", "edge-tts unavailable (no internet?)")
        result.skip("STT WER (TTS-generated speech)", "no TTS audio available")

    if wav_paths:
        wers = []
        noisy_wer = None
        for i, (phrase, wav) in enumerate(wav_paths):
            try:
                hyp = transcribe_audio(wav)
            except Exception as e:
                result.fail(f"STT transcribes phrase {i + 1}", repr(e))
                continue
            if not hyp:
                result.fail(f"STT returned empty for phrase {i + 1}", phrase)
                continue
            w = wer(phrase, hyp)
            wers.append(w)
            result.info(f"  WER phrase {i + 1}: {w:.2f}  ref={phrase[:40]!r} hyp={hyp[:60]!r}")

            if i == 0:
                noisy = _add_noise(wav)
                if noisy:
                    try:
                        hyp_n = transcribe_audio(noisy)
                    except Exception as e:
                        result.fail("Noise robustness: pipeline crashed on noisy input", repr(e))
                    else:
                        noisy_wer = wer(phrase, hyp_n) if hyp_n else 1.0
                        result.ok("Noise robustness: noisy input handled without crash",
                                  f"WER={noisy_wer:.2f} (informational)")
                else:
                    result.skip("Noise robustness", "ffmpeg noise mix failed")

        if wers:
            avg = sum(wers) / len(wers)
            if avg < 0.5 and all(w < 0.8 for w in wers):
                result.ok("Speech recognition accuracy: avg WER < 0.50 (clean MSA speech)",
                          f"avg={avg:.2f} over {len(wers)} phrases")
            else:
                result.fail("Speech recognition accuracy: avg WER < 0.50",
                            f"avg={avg:.2f} details in notes")
            result.info(f"  WER details: {[round(w, 3) for w in wers]}, noisy={noisy_wer}")

    # ── 4. STT robustness: corrupted/unsupported bytes must not crash ──
    bad_path = os.path.join(tmpdir, "corrupted.webm")
    with open(bad_path, "wb") as f:
        f.write(b"\x1aE\xdf\xa3not-actually-a-webm-stream\x00\x01\x02")
    try:
        out = transcribe_audio(bad_path)
        result.ok("Corrupted audio handled gracefully (no exception)", f"returned {out!r}")
    except Exception as e:
        result.fail("Corrupted audio crashed the STT path", repr(e))
