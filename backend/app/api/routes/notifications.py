"""app.api.routes.notifications — User-facing notification inbox."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Notification, NotificationRead, User, get_db
from app.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Notification, NotificationRead.id)
        .outerjoin(NotificationRead, (
            (NotificationRead.notification_id == Notification.id)
            & (NotificationRead.user_id == user.id)
        ))
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "created_at": n.created_at.isoformat(),
            "is_read": read_id is not None,
        }
        for n, read_id in rows
    ]


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if notification is None:
        from app.core.errors import ApiError
        raise ApiError(404, "not_found", "الإشعار غير موجود.")
    existing = (
        db.query(NotificationRead)
        .filter(
            NotificationRead.notification_id == notification_id,
            NotificationRead.user_id == user.id,
        )
        .first()
    )
    if not existing:
        db.add(NotificationRead(notification_id=notification_id, user_id=user.id))
        db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    all_notifications = db.query(Notification).all()
    read_ids = {
        r.notification_id
        for r in db.query(NotificationRead).filter(NotificationRead.user_id == user.id).all()
    }
    for n in all_notifications:
        if n.id not in read_ids:
            db.add(NotificationRead(notification_id=n.id, user_id=user.id))
    db.commit()
    return {"ok": True}
