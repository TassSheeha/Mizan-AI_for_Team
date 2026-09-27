"""app.api.routes.auth — Registration, login, token refresh, profile, logout."""

import jwt
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import ApiError
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token, create_refresh_token, decode_token,
    hash_password, verify_password,
)
from app.core.logging import audit
from app.db.models import RefreshToken, User, get_db
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenPair, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue_tokens(db: Session, user: User) -> TokenPair:
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    jti = decode_token(refresh, expected_type="refresh")["jti"]
    exp = datetime.fromtimestamp(
        decode_token(refresh, expected_type="refresh")["exp"], tz=timezone.utc
    ).replace(tzinfo=None)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=exp))
    db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenPair, status_code=201)
@limiter.limit("10/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise ApiError(409, "email_taken", "هذا البريد الإلكتروني مسجّل مسبقاً.")
    if db.query(User).filter(User.username == body.username).first():
        raise ApiError(409, "username_taken", "اسم المستخدم محجوز مسبقاً.")

    user = User(
        email=body.email.lower(),
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit("user.register", user.id, user.email)
    return _issue_tokens(db, user)


@router.post("/login", response_model=TokenPair)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "bad_credentials", "البريد الإلكتروني أو كلمة المرور غير صحيحة.")
    if not user.is_active:
        raise ApiError(403, "account_disabled", "تم تعطيل هذا الحساب. تواصل مع المسؤول.")

    user.last_login_at = datetime.utcnow()
    db.commit()
    audit("user.login", user.id, user.email)
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "انتهت صلاحية الجلسة. سجّل الدخول من جديد.")
    except jwt.PyJWTError:
        raise ApiError(401, "invalid_token", "رمز التحديث غير صالح.")

    record = db.get(RefreshToken, payload["jti"])
    if record is None or record.revoked:
        raise ApiError(401, "invalid_token", "رمز التحديث ملغى أو غير معروف.")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "account_disabled", "الحساب غير موجود أو معطّل.")

    record.revoked = True  # rotation: one-time refresh tokens
    db.commit()
    return _issue_tokens(db, user)


@router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
        record = db.get(RefreshToken, payload["jti"])
        if record:
            record.revoked = True
            db.commit()
    except jwt.PyJWTError:
        pass
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
