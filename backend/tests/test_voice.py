"""Voice STT endpoint — status, auth, validation, transcription (stubbed model)."""


def test_voice_status(client, user_headers):
    res = client.get("/api/voice/status", headers=user_headers)
    assert res.status_code == 200
    assert res.json()["status"] in ("ready", "starting", "failed")


def test_voice_requires_auth(client):
    res = client.post("/api/voice/transcribe", files={"file": ("a.wav", b"RIFFxxxx", "audio/wav")})
    assert res.status_code == 401


def test_voice_rejects_empty_audio(client, user_headers):
    from app.api.routes import voice

    voice._state["status"] = "ready"
    res = client.post(
        "/api/voice/transcribe",
        files={"file": ("a.wav", b"tiny", "audio/wav")},
        headers=user_headers,
    )
    assert res.status_code == 422


def test_voice_transcribe_stub(client, user_headers, monkeypatch):
    from app.api.routes import voice

    voice._state["status"] = "ready"
    monkeypatch.setattr(voice, "_transcribe_sync", lambda path: "شن حقي في الإجازة السنوية")

    # Minimal valid RIFF/WAVE header + padding above the 1 KB minimum
    wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 36 + b"\x00" * 2000
    res = client.post(
        "/api/voice/transcribe",
        files={"file": ("a.wav", wav, "audio/wav")},
        headers=user_headers,
    )
    assert res.status_code == 200
    assert res.json()["text"] == "شن حقي في الإجازة السنوية"
