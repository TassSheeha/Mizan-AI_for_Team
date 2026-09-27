"""
app.api.routes.admin — Admin dashboard API.

Covers: statistics, knowledge-base document management (add/update/delete/
reindex), user management, notifications broadcasting, feedback analytics,
system health, audit log, and database backup.
"""

import json
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import PROJECT_ROOT, settings
from app.core.errors import ApiError
from app.core.logging import audit
from app.db.models import (
    AuditEntry, Conversation, Feedback, LegalDocument, Message, Notification,
    SessionLocal, User, get_db,
)
from app.schemas import (
    DocumentOut, DocumentUpdate, NotificationCreate, UserAdminUpdate,
)
from app.services import documents as docsvc
from app.services.ai import ai_service

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Serialise all knowledge-base mutations (index + DB + AI reload)
_index_lock = threading.Lock()


# ─── Statistics ───────────────────────────────────────────────────────────────
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    day_ago = datetime.utcnow() - timedelta(days=1)
    feedback_rows = (
        db.query(Feedback.value, func.count(Feedback.id))
        .group_by(Feedback.value)
        .all()
    )
    feedback_counts = {value: count for value, count in feedback_rows}
    total_feedback = sum(feedback_counts.values())
    return {
        "users": db.query(User).count(),
        "active_users": db.query(User).filter(User.is_active.is_(True)).count(),
        "conversations": db.query(Conversation).count(),
        "messages": db.query(Message).count(),
        "messages_24h": db.query(Message).filter(Message.created_at >= day_ago).count(),
        "documents": db.query(LegalDocument).filter(LegalDocument.status == "indexed").count(),
        "indexed_chunks": docsvc.full_rebuild_status().get("indexed_chunks", -1),
        "ai_status": ai_service.status,
        "feedback": {
            "like": feedback_counts.get("like", 0),
            "dislike": feedback_counts.get("dislike", 0),
            "total": total_feedback,
            "satisfaction": (
                round(feedback_counts.get("like", 0) / total_feedback * 100, 1)
                if total_feedback else None
            ),
        },
        "avg_confidence": db.query(func.avg(Message.confidence)).scalar() or 0.0,
    }


# ─── Document management ──────────────────────────────────────────────────────
@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return db.query(LegalDocument).order_by(LegalDocument.created_at).all()


def _sync_builtin_documents(db: Session) -> None:
    """Register the 12 built-in documents (from config.py) on first run."""
    import sys

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from config import DOCUMENTS

    for d in DOCUMENTS:
        exists = db.query(LegalDocument).filter(LegalDocument.doc_id == d["doc_id"]).first()
        if exists:
            continue
        chunks_file = docsvc.CHUNKS_DIR / f"{d['doc_id']}_chunks.json"
        chunk_count = 0
        if chunks_file.exists():
            try:
                chunk_count = len(json.loads(chunks_file.read_text(encoding="utf-8")))
            except Exception:
                chunk_count = 0
        db.add(LegalDocument(
            doc_id=d["doc_id"],
            title=d["title"],
            doc_type=d.get("doc_type", "law"),
            year=d.get("year", 0),
            specialization=d.get("specialization", ""),
            source_file=d.get("pdf_file", ""),
            chunks_file=chunks_file.name if chunks_file.exists() else "",
            chunk_count=chunk_count,
            status="indexed",
            is_builtin=True,
        ))
    db.commit()


