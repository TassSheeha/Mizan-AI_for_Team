"""app.api.deps — Authentication and RBAC dependencies."""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import decode_token
from app.db.models import User, get_db

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise ApiError(401, "not_authenticated", "يجب تسجيل الدخول أولاً.")
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "انتهت صلاحية الجلسة. سجّل الدخول من جديد.")
    except jwt.PyJWTError:
        raise ApiError(401, "invalid_token", "رمز الدخول غير صالح.")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "account_disabled", "الحساب غير موجود أو معطّل.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "هذه الصفحة متاحة للمسؤولين فقط.")
    return user
