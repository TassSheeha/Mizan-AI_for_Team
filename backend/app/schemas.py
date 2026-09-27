"""app.schemas — Pydantic request/response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# ─── Auth ─────────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Chat / conversations ─────────────────────────────────────────────────────
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class CitationOut(BaseModel):
    article: str | int | None = None
    page: int | None = None
    section: str | None = None
    chapter: str | None = None
    document: str | None = None
    doc_id: str | None = None
    year: int | None = None
    text: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[CitationOut] | None = None
    confidence: float = 0.0
    retrieval_time: float = 0.0
    generation_time: float = 0.0
    provider: str = ""
    answer_type: str = "answer"
    feedback: Literal["like", "dislike", None] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=10)
    mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    doc_id: str | None = None


class FeedbackRequest(BaseModel):
    value: Literal["like", "dislike", None]


# ─── Admin ────────────────────────────────────────────────────────────────────
class DocumentUploadMeta(BaseModel):
    doc_id: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=300)
    doc_type: str = Field(default="law", max_length=30)
    year: int = Field(default=0, ge=0, le=2100)
    specialization: str = Field(default="", max_length=50)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    doc_type: str | None = Field(default=None, max_length=30)
    year: int | None = Field(default=None, ge=0, le=2100)
    specialization: str | None = Field(default=None, max_length=50)


class DocumentOut(BaseModel):
    id: int
    doc_id: str
    title: str
    doc_type: str
    year: int
    specialization: str
    chunk_count: int
    status: str
    error_message: str | None = None
    is_builtin: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


class NotificationOut(BaseModel):
    id: int
    title: str
    body: str
    created_at: datetime
    is_read: bool = False

    class Config:
        from_attributes = True


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    role: Literal["user", "admin", None] = None


class UserAdminOut(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    conversation_count: int = 0

    class Config:
        from_attributes = True
