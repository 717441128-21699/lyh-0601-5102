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
    log_operation,
    get_date_range
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
    risk_triggered = risk_result["triggered"]
    risk_frozen = risk_result["frozen"]
    risk_reason = risk_result.get("reason", "")

    if risk_frozen:
        change_request.risk_triggered = True
        change_request.risk_reason = risk_reason
        change_request.status = "RISK_HOLD"
        change_request.sync_status = "BLOCKED"
        db.flush()

        db.commit()
        db.refresh(change_request)

        return {
            "request": format_change_request_response(change_request),
            "risk_triggered": True,
            "risk_frozen": True,
            "risk_reason": risk_reason,
            "risk_info": {
                "change_count_30d": risk_result.get("change_count", 3),
                "risk_threshold": risk_result.get("threshold"),
                "status": risk_result.get("customer_risk_status"),
                "remaining_changes": risk_result.get("remaining_changes"),
                "is_frozen": True
            },
            "approval_flow": None
        }
    elif risk_triggered:
        change_request.risk_triggered = True
        change_request.risk_reason = risk_reason
        db.flush()

    approval_result = init_approval_flow(db, change_request, customer, len(diff_fields))

    if not approval_result["success"]:
        db.rollback()
        raise ValueError(approval_result["message"])

    if approval_result.get("auto_approved"):
        from app.services.sync_service import sync_to_systems
        from app.services.notification_service import send_notification

        sync_result = sync_to_systems(db, change_request)

        old_customer_data = json_to_dict(change_request.old_data)
        new_data = json_to_dict(change_request.new_data)
        for field, new_value in new_data.items():
            if hasattr(customer, field):
                old_value = getattr(customer, field)
                if old_value != new_value:
                    setattr(customer, field, new_value)

        order_manager = getattr(customer, "order_manager") or ""
        if order_manager:
            send_notification(
                db,
                change_request_id=change_request.id,
                recipient=order_manager,
                notification_type="SYNC_COMPLETE",
                title="客户主数据同步完成",
                content=f"客户 {customer.customer_name} 的变更申请 {change_request.request_no} 已完成所有系统同步。"
            )

    db.commit()
    db.refresh(change_request)

    return {
        "request": format_change_request_response(change_request),
        "risk_triggered": risk_triggered,
        "risk_frozen": False,
        "risk_info": {
            "change_count_30d": risk_result.get("change_count", 0),
            "risk_threshold": risk_result.get("threshold"),
            "status": risk_result.get("customer_risk_status"),
            "remaining_changes": risk_result.get("remaining_changes"),
            "is_frozen": False
        } if risk_triggered else None,
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


def query_change_requests(db: Session, query: ChangeRequestQuery,
                          quick_range: str = None) -> Dict[str, Any]:
    query_stmt = db.query(ChangeRequest)

    if query.customer_name:
        query_stmt = query_stmt.filter(
            ChangeRequest.customer_code.in_(
                db.query(Customer.customer_code).filter(
                    Customer.customer_name.like(f"%{query.customer_name}%")
                )
            )
        )

    start_dt, end_dt = get_date_range(
        quick_range=quick_range,
        start_date=query.start_date,
        end_date=query.end_date
    )
    if start_dt:
        query_stmt = query_stmt.filter(ChangeRequest.created_at >= start_dt)
    if end_dt:
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
    与 query_change_requests 使用同一套日期口径
    """
    query_obj = ChangeRequestQuery(
        customer_name=customer_name,
        start_date=None,
        end_date=None,
        status=status,
        department=department,
        page=page,
        page_size=page_size
    )

    return query_change_requests(db, query_obj, quick_range=quick_range)


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
    """客户解除风控冻结后，重新激活其待审批申请，完整恢复审批链和待办"""
    from app.services.approval_service import (
        init_approval_flow, get_approval_records,
        _send_approval_notification
    )
    from app.services.approval_rule_service import get_next_approver

    pending_requests = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.status == "RISK_HOLD"
        )
    ).all()

    customer = db.query(Customer).filter(Customer.id == customer_id).first()

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

        if req.approval_chain_id is None:
            old_data = json_to_dict(req.old_data)
            new_data = json_to_dict(req.new_data)
            diff_fields = []
            for field, new_val in new_data.items():
                old_val = old_data.get(field)
                if old_val != new_val:
                    diff_fields.append({
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val
                    })

            if customer:
                init_result = init_approval_flow(db, req, customer, len(diff_fields))
                if init_result["success"] and init_result.get("auto_approved"):
                    from app.services.sync_service import sync_to_systems
                    from app.services.notification_service import send_notification

                    sync_to_systems(db, req)

                    new_values = json_to_dict(req.new_data)
                    for field, new_value in new_values.items():
                        if hasattr(customer, field):
                            old_value = getattr(customer, field)
                            if old_value != new_value:
                                setattr(customer, field, new_value)

                    order_manager = getattr(customer, "order_manager") or ""
                    if order_manager:
                        send_notification(
                            db,
                            change_request_id=req.id,
                            recipient=order_manager,
                            notification_type="SYNC_COMPLETE",
                            title="客户主数据同步完成",
                            content=f"客户 {customer.customer_name} 的变更申请 {req.request_no} 已完成所有系统同步。"
                        )
        else:
            current_index = req.current_node_index
            chain = req.approval_chain

            if chain and current_index < len(chain.nodes):
                existing_record = db.query(ApprovalRecord).filter(
                    and_(
                        ApprovalRecord.change_request_id == req.id,
                        ApprovalRecord.node_order == current_index
                    )
                ).first()

                if not existing_record:
                    next_node_info = get_next_approver(chain, current_index)
                    new_record = ApprovalRecord(
                        change_request_id=req.id,
                        node_id=next_node_info.get("node_id"),
                        node_name=next_node_info.get("node_name", "待审批"),
                        node_order=current_index,
                        approver_role=next_node_info.get("approver_role"),
                        approver=next_node_info.get("approver"),
                        action="PENDING"
                    )
                    db.add(new_record)

                    next_node_info = get_next_approver(chain, current_index)
                    if next_node_info["has_next"]:
                        _send_approval_notification(
                            db,
                            change_request=req,
                            node_info=next_node_info,
                            notification_type="APPROVAL_TODO",
                            title="您有新的待审批申请（风控解除后恢复）",
                            content=f"客户风控已解除，变更申请 {req.request_no} 恢复审批流程，请及时处理。"
                        )

    db.flush()
