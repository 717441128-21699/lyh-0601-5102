from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Notification


def send_notification(db: Session, change_request_id: int, recipient: str,
                       notification_type: str, title: str, content: str) -> Notification:
    notification = Notification(
        change_request_id=change_request_id,
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        content=content
    )
    db.add(notification)
    db.flush()
    return notification


def get_user_notifications(db: Session, recipient: str, is_read: bool = None,
                           page: int = 1, page_size: int = 20) -> dict:
    query = db.query(Notification).filter(Notification.recipient == recipient)

    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)

    total = query.count()
    items = query.order_by(Notification.sent_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }


def mark_notification_read(db: Session, notification_id: int, recipient: str) -> Notification:
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.recipient == recipient
    ).first()

    if not notification:
        raise ValueError("通知不存在或无权限")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


def mark_all_read(db: Session, recipient: str) -> int:
    count = db.query(Notification).filter(
        Notification.recipient == recipient,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return count


def get_unread_count(db: Session, recipient: str) -> int:
    return db.query(Notification).filter(
        Notification.recipient == recipient,
        Notification.is_read == False
    ).count()
