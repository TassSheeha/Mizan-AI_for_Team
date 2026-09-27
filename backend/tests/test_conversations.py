"""Conversations CRUD + ownership isolation + SSE streaming chat + feedback."""


def test_create_and_list_conversations(client, user_headers):
    res = client.post("/api/conversations", json={"title": "اختبار"}, headers=user_headers)
    assert res.status_code == 201
    conv_id = res.json()["id"]

    listed = client.get("/api/conversations", headers=user_headers).json()
    assert any(c["id"] == conv_id for c in listed)
    assert all(c["message_count"] >= 1 for c in listed)  # welcome message


def test_conversation_get_messages(client, user_headers):
    conv_id = client.post("/api/conversations", headers=user_headers).json()["id"]
    data = client.get(f"/api/conversations/{conv_id}", headers=user_headers).json()
    assert data["id"] == conv_id
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "assistant"


def test_rename_and_delete_conversation(client, user_headers):
    conv_id = client.post("/api/conversations", headers=user_headers).json()["id"]

    res = client.patch(
        f"/api/conversations/{conv_id}",
        json={"title": "عنوان جديد"}, headers=user_headers,
    )
    assert res.status_code == 200
    assert res.json()["title"] == "عنوان جديد"

    assert client.delete(f"/api/conversations/{conv_id}", headers=user_headers).status_code == 200
    assert client.get(f"/api/conversations/{conv_id}", headers=user_headers).status_code == 404


def test_ownership_isolation(client, user_headers, second_user_headers):
    conv_id = client.post("/api/conversations", headers=user_headers).json()["id"]
    # Another user must not see or modify it
    assert client.get(f"/api/conversations/{conv_id}", headers=second_user_headers).status_code == 404
    assert client.delete(f"/api/conversations/{conv_id}", headers=second_user_headers).status_code == 404


def test_chat_stream_sse_and_persistence(client, user_headers):
    from app.services import ai as ai_mod

    svc = ai_mod.ai_service
    svc.ask_stream_sync = lambda **kw: {
        "type": "answer",
        "sources": [],
        "citations": [{
            "article": "12", "document": "قانون علاقات العمل", "page": 5,
            "text": "نص المادة", "doc_id": "LAW_12_2010",
        }],
        "confidence": 0.91,
        "retrieval_query": "س",
        "stream": iter(["إجابة ", "اختبار ", "بالثدفق"]),
    }
    svc.finish_stream_sync = lambda text: text.strip()
    svc.provider_name = lambda: "groq"

    res = client.post(
        "/api/chat/stream",
        json={"query": "شن حقوقي في الإجازة؟", "top_k": 3, "mode": "hybrid"},
        headers=user_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in res.text
    assert "event: token" in res.text
    assert "event: done" in res.text

    # Extract conversation id from meta event
    meta_line = [l for l in res.text.splitlines() if l.startswith("data: ")][0]
    conv_id = meta_line.split('"conversation_id": "')[1].split('"')[0]

    # Conversation + both messages persisted
    data = client.get(f"/api/conversations/{conv_id}", headers=user_headers).json()
    roles = [m["role"] for m in data["messages"]]
    assert roles == ["assistant", "user", "assistant"]  # welcome, question, answer
    answer = data["messages"][-1]
    assert answer["content"] == "إجابة اختبار بالثدفق"
    assert answer["citations"][0]["article"] == "12"
    assert answer["provider"] == "groq"

    # Auto-title from first question
    listed = client.get("/api/conversations", headers=user_headers).json()
    conv = next(c for c in listed if c["id"] == conv_id)
    assert "الإجازة" in conv["title"]


def test_feedback_toggle(client, user_headers):
    from app.services import ai as ai_mod

    svc = ai_mod.ai_service
    svc.ask_stream_sync = lambda **kw: {
        "type": "answer", "sources": [], "citations": [], "confidence": 0.9,
        "retrieval_query": "س", "stream": iter(["جواب"]),
    }
    svc.finish_stream_sync = lambda t: t
    svc.provider_name = lambda: "groq"

    res = client.post("/api/chat/stream", json={"query": "سؤال تجريبي"}, headers=user_headers)
    done_data = [l for l in res.text.splitlines() if l.startswith("data: ")][-1]
    msg_id = int(done_data.split('"assistant_message_id": ')[1].split(",")[0])

    # like → dislike → remove
    r1 = client.post(f"/api/messages/{msg_id}/feedback", json={"value": "like"}, headers=user_headers)
    assert r1.status_code == 200 and r1.json()["feedback"] == "like"

    r2 = client.post(f"/api/messages/{msg_id}/feedback", json={"value": "dislike"}, headers=user_headers)
    assert r2.json()["feedback"] == "dislike"

    r3 = client.post(f"/api/messages/{msg_id}/feedback", json={"value": None}, headers=user_headers)
    assert r3.json()["feedback"] is None

    # conversation view reflects feedback state
    conv_id = [l for l in res.text.splitlines() if l.startswith("data: ")][0]
    cid = conv_id.split('"conversation_id": "')[1].split('"')[0]
    data = client.get(f"/api/conversations/{cid}", headers=user_headers).json()
    assert data["messages"][-1]["feedback"] is None
