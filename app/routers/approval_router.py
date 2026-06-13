from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.services import approval_rule_service, approval_service
from app.schemas import PaginatedResponse

router = APIRouter(prefix="/api/approval", tags=["审批管理"])


@router.get("/chains", summary="获取审批链列表")
def list_chains(is_active: Optional[bool] = Query(None, description="是否启用"), db: Session = Depends(get_db)):
    chains = approval_rule_service.list_approval_chains(db, is_active=is_active)
    return {
        "total": len(chains),
        "items": chains
    }


@router.get("/chains/{chain_id}", summary="获取审批链详情")
def get_chain_detail(chain_id: int, db: Session = Depends(get_db)):
    chain = approval_rule_service.get_approval_chain_detail(db, chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="审批链不存在")
    return chain


@router.post("/chains", summary="创建审批链")
def create_chain(
    chain_name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
    nodes: List[dict] = Body([], embed=True),
    db: Session = Depends(get_db)
):
    try:
        chain = approval_rule_service.create_approval_chain(
            db, chain_name, description, nodes
        )
        return chain
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rules", summary="获取审批规则列表")
def list_rules(is_active: Optional[bool] = Query(None, description="是否启用"), db: Session = Depends(get_db)):
    rules = approval_rule_service.list_approval_rules(db, is_active=is_active)
    return {
        "total": len(rules),
        "items": rules
    }


@router.post("/rules", summary="创建审批规则")
def create_rule(
    rule_name: str = Body(..., embed=True),
    chain_id: int = Body(..., embed=True),
    priority: int = Body(0, embed=True),
    customer_level: Optional[str] = Body(None, embed=True),
    change_type: Optional[str] = Body(None, embed=True),
    department: Optional[str] = Body(None, embed=True),
    industry: Optional[str] = Body(None, embed=True),
    min_change_fields: int = Body(0, embed=True),
    description: str = Body("", embed=True),
    db: Session = Depends(get_db)
):
    try:
        rule = approval_rule_service.create_approval_rule(
            db, rule_name=rule_name, chain_id=chain_id, priority=priority,
            customer_level=customer_level, change_type=change_type,
            department=department, industry=industry,
            min_change_fields=min_change_fields, description=description
        )
        return rule
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/rules/{rule_id}", summary="更新审批规则")
def update_rule(rule_id: int, updates: dict, db: Session = Depends(get_db)):
    try:
        rule = approval_rule_service.update_approval_rule(db, rule_id, **updates)
        return rule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rules/{rule_id}/toggle", summary="启用/禁用审批规则")
def toggle_rule(rule_id: int, is_active: bool = Body(..., embed=True), db: Session = Depends(get_db)):
    try:
        rule = approval_rule_service.toggle_approval_rule(db, rule_id, is_active)
        return rule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/todo/stats", summary="获取待办统计")
def get_todo_stats(
    approver: Optional[str] = Query(None, description="审批人"),
    role: Optional[str] = Query(None, description="审批角色"),
    department: Optional[str] = Query(None, description="部门"),
    db: Session = Depends(get_db)
):
    return approval_service.get_todo_stats(
        db, approver=approver, role=role, department=department
    )


@router.get("/todo", summary="获取我的待审批列表")
def get_my_todo(
    approver: Optional[str] = Query(None, description="审批人"),
    role: Optional[str] = Query(None, description="审批角色"),
    department: Optional[str] = Query(None, description="部门"),
    priority: Optional[str] = Query(None, description="优先级"),
    is_overdue: Optional[bool] = Query(None, description="是否超时"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    result = approval_service.get_my_todo(
        db, approver=approver, role=role, department=department,
        priority=priority, is_overdue=is_overdue,
        page=page, page_size=page_size
    )
    return result


@router.post("/todo/batch-approve", summary="批量审批通过")
def batch_approve(
    request_ids: List[int] = Body(..., embed=True),
    approver: str = Body(..., embed=True),
    comment: str = Body("", embed=True),
    db: Session = Depends(get_db)
):
    if not request_ids:
        raise HTTPException(status_code=400, detail="请选择要审批的申请")
    result = approval_service.batch_approve(db, request_ids, approver, comment)
    return result


@router.post("/todo/batch-reject", summary="批量驳回")
def batch_reject(
    request_ids: List[int] = Body(..., embed=True),
    approver: str = Body(..., embed=True),
    comment: str = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    if not request_ids:
        raise HTTPException(status_code=400, detail="请选择要驳回的申请")
    result = approval_service.batch_reject(db, request_ids, approver, comment)
    return result


@router.post("/check-overdue", summary="检查并更新超时申请")
def check_overdue(db: Session = Depends(get_db)):
    count = approval_service.check_and_update_overdue(db)
    return {"overdue_count": count}


@router.get("/records/{request_id}", summary="获取申请的审批记录")
def get_approval_records(request_id: int, db: Session = Depends(get_db)):
    records = approval_service.get_approval_records(db, request_id)
    return {
        "total": len(records),
        "items": records
    }