@router.post("/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form("law"),
    year: int = Form(0),
    specialization: str = Form(""),
    db: Session = Depends(get_db),
):
    _sync_builtin_documents(db)
    import re as _re
    doc_id = doc_id.strip().upper().replace(" ", "_")
    if not _re.fullmatch(r"[A-Z0-9_\-]{2,100}", doc_id):
        raise ApiError(
            422, "bad_doc_id",
            "معرّف الوثيقة غير صالح: استخدم حروفاً إنجليزية وأرقاماً وشرطات فقط (2-100).",
        )
    if db.query(LegalDocument).filter(LegalDocument.doc_id == doc_id).first():
        raise ApiError(409, "doc_exists", "معرّف الوثيقة موجود مسبقاً.")

    filename = file.filename or ""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in (".pdf", ".json"):
        raise ApiError(422, "unsupported_type", "الملفات المدعومة: PDF أو JSON (chunks).")
    if len(filename) > 200:
        raise ApiError(422, "bad_filename", "اسم الملف طويل جداً.")

    dest = docsvc.UPLOADS_DIR / f"{doc_id}{suffix}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    record = LegalDocument(
        doc_id=doc_id, title=title, doc_type=doc_type, year=year,
        specialization=specialization, source_file=dest.name,
        status="processing", is_builtin=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    meta = {
        "doc_id": doc_id, "title": title, "doc_type": doc_type,
        "year": year, "specialization": specialization,
    }

    def _process(record_id: int, path: str, meta_: dict):
        with _index_lock:
            with SessionLocal() as sdb:  # own session: background thread
                rec = sdb.get(LegalDocument, record_id)
                if rec is None:
                    audit("doc.index_failed", None, f"{meta_['doc_id']}: record deleted during processing")
                    return
                try:
                    if path.endswith(".pdf"):
                        count = docsvc.ingest_pdf(docsvc.UPLOADS_DIR / path, meta_)
                    else:
                        count = docsvc.ingest_chunks_file(
                            docsvc.UPLOADS_DIR / path, meta_
                        )
                    if count <= 0:
                        raise ValueError("لم تتم فهرسة أي مقطع: تحقق من محتوى الملف.")
                    # ingest_* persists the canonical copy under CHUNKS_DIR.
                    rec.chunk_count = count
                    rec.chunks_file = f"{meta_['doc_id']}_chunks.json"
                    rec.status = "indexed"
                    rec.error_message = None
                    sdb.commit()
                    audit("doc.indexed", None, f"{meta_['doc_id']} ({count} chunks)")
                    try:
                        ai_service.reload()
                    except Exception as reload_exc:
                        audit("doc.reload_failed", None, f"{meta_['doc_id']}: {reload_exc}")
                except Exception as exc:
                    rec.status = "error"
                    rec.error_message = str(exc)[:1000]
                    sdb.commit()
                    audit("doc.index_failed", None, f"{meta_['doc_id']}: {exc}")

    threading.Thread(
        target=_process, args=(record.id, dest.name, meta), daemon=True
    ).start()
    return record


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
def update_document(
    doc_id: str,
    body: DocumentUpdate,
    db: Session = Depends(get_db),
):
    record = db.query(LegalDocument).filter(LegalDocument.doc_id == doc_id).first()
    if record is None:
        raise ApiError(404, "doc_not_found", "الوثيقة غير موجودة.")
    if body.title is not None:
        record.title = body.title
    if body.doc_type is not None:
        record.doc_type = body.doc_type
    if body.year is not None:
        record.year = body.year
    if body.specialization is not None:
        record.specialization = body.specialization
    db.commit()
    db.refresh(record)
    audit("doc.updated", None, doc_id)
    return record


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    record = db.query(LegalDocument).filter(LegalDocument.doc_id == doc_id).first()
    if record is None:
        raise ApiError(404, "doc_not_found", "الوثيقة غير موجودة.")
    if record.is_builtin:
        raise ApiError(
            403, "builtin_protected",
            "لا يمكن حذف التشريعات الأساسية المضمنة في النظام من هذه الواجهة.",
        )
    if record.status == "processing":
        raise ApiError(409, "busy", "الوثيقة قيد المعالجة حالياً.")

    with _index_lock:
        removed = docsvc.remove_document_from_index(doc_id)
        # remove per-doc chunks file if present
        chunks_file = docsvc.CHUNKS_DIR / f"{doc_id}_chunks.json"
        if chunks_file.exists():
            chunks_file.unlink()
        uploaded = docsvc.UPLOADS_DIR / record.source_file
        if record.source_file and uploaded.exists() and uploaded.suffix in (".pdf", ".json"):
            try:
                uploaded.unlink()
            except OSError:
                pass
        db.delete(record)
        db.commit()
    audit("doc.deleted", None, f"{doc_id} ({removed} chunks removed)")
    try:
        ai_service.reload()
    except Exception as exc:
        audit("doc.reload_failed", None, f"{doc_id}: {exc}")
    return {"ok": True, "removed_chunks": removed}


