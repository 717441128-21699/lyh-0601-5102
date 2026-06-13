from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.schemas import PaginatedResponse
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["通知中心"])


@router.get("", response_model=PaginatedResponse, summary="获取我的通知")
def list_notifications(
    recipient: str = Query(..., description="接收人"),
    is_read: Optional[bool] = Query(None, description="是否已读"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    return notification_service.get_user_notifications(
        db, recipient=recipient, is_read=is_read,
        page=page, page_size=page_size
    )


@router.get("/unread-count", summary="获取未读通知数量")
def get_unread_count(recipient: str = Query(..., description="接收人"), db: Session = Depends(get_db)):
    count = notification_service.get_unread_count(db, recipient)
    return {"unread_count": count}


@router.post("/{notification_id}/read", summary="标记通知为已读")
def mark_read(notification_id: int, recipient: str = Query(...), db: Session = Depends(get_db)):
    try:
        notification = notification_service.mark_notification_read(db, notification_id, recipient)
        return notification
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mark-all-read", summary="全部标记为已读")
def mark_all_read(recipient: str = Query(...), db: Session = Depends(get_db)):
    count = notification_service.mark_all_read(db, recipient)
    return {"marked_count": count}
