from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from app.models import Customer, ChangeRequest, ApprovalRecord
from app.schemas import ChangeRequestCreate, ChangeRequestQuery
from app.services.utils import (
    generate_request_no,
    dict_to_json,
    json_to_dict,
    calculate_diff,
    customer_to_dict,
    log_operation
)
from app.services.risk_service import check_risk_and_freeze
from app.services.approval_service import init_approval_flow, get_approval_records
from app.services import approval_rule_service


def get_customer_by_code(db: Session, customer_code: str) -> Customer:
    return db.query(Customer).filter(Customer.customer_code == customer_code).first()


def get_change_request_by_no(db: Session, request_no: str) -> ChangeRequest:
    return db.query(ChangeRequest).filter(ChangeRequest.request_no == request_no).first()


def get_change_request_by_id(db: Session, request_id: int) -> ChangeRequest:
    return db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()


def submit_change_request(db: Session, request_data: ChangeRequestCreate,
                          priority: str = "NORMAL") -> Dict[str, Any]:
    customer = get_customer_by_code(db, request_data.customer_code)
    if not customer:
        raise ValueError(f"客户编码 {request_data.customer_code} 不存在")

    if customer.is_frozen:
        raise ValueError(f"客户 {customer.customer_name} 已被冻结，无法提交变更申请")

    old_data = customer_to_dict(customer)
    diff_fields = calculate_diff(old_data, request_data.new_data)

    if not diff_fields:
        raise ValueError("未检测到任何数据变更")

    request_no = generate_request_no()

    change_request = ChangeRequest(
        request_no=request_no,
        customer_id=customer.id,
        customer_code=customer.customer_code,
        change_type=request_data.change_type,
        submitter=request_data.submitter,
        department=request_data.department,
        old_data=dict_to_json(old_data),
        new_data=dict_to_json(request_data.new_data),
        diff_data=dict_to_json(diff_fields),
        status="PENDING",
        priority=priority,
        sync_status="PENDING"
    )

    db.add(change_request)
    db.flush()

    log_operation(
        db,
        operation_type="SUBMIT_CHANGE",
        operator=request_data.submitter,
        target_type="CHANGE_REQUEST",
        target_id=change_request.id,
        detail=f"提交客户主数据变更申请: {request_no}, 变更字段: {[f['field'] for f in diff_fields]}"
    )

    risk_result = check_risk_and_freeze(db, customer.id)
    if risk_result["triggered"]:
        change_request.risk_triggered = True
        change_request.risk_reason = risk_result["reason"]
        change_request.status = "RISK_HOLD"
        change_request.sync_status = "BLOCKED"
        db.flush()

        db.commit()
        db.refresh(change_request)

        return {
            "request": format_change_request_response(change_request),
            "risk_triggered": True,
            "risk_reason": risk_result["reason"],
            "approval_flow": None
        }

    approval_result = init_approval_flow(db, change_request, customer, len(diff_fields))

    if not approval_result["success"]:
        db.rollback()
        raise ValueError(approval_result["message"])

    db.commit()
    db.refresh(change_request)

    return {
        "request": format_change_request_response(change_request),
        "risk_triggered": False,
        "approval_flow": {
            "matched_rule": approval_result.get("matched_rule"),
            "match_reason": approval_result.get("match_reason"),
            "chain_name": approval_result.get("chain_name"),
            "total_nodes": approval_result.get("total_nodes"),
            "current_node_index": approval_result.get("current_node_index"),
            "next_approver": _format_next_approver(approval_result.get("next_approver")),
            "approval_records": _format_approval_records(
                get_approval_records(db, change_request.id)
            )
        }
    }


def _format_next_approver(next_info: Dict) -> Dict:
    if not next_info:
        return {}
    return {
        "has_next": next_info.get("has_next", False),
        "node_name": next_info.get("node_name", ""),
        "approver_role": next_info.get("approver_role", ""),
        "approver": next_info.get("approver", ""),
        "department": next_info.get("department", ""),
        "timeout_hours": next_info.get("timeout_hours", 0)
    }


def _format_approval_records(records: List) -> List[Dict]:
    result = []
    for record in records:
        result.append({
            "id": record.id,
            "node_name": record.node_name,
            "node_order": record.node_order,
            "approver_role": record.approver_role,
            "approver": record.approver,
            "action": record.action,
            "comment": record.comment,
            "approved_at": record.approved_at,
            "is_overdue": record.is_overdue
        })
    return result


def query_change_requests(db: Session, query: ChangeRequestQuery) -> Dict[str, Any]:
    query_stmt = db.query(ChangeRequest)

    if query.customer_name:
        query_stmt = query_stmt.filter(
            ChangeRequest.customer_code.in_(
                db.query(Customer.customer_code).filter(
                    Customer.customer_name.like(f"%{query.customer_name}%")
                )
            )
        )

    if query.start_date:
        start_dt = datetime.combine(query.start_date, datetime.min.time())
        query_stmt = query_stmt.filter(ChangeRequest.created_at >= start_dt)

    if query.end_date:
        end_dt = datetime.combine(query.end_date, datetime.max.time())
        query_stmt = query_stmt.filter(ChangeRequest.created_at <= end_dt)

    if query.status:
        query_stmt = query_stmt.filter(ChangeRequest.status == query.status)

    if query.department:
        query_stmt = query_stmt.filter(ChangeRequest.department == query.department)

    total = query_stmt.count()

    items = query_stmt.order_by(ChangeRequest.created_at.desc()) \
        .offset((query.page - 1) * query.page_size) \
        .limit(query.page_size) \
        .all()

    return {
        "total": total,
        "page": query.page,
        "page_size": query.page_size,
        "items": items
    }


