from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.schemas import PaginatedResponse, SyncRecordResponse
from app.services import sync_service

router = APIRouter(prefix="/api/sync", tags=["系统同步"])


@router.get("/records", response_model=PaginatedResponse, summary="查询同步记录")
def list_sync_records(
    change_request_id: Optional[int] = Query(None, description="变更申请ID"),
    status: Optional[str] = Query(None, description="同步状态"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    return sync_service.get_sync_records(
        db, change_request_id=change_request_id, status=status,
        page=page, page_size=page_size
    )


@router.post("/records/{record_id}/retry", summary="重试同步")
def retry_sync(record_id: int, db: Session = Depends(get_db)):
    try:
        record = sync_service.retry_sync(db, record_id)
        return record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