@router.post("/documents/{doc_id}/reindex")
def reindex_document(doc_id: str, db: Session = Depends(get_db)):
    record = db.query(LegalDocument).filter(LegalDocument.doc_id == doc_id).first()
    if record is None:
        raise ApiError(404, "doc_not_found", "الوثيقة غير موجودة.")
    if record.status == "processing":
        raise ApiError(409, "busy", "الوثيقة قيد المعالجة حالياً. انتظر اكتمال الفهرسة.")
    if not record.chunks_file:
        raise ApiError(409, "no_chunks_file", "لا توجد ملفات مقاطع محفوظة لهذه الوثيقة.")

    # Prefer the canonical copy; fall back to the stored filename in both dirs.
    candidates = [
        docsvc.CHUNKS_DIR / f"{record.doc_id}_chunks.json",
        docsvc.CHUNKS_DIR / record.chunks_file,
        docsvc.UPLOADS_DIR / record.chunks_file,
    ]
    chunks_file = next((p for p in candidates if p.exists()), None)
    if chunks_file is None:
        record.status = "error"
        record.error_message = "ملف المقاطع غير موجود على القرص."
        db.commit()
        raise ApiError(404, "chunks_file_missing", "ملف المقاطع غير موجود على القرص.")

    # Fail fast on unreadable/corrupt files BEFORE touching the live index.
    try:
        import json as _json

        _json.loads(chunks_file.read_text(encoding="utf-8"))
    except Exception as exc:
        record.status = "error"
        record.error_message = f"ملف المقاطع تالف: {exc}"[:1000]
        db.commit()
        raise ApiError(422, "bad_chunks_file", "ملف المقاطع تالف ولا يمكن إعادة فهرسته.")

    with _index_lock:
        try:
            docsvc.remove_document_from_index(doc_id)
            meta = {
                "doc_id": record.doc_id, "title": record.title,
                "doc_type": record.doc_type, "year": record.year,
            }
            count = docsvc.ingest_chunks_file(chunks_file, meta)
            if count <= 0:
                raise ValueError("لم تتم فهرسة أي مقطع.")
            record.chunk_count = count
            record.chunks_file = f"{record.doc_id}_chunks.json"
            record.status = "indexed"
            record.error_message = None
            db.commit()
        except ApiError:
            raise
        except Exception as exc:
            db.rollback()
            record = db.query(LegalDocument).filter(LegalDocument.doc_id == doc_id).first()
            if record is not None:
                record.status = "error"
                record.error_message = str(exc)[:1000]
                db.commit()
            audit("doc.reindex_failed", None, f"{doc_id}: {exc}")
            raise ApiError(500, "reindex_failed", f"فشلت إعادة الفهرسة: {exc}")
    audit("doc.reindexed", None, f"{doc_id} ({count} chunks)")
    try:
        ai_service.reload()
    except Exception as exc:
        audit("doc.reload_failed", None, f"{doc_id}: {exc}")
    return {"ok": True, "chunks": count}


# ─── Users management ─────────────────────────────────────────────────────────
@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = (
        db.query(User, func.count(Conversation.id))
        .outerjoin(Conversation, Conversation.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .all()
    )
    return [
        {
            "id": u.id, "email": u.email, "username": u.username,
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "conversation_count": count,
        }
        for u, count in users
    ]


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserAdminUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "المستخدم غير موجود.")
    if user.id == admin.id and (body.role == "user" or body.is_active is False):
        raise ApiError(422, "self_lockout", "لا يمكنك تعطيل حسابك أو تنزيل صلاحيتك.")
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role
    db.commit()
    audit("user.updated", admin.id, f"user={user_id} role={user.role} active={user.is_active}")
    return {"ok": True}


