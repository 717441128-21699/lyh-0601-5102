from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from app.models import Customer, ChangeRequest
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
from app.services.approval_service import auto_approve_if_applicable


def get_customer_by_code(db: Session, customer_code: str) -> Customer:
    return db.query(Customer).filter(Customer.customer_code == customer_code).first()


def get_change_request_by_no(db: Session, request_no: str) -> ChangeRequest:
    return db.query(ChangeRequest).filter(ChangeRequest.request_no == request_no).first()


def get_change_request_by_id(db: Session, request_id: int) -> ChangeRequest:
    return db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()


def submit_change_request(db: Session, request_data: ChangeRequestCreate) -> ChangeRequest:
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
        approval_level="AUTO" if customer.customer_level == "NORMAL" else "REGIONAL_MANAGER",
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

    if customer.customer_level == "NORMAL" and not change_request.risk_triggered:
        auto_approve_if_applicable(db, change_request)

    db.commit()
    db.refresh(change_request)

    return change_request


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
        query_stmt = query_stmt.filter(ChangeRequest.created_at >= query.start_date)

    if query.end_date:
        query_stmt = query_stmt.filter(ChangeRequest.created_at <= query.end_date)

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


def get_change_count_30d(db: Session, customer_id: int) -> int:
    thirty_days_ago = datetime.now() - timedelta(days=30)
    return db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.created_at >= thirty_days_ago,
            ChangeRequest.status.in_(["APPROVED", "PENDING", "RISK_HOLD"])
        )
    ).count()


def format_change_request_response(change_request: ChangeRequest) -> Dict[str, Any]:
    data = {
        "id": change_request.id,
        "request_no": change_request.request_no,
        "customer_id": change_request.customer_id,
        "customer_code": change_request.customer_code,
        "change_type": change_request.change_type,
        "submitter": change_request.submitter,
        "department": change_request.department,
        "old_data": json_to_dict(change_request.old_data),
        "new_data": json_to_dict(change_request.new_data),
        "diff_data": json_to_dict(change_request.diff_data),
        "status": change_request.status,
        "approval_level": change_request.approval_level,
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
