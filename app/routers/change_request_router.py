from fastapi import APIRouter, Depends, HTTPException, Query, Body
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
from app.services import change_request_service, approval_service
from app.services.utils import json_to_dict

router = APIRouter(prefix="/api/change-requests", tags=["变更申请"])


@router.post("", summary="提交变更申请")
def submit_request(request_data: ChangeRequestCreate,
                   priority: str = Query("NORMAL", description="优先级: NORMAL/HIGH"),
                   db: Session = Depends(get_db)):
    try:
        result = change_request_service.submit_change_request(db, request_data, priority)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=PaginatedResponse, summary="查询变更申请列表")
def list_requests(
    customer_name: Optional[str] = Query(None, description="客户名称"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    quick_range: Optional[str] = Query(None, description="快捷范围: today/yesterday/7d/30d"),
    status: Optional[str] = Query(None, description="状态"),
    department: Optional[str] = Query(None, description="部门"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    if quick_range:
        result = change_request_service.query_change_requests_quick(
            db, quick_range=quick_range, customer_name=customer_name,
            status=status, department=department,
            page=page, page_size=page_size
        )
    else:
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


@router.get("/{request_id}", summary="获取变更申请详情（含审批流程）")
def get_request(request_id: int, db: Session = Depends(get_db)):
    try:
        detail = change_request_service.get_change_request_detail(db, request_id)
        return detail
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{request_id}/approve", summary="审批通过")
def approve_request(request_id: int, action_data: ApprovalAction, db: Session = Depends(get_db)):
    try:
        request = approval_service.approve_request(
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
    from app.services import sync_service
    records = sync_service.get_sync_records(db, change_request_id=request_id)
    return records


@router.get("/{request_id}/approval-flow", summary="获取审批流程详情")
def get_approval_flow(request_id: int, db: Session = Depends(get_db)):
    records = approval_service.get_approval_records(db, request_id)
    request = change_request_service.get_change_request_by_id(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="变更申请不存在")

    chain = request.approval_chain
    nodes = []
    if chain:
        for node in chain.nodes:
            record = None
            for r in records:
                if r.node_id == node.id:
                    record = r
                    break
            nodes.append({
                "node_id": node.id,
                "node_name": node.node_name,
                "node_order": node.node_order,
                "approver_role": node.approver_role,
                "approver": node.approver,
                "department": node.department,
                "timeout_hours": node.timeout_hours,
                "status": record.action if record else "PENDING",
                "actual_approver": record.approver if record else None,
                "comment": record.comment if record else None,
                "approved_at": record.approved_at if record else None,
                "is_overdue": record.is_overdue if record else False
            })

    return {
        "request_id": request_id,
        "request_no": request.request_no,
        "chain_name": chain.chain_name if chain else "",
        "current_node_index": request.current_node_index,
        "total_nodes": len(chain.nodes) if chain else 0,
        "status": request.status,
        "nodes": nodes
    }