# ─── Notifications broadcasting ───────────────────────────────────────────────
@router.post("/notifications", status_code=201)
def broadcast_notification(
    body: NotificationCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    notification = Notification(title=body.title, body=body.body, created_by=admin.id)
    db.add(notification)
    db.commit()
    audit("notification.sent", admin.id, body.title)
    return {"ok": True, "id": notification.id}


@router.get("/notifications")
def list_sent_notifications(db: Session = Depends(get_db)):
    rows = db.query(Notification).order_by(Notification.created_at.desc()).limit(100).all()
    return [
        {
            "id": n.id, "title": n.title, "body": n.body,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]


# ─── Feedback analytics ───────────────────────────────────────────────────────
@router.get("/feedback")
def feedback_analytics(db: Session = Depends(get_db)):
    rows = (
        db.query(Feedback, Message, Conversation)
        .join(Message, Feedback.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .order_by(Feedback.created_at.desc())
        .limit(200)
        .all()
    )
    items = [
        {
            "id": fb.id,
            "value": fb.value,
            "created_at": fb.created_at.isoformat(),
            "message_content": msg.content[:300],
            "confidence": msg.confidence,
            "provider": msg.provider,
            "conversation_title": conv.title,
        }
        for fb, msg, conv in rows
    ]
    likes = sum(1 for i in items if i["value"] == "like")
    dislikes = len(items) - likes
    return {"items": items, "summary": {"like": likes, "dislike": dislikes, "total": len(items)}}


# ─── Conversations browser ────────────────────────────────────────────────────
@router.get("/conversations")
def all_conversations(db: Session = Depends(get_db)):
    rows = (
        db.query(Conversation, User.username, func.count(Message.id))
        .join(User, Conversation.user_id == User.id)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": c.id, "title": c.title, "username": username,
            "message_count": count,
            "updated_at": c.updated_at.isoformat(),
        }
        for c, username, count in rows
    ]


# ─── System health ────────────────────────────────────────────────────────────
@router.get("/health")
def health(db: Session = Depends(get_db)):
    started = time.time()
    db_ok = True
    try:
        db.query(User).first()
    except Exception:
        db_ok = False
    db_latency_ms = round((time.time() - started) * 1000, 1)

    index_status = docsvc.full_rebuild_status()

    groq_ok = None
    if settings.GROQ_API_KEY:
        import requests

        try:
            r = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                timeout=4.0,
            )
            groq_ok = r.status_code == 200
        except Exception:
            groq_ok = False

    return {
        "status": "ok" if (db_ok and ai_service.status == "ready") else "degraded",
        "components": {
            "database": {"ok": db_ok, "latency_ms": db_latency_ms},
            "ai_layer": {"status": ai_service.status, "error": ai_service.error},
            "vector_index": index_status,
            "groq_api": {"ok": groq_ok, "model": settings.GROQ_MODEL},
        },
        "uptime_seconds": round(time.time() - (ai_service.started_at or time.time()), 1),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── Audit log ────────────────────────────────────────────────────────────────
@router.get("/audit-log")
def audit_log(db: Session = Depends(get_db)):
    rows = db.query(AuditEntry).order_by(AuditEntry.id.desc()).limit(200).all()
    return [
        {
            "id": r.id, "user_id": r.user_id, "action": r.action,
            "detail": r.detail, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ─── Database backup (SQLite online backup API) ───────────────────────────────
@router.get("/backup")
def backup_database(admin: User = Depends(require_admin)):
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise ApiError(501, "not_supported", "النسخ الاحتياطي متاح حالياً لقواعد SQLite فقط.")
    source = settings.DATABASE_URL.replace("sqlite:///", "")
    dest = PROJECT_ROOT / "backend" / "uploads" / f"mizan_backup_{datetime.utcnow():%Y%m%d_%H%M%S}.db"
    src_conn = sqlite3.connect(source)
    dst_conn = sqlite3.connect(str(dest))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    audit("db.backup", admin.id, dest.name)
    return FileResponse(
        str(dest), media_type="application/octet-stream", filename=dest.name
    )
