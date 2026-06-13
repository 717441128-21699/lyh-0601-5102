from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.schemas import PaginatedResponse
from app.services import risk_service

router = APIRouter(prefix="/api/risk", tags=["风控管理"])


@router.get("/warnings", response_model=PaginatedResponse, summary="查询风控预警列表")
def list_warnings(
    customer_id: Optional[int] = Query(None, description="客户ID"),
    is_handled: Optional[bool] = Query(None, description="是否已处理"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    return risk_service.get_risk_warnings(
        db, customer_id=customer_id, is_handled=is_handled,
        page=page, page_size=page_size
    )


@router.post("/warnings/{warning_id}/handle", summary="处理风控预警")
def handle_warning(
    warning_id: int,
    handler: str = Query(..., description="处理人"),
    comment: str = Query(..., description="处理意见"),
    unfreeze: bool = Query(False, description="是否解除冻结"),
    db: Session = Depends(get_db)
):
    try:
        warning = risk_service.handle_risk_warning(
            db, warning_id, handler, comment, unfreeze
        )
        return warning
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/customers/{customer_id}/status", summary="获取客户风控状态")
def get_customer_risk_status(customer_id: int, db: Session = Depends(get_db)):
    try:
        status = risk_service.get_customer_risk_status(db, customer_id)
        return status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
