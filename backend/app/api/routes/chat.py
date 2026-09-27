"""
app.api.routes.chat — Conversations CRUD, SSE chat streaming, message feedback.

Streaming contract (SSE, one JSON object per event):
  event: meta   data: {"conversation_id", "user_message_id"}
  event: token  data: {"t": "..."}                       (answer streams only)
  event: done   data: {"assistant_message_id", "answer_type", "citations",
                       "confidence", "retrieval_time", "generation_time",
                       "provider", "content"}
  event: error  data: {"message": "..."}

The generator is a plain sync generator: Starlette iterates it in a threadpool,
which keeps blocking RAG/Groq calls off the event loop.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import limiter
from app.db.models import Conversation, Feedback, Message, User, get_db
from app.schemas import (
    ChatRequest, ConversationCreate, ConversationUpdate, ConversationOut,
    FeedbackRequest, MessageOut,
)
from app.services.ai import ai_service

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger("mizan.chat")

WELCOME_CONTENT = (
    "أهلاً وسهلاً بك! 👋 أنا **الميزان**، مستشارك القانوني الليبي الذكي. "
    "قاعدة معرفتي تغطي 12 تشريعاً ليبياً. تفضل بطرح أي سؤال أو استفسار قانوني "
    "(بالفصحى أو باللهجة الليبية)، وسأجيبك بكل بساطة مع ذكر السند والمواد القانونية المحددة."
)


def _get_owned_conversation(db: Session, user: User, conversation_id: str) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise ApiError(404, "conversation_not_found", "المحادثة غير موجودة.")
    return conv


def _message_out(db: Session, msg: Message) -> dict:
    out = MessageOut(
        id=msg.id, role=msg.role, content=msg.content,
        citations=json.loads(msg.citations) if msg.citations else [],
        confidence=msg.confidence, retrieval_time=msg.retrieval_time,
        generation_time=msg.generation_time, provider=msg.provider,
        answer_type=msg.answer_type, created_at=msg.created_at,
    ).model_dump(mode="json")
    feedback = db.query(Feedback).filter(Feedback.message_id == msg.id).first()
    out["feedback"] = feedback.value if feedback else None
    return out


# ─── Conversations CRUD ───────────────────────────────────────────────────────
@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.is_archived.is_(False))
        .options(joinedload(Conversation.messages))
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "message_count": len(c.messages),
            "last_message": c.messages[-1].content[:120] if c.messages else "",
        }
        for c in convs
    ]


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(user_id=user.id, title=(body.title if body else None) or "محادثة جديدة")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    # Persist a welcome message so a fresh conversation is never empty (ChatGPT-like UX)
    welcome = Message(
        conversation_id=conv.id, role="assistant", content=WELCOME_CONTENT, answer_type="greeting"
    )
    db.add(welcome)
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _get_owned_conversation(db, user, conversation_id)
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id)
        .all()
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": [_message_out(db, m) for m in msgs],
    }


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _get_owned_conversation(db, user, conversation_id)
    conv.title = body.title
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _get_owned_conversation(db, user, conversation_id)
    db.delete(conv)
    db.commit()
    return {"ok": True}


# ─── Chat streaming (SSE) ─────────────────────────────────────────────────────
@router.post("/chat/stream")
@limiter.limit("20/minute")
def chat_stream(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def generate():
        try:
            yield from _run_stream(db, user, body)
        except ApiError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:
            logger.exception("chat stream failed")
            yield _sse("error", {"message": "حدث خطأ أثناء معالجة الطلب."})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_stream(db: Session, user: User, body: ChatRequest):
    query = body.query.strip()
    if not query:
        raise ApiError(422, "empty_query", "اكتب سؤالاً قبل الإرسال.")

    # Resolve or create the conversation
    if body.conversation_id:
        conv = _get_owned_conversation(db, user, body.conversation_id)
    else:
        conv = Conversation(user_id=user.id, title=query[:60])
        db.add(conv)
        db.commit()
        db.refresh(conv)
        db.add(Message(
            conversation_id=conv.id, role="assistant",
            content=WELCOME_CONTENT, answer_type="greeting",
        ))
        db.commit()

    # History BEFORE appending the current question (matches app.py semantics)
    history_rows = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id)
        .all()
    )
    chat_history = [{"role": m.role, "content": m.content} for m in history_rows]

    user_msg = Message(conversation_id=conv.id, role="user", content=query)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    yield _sse("meta", {"conversation_id": conv.id, "user_message_id": user_msg.id})

    filters = {"doc_id": body.doc_id} if body.doc_id else None

    import time
    t0 = time.perf_counter()
    result = ai_service.ask_stream_sync(
        query=query, top_k=body.top_k, mode=body.mode,
        filters=filters, chat_history=chat_history,
    )
    t_retrieval = time.perf_counter() - t0

    answer_type = result["type"]
    if answer_type in ("greeting", "no_match"):
        content = result["answer"]
        asst = Message(
            conversation_id=conv.id, role="assistant", content=content,
            citations=json.dumps([], ensure_ascii=False),
            confidence=result.get("confidence", 0.0),
            retrieval_time=t_retrieval, generation_time=0.0,
            provider=ai_service.provider_name(), answer_type=answer_type,
        )
        db.add(asst)
        db.commit()
        db.refresh(asst)
        yield _sse("token", {"t": content})
        yield _sse("done", {
            "assistant_message_id": asst.id,
            "conversation_id": conv.id,
            "answer_type": answer_type,
            "content": content,
            "citations": [],
            "confidence": result.get("confidence", 0.0),
            "retrieval_time": t_retrieval,
            "generation_time": 0.0,
            "provider": ai_service.provider_name(),
        })
        return

    # Answer stream
    full_response = ""
    for token in result["stream"]:
        full_response += token
        yield _sse("token", {"t": token})

    t1 = time.perf_counter()
    answer = ai_service.finish_stream_sync(full_response)
    t_gen = time.perf_counter() - t1

    citations = result.get("citations", [])
    asst = Message(
        conversation_id=conv.id, role="assistant", content=answer,
        citations=json.dumps(citations, ensure_ascii=False),
        confidence=result.get("confidence", 0.0),
        retrieval_time=t_retrieval, generation_time=t_gen,
        provider=ai_service.provider_name(), answer_type="answer",
    )
    db.add(asst)
    db.commit()
    db.refresh(asst)

    yield _sse("done", {
        "assistant_message_id": asst.id,
        "conversation_id": conv.id,
        "answer_type": "answer",
        "content": answer,
        "citations": citations,
        "confidence": result.get("confidence", 0.0),
        "retrieval_time": t_retrieval,
        "generation_time": t_gen,
        "provider": ai_service.provider_name(),
    })


# ─── Message feedback ─────────────────────────────────────────────────────────
@router.post("/messages/{message_id}/feedback")
def set_feedback(
    message_id: int,
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.get(Message, message_id)
    if msg is None:
        raise ApiError(404, "message_not_found", "الرسالة غير موجودة.")
    conv = db.get(Conversation, msg.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise ApiError(404, "message_not_found", "الرسالة غير موجودة.")
    if msg.role != "assistant":
        raise ApiError(422, "not_rateable", "يمكن تقييم إجابات النظام فقط.")

    from app.db.models import utcnow

    existing = db.query(Feedback).filter(Feedback.message_id == msg.id).first()
    if body.value is None:
        if existing:
            db.delete(existing)
            db.commit()
    else:
        if existing:
            existing.value = body.value
            existing.created_at = utcnow()
        else:
            db.add(Feedback(message_id=msg.id, user_id=user.id, value=body.value))
        db.commit()
    return {"message_id": msg.id, "feedback": body.value}
