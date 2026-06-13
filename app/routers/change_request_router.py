from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date
from app.database import get_db
from app.schemas import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    ChangeRequestQuery,
    PaginatedResponse,
    ApprovalAction
)
from app.services import change_request_service, approval_service, sync_service
from app.services.utils import json_to_dict

router = APIRouter(prefix="/api/change-requests", tags=["变更申请"])


@router.post("", summary="提交变更申请")
def submit_request(request_data: ChangeRequestCreate, db: Session = Depends(get_db)):
    try:
        request = change_request_service.submit_change_request(db, request_data)
        return change_request_service.format_change_request_response(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=PaginatedResponse, summary="查询变更申请列表")
def list_requests(
    customer_name: Optional[str] = Query(None, description="客户名称"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    status: Optional[str] = Query(None, description="状态"),
    department: Optional[str] = Query(None, description="部门"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    query = ChangeRequestQuery(
        customer_name=customer_name,
        start_date=start_date,
        end_date=end_date,
        status=status,
        department=department,
        page=page,
        page_size=page_size
    )
    result = change_request_service.query_change_requests(db, query)
    items = [change_request_service.format_change_request_response(item) for item in result["items"]]
    return {
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": items
    }


@router.get("/{request_id}", summary="获取变更申请详情")
def get_request(request_id: int, db: Session = Depends(get_db)):
    request = change_request_service.get_change_request_by_id(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="变更申请不存在")
    return change_request_service.format_change_request_response(request)


@router.post("/{request_id}/approve", summary="审批通过")
def approve_request(request_id: int, action_data: ApprovalAction, db: Session = Depends(get_db)):
    try:
        request = approval_service.manual_approve(
            db, request_id, action_data.approver, action_data.comment
        )
        return change_request_service.format_change_request_response(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{request_id}/reject", summary="驳回申请")
def reject_request(request_id: int, action_data: ApprovalAction, db: Session = Depends(get_db)):
    try:
        request = approval_service.reject_request(
            db, request_id, action_data.approver, action_data.comment
        )
        return change_request_service.format_change_request_response(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{request_id}/sync-records", summary="获取同步记录")
def get_sync_records(request_id: int, db: Session = Depends(get_db)):
    records = sync_service.get_sync_records(db, change_request_id=request_id)
    return records
