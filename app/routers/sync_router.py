from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.schemas import PaginatedResponse, SyncRecordResponse
from app.services import sync_service

router = APIRouter(prefix="/api/sync", tags=["系统同步"])


class RetrySyncAllRequest(BaseModel):
    operator: Optional[str] = None


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


@router.post("/records/{record_id}/retry", summary="重试单个系统同步")
def retry_sync(record_id: int, operator: str = None, db: Session = Depends(get_db)):
    try:
        record = sync_service.retry_sync(db, record_id, operator=operator)
        return {
            "success": True,
            "sync_record_id": record.id,
            "target_system": record.target_system,
            "status": record.status,
            "retry_count": record.retry_count
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/requests/{request_id}/retry-all", summary="重试申请单所有失败同步")
def retry_sync_all(request_id: int, req: RetrySyncAllRequest = None, db: Session = Depends(get_db)):
    try:
        operator = req.operator if req else None
        result = sync_service.retry_sync_all(db, request_id, operator=operator)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/requests/{request_id}/summary", summary="获取同步结果汇总")
def get_sync_summary(request_id: int, db: Session = Depends(get_db)):
    try:
        summary = sync_service.get_sync_summary(db, request_id)
        return {
            "success": True,
            "data": summary
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