def query_change_requests_quick(db: Session, quick_range: str = None,
                                customer_name: str = None, status: str = None,
                                department: str = None, page: int = 1,
                                page_size: int = 20) -> Dict[str, Any]:
    """
    快捷查询：支持最近7天、最近30天等快捷范围
    """
    today = date.today()
    start_date = None

    if quick_range == "7d":
        start_date = today - timedelta(days=7)
    elif quick_range == "30d":
        start_date = today - timedelta(days=30)
    elif quick_range == "today":
        start_date = today
    elif quick_range == "yesterday":
        start_date = today - timedelta(days=1)

    query_obj = ChangeRequestQuery(
        customer_name=customer_name,
        start_date=start_date,
        end_date=today if quick_range in ["today", "yesterday"] else None,
        status=status,
        department=department,
        page=page,
        page_size=page_size
    )

    if quick_range == "yesterday":
        query_obj.end_date = start_date

    return query_change_requests(db, query_obj)


def get_change_count_30d(db: Session, customer_id: int) -> int:
    thirty_days_ago = datetime.now() - timedelta(days=30)
    return db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.created_at >= thirty_days_ago,
            ChangeRequest.status.in_(["APPROVED", "PENDING", "RISK_HOLD"])
        )
    ).count()


def get_change_request_detail(db: Session, request_id: int) -> Dict[str, Any]:
    """获取变更申请详情，包含审批流程记录"""
    request = get_change_request_by_id(db, request_id)
    if not request:
        raise ValueError("变更申请不存在")

    result = format_change_request_response(request)

    approval_records = get_approval_records(db, request_id)
    result["approval_records"] = _format_approval_records(approval_records)

    if request.approval_chain:
        chain = request.approval_chain
        current_index = request.current_node_index
        next_info = approval_rule_service.get_next_approver(chain, current_index)
        result["approval_flow"] = {
            "chain_name": chain.chain_name,
            "total_nodes": len(chain.nodes),
            "current_node_index": current_index,
            "next_approver": _format_next_approver(next_info)
        }

    return result


def format_change_request_response(change_request: ChangeRequest) -> Dict[str, Any]:
    data = {
        "id": change_request.id,
        "request_no": change_request.request_no,
        "customer_id": change_request.customer_id,
        "customer_code": change_request.customer_code,
        "change_type": change_request.change_type,
        "submitter": change_request.submitter,
        "department": change_request.department,
        "priority": change_request.priority,
        "old_data": json_to_dict(change_request.old_data),
        "new_data": json_to_dict(change_request.new_data),
        "diff_data": json_to_dict(change_request.diff_data),
        "status": change_request.status,
        "is_overdue": change_request.is_overdue,
        "approval_level": change_request.approval_level,
        "approval_chain_id": change_request.approval_chain_id,
        "current_node_index": change_request.current_node_index,
        "approver": change_request.approver,
        "approval_comment": change_request.approval_comment,
        "approved_at": change_request.approved_at,
        "risk_triggered": change_request.risk_triggered,
        "risk_reason": change_request.risk_reason,
        "sync_status": change_request.sync_status,
        "synced_at": change_request.synced_at,
        "created_at": change_request.created_at,
        "updated_at": change_request.updated_at
    }
    return data


def get_dashboard_stats(db: Session, approver: str = None) -> Dict[str, Any]:
    """获取首页统计数据"""
    from app.services.approval_service import get_todo_stats
    from app.services.report_service import get_7day_trend

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    today_submitted = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.created_at >= today_start,
            ChangeRequest.created_at <= today_end
        )
    ).count()

    today_approved = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.approved_at >= today_start,
            ChangeRequest.approved_at <= today_end,
            ChangeRequest.status == "APPROVED"
        )
    ).count()

    todo_stats = get_todo_stats(db, approver=approver)
    trend = get_7day_trend(db)

    return {
        "today_submitted": today_submitted,
        "today_approved": today_approved,
        "todo_stats": todo_stats,
        "trend_7d": trend
    }


def continue_after_risk_unfreeze(db: Session, customer_id: int):
    """客户解除风控冻结后，重新激活其待审批申请"""
    pending_requests = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.status == "RISK_HOLD"
        )
    ).all()

    for req in pending_requests:
        req.status = "PENDING"
        req.risk_triggered = False
        req.risk_reason = None
        req.sync_status = "PENDING"

        log_operation(
            db,
            operation_type="RESUME_AFTER_RISK",
            operator="SYSTEM",
            target_type="CHANGE_REQUEST",
            target_id=req.id,
            detail="客户解除冻结，申请恢复审批流程"
        )

    db.flush()
