import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.models import (
    RiskCase, RiskWarning, Customer, ChangeRequest,
    ApprovalRecord, OperationLog
)
from app.services.utils import log_operation, json_to_dict, dict_to_json


def generate_case_no() -> str:
    """生成风控案件编号"""
    timestamp = datetime.now().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"RISK-{timestamp}-{suffix}"


def create_risk_case(db: Session, customer: Customer, risk_type: str, risk_level: str,
                     description: str, matched_rule_name: str = None,
                     match_reason: str = None, related_warning_id: int = None,
                     related_change_request_ids: List[int] = None,
                     freeze_reason: str = None) -> RiskCase:
    """创建风控案件"""
    case = RiskCase(
        case_no=generate_case_no(),
        customer_id=customer.id,
        customer_code=customer.customer_code,
        risk_type=risk_type,
        risk_level=risk_level,
        description=description,
        related_warning_id=related_warning_id,
        related_change_request_ids=dict_to_json(related_change_request_ids) if related_change_request_ids else None,
        matched_rule_name=matched_rule_name,
        match_reason=match_reason,
        freeze_reason=freeze_reason
    )
    db.add(case)
    db.flush()

    log_operation(
        db,
        operation_type="CREATE_RISK_CASE",
        operator="SYSTEM",
        target_type="RISK_CASE",
        target_id=case.id,
        detail=f"创建风控案件: {case.case_no}, 类型: {risk_type}, 级别: {risk_level}"
    )

    return case


def update_risk_case_status(db: Session, case_id: int, status: str,
                            handler: str = None, comment: str = None,
                            unfreeze_reason: str = None) -> RiskCase:
    """更新风控案件状态"""
    case = db.query(RiskCase).filter(RiskCase.id == case_id).first()
    if not case:
        raise ValueError("风控案件不存在")

    case.status = status
    case.handler = handler or case.handler
    case.handled_at = datetime.now()
    if unfreeze_reason:
        case.unfreeze_reason = unfreeze_reason

    log_operation(
        db,
        operation_type="UPDATE_RISK_CASE",
        operator=handler or "SYSTEM",
        target_type="RISK_CASE",
        target_id=case_id,
        detail=f"更新风控案件状态: {status}, 备注: {comment or '无'}"
    )

    return case


def get_risk_workbench_summary(db: Session, handler: str = None) -> Dict[str, Any]:
    """获取风控工作台汇总数据"""
    now = datetime.now()
    thirty_days_ago = now - timedelta(days=30)

    warning_count = db.query(RiskWarning).filter(
        and_(
            RiskWarning.is_handled == False,
            RiskWarning.warning_level.in_(["MEDIUM", "WARNING"])
        )
    ).count()

    frozen_count = db.query(Customer).filter(Customer.is_frozen == True).count()

    open_case_count = db.query(RiskCase).filter(RiskCase.status == "OPEN").count()
    processing_case_count = db.query(RiskCase).filter(RiskCase.status == "PROCESSING").count()
    closed_case_count = db.query(RiskCase).filter(
        RiskCase.status.in_(["RESOLVED", "CLOSED"])
    ).count()

    recovered_count = db.query(RiskCase).filter(
        and_(
            RiskCase.status == "RESOLVED",
            RiskCase.updated_at >= thirty_days_ago
        )
    ).count()

    return {
        "warning_customers": warning_count,
        "frozen_customers": frozen_count,
        "open_cases": open_case_count,
        "processing_cases": processing_case_count,
        "closed_cases": closed_case_count,
        "recovered_last_30d": recovered_count
    }


def get_warning_customers(db: Session, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """获取预警中的客户列表"""
    warning_customer_ids = db.query(RiskWarning.customer_id).filter(
        and_(
            RiskWarning.is_handled == False,
            RiskWarning.warning_level.in_(["MEDIUM", "WARNING"])
        )
    ).distinct().all()
    warning_customer_ids = [id[0] for id in warning_customer_ids]

    query = db.query(Customer).filter(Customer.id.in_(warning_customer_ids))
    total = query.count()

    customers = query.order_by(Customer.updated_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    result = []
    for customer in customers:
        warnings = db.query(RiskWarning).filter(
            and_(
                RiskWarning.customer_id == customer.id,
                RiskWarning.is_handled == False
            )
        ).order_by(RiskWarning.created_at.desc()).all()

        related_requests = db.query(ChangeRequest).filter(
            and_(
                ChangeRequest.customer_id == customer.id,
                ChangeRequest.risk_triggered == True
            )
        ).order_by(ChangeRequest.created_at.desc()).limit(5).all()

        cases = db.query(RiskCase).filter(
            RiskCase.customer_id == customer.id
        ).order_by(RiskCase.created_at.desc()).limit(3).all()

        result.append({
            "customer": {
                "id": customer.id,
                "customer_code": customer.customer_code,
                "customer_name": customer.customer_name,
                "customer_level": customer.customer_level,
                "industry": customer.industry,
                "department": customer.department,
                "is_frozen": customer.is_frozen
            },
            "warnings": [
                {
                    "id": w.id,
                    "warning_type": w.warning_type,
                    "warning_level": w.warning_level,
                    "description": w.description,
                    "change_count_30d": w.change_count_30d,
                    "created_at": w.created_at
                }
                for w in warnings
            ],
            "related_requests": [
                {
                    "id": r.id,
                    "request_no": r.request_no,
                    "change_type": r.change_type,
                    "status": r.status,
                    "risk_reason": r.risk_reason,
                    "created_at": r.created_at
                }
                for r in related_requests
            ],
            "cases": [
                {
                    "id": c.id,
                    "case_no": c.case_no,
                    "risk_type": c.risk_type,
                    "risk_level": c.risk_level,
                    "status": c.status,
                    "matched_rule_name": c.matched_rule_name,
                    "created_at": c.created_at
                }
                for c in cases
            ]
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result
    }


def get_frozen_customers(db: Session, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """获取已冻结客户列表"""
    query = db.query(Customer).filter(Customer.is_frozen == True)
    total = query.count()

    customers = query.order_by(Customer.updated_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    result = []
    for customer in customers:
        warnings = db.query(RiskWarning).filter(
            RiskWarning.customer_id == customer.id
        ).order_by(RiskWarning.created_at.desc()).limit(5).all()

        cases = db.query(RiskCase).filter(
            and_(
                RiskCase.customer_id == customer.id,
                RiskCase.status.in_(["OPEN", "PROCESSING"])
            )
        ).order_by(RiskCase.created_at.desc()).all()

        pending_requests = db.query(ChangeRequest).filter(
            and_(
                ChangeRequest.customer_id == customer.id,
                ChangeRequest.status.in_(["RISK_HOLD", "PENDING"])
            )
        ).order_by(ChangeRequest.created_at.desc()).all()

        result.append({
            "customer": {
                "id": customer.id,
                "customer_code": customer.customer_code,
                "customer_name": customer.customer_name,
                "customer_level": customer.customer_level,
                "industry": customer.industry,
                "department": customer.department,
                "freeze_reason": customer.freeze_reason,
                "is_frozen": customer.is_frozen
            },
            "warnings": [
                {
                    "id": w.id,
                    "warning_type": w.warning_type,
                    "warning_level": w.warning_level,
                    "description": w.description,
                    "change_count_30d": w.change_count_30d,
                    "created_at": w.created_at
                }
                for w in warnings
            ],
            "cases": [
                {
                    "id": c.id,
                    "case_no": c.case_no,
                    "risk_type": c.risk_type,
                    "risk_level": c.risk_level,
                    "status": c.status,
                    "matched_rule_name": c.matched_rule_name,
                    "match_reason": c.match_reason,
                    "freeze_reason": c.freeze_reason,
                    "created_at": c.created_at
                }
                for c in cases
            ],
            "pending_requests": [
                {
                    "id": r.id,
                    "request_no": r.request_no,
                    "change_type": r.change_type,
                    "status": r.status,
                    "risk_reason": r.risk_reason,
                    "created_at": r.created_at
                }
                for r in pending_requests
            ]
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result
    }


def get_recovery_records(db: Session, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """获取人工解除后的恢复记录"""
    query = db.query(RiskCase).filter(
        RiskCase.status.in_(["RESOLVED", "CLOSED"])
    ).order_by(RiskCase.updated_at.desc())

    total = query.count()
    cases = query.offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for case in cases:
        customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
        if not customer:
            continue

        related_request_ids = json_to_dict(case.related_change_request_ids) if case.related_change_request_ids else []
        related_requests = []
        if related_request_ids:
            related_requests = db.query(ChangeRequest).filter(
                ChangeRequest.id.in_(related_request_ids)
            ).order_by(ChangeRequest.created_at.desc()).all()

        operation_logs = db.query(OperationLog).filter(
            and_(
                OperationLog.target_type == "CUSTOMER",
                OperationLog.target_id == customer.id,
                OperationLog.operation_type.in_(["UNFREEZE", "RISK_UNFREEZE"])
            )
        ).order_by(OperationLog.created_at.desc()).limit(5).all()

        result.append({
            "case": {
                "id": case.id,
                "case_no": case.case_no,
                "risk_type": case.risk_type,
                "risk_level": case.risk_level,
                "status": case.status,
                "matched_rule_name": case.matched_rule_name,
                "match_reason": case.match_reason,
                "freeze_reason": case.freeze_reason,
                "unfreeze_reason": case.unfreeze_reason,
                "handler": case.handler,
                "handled_at": case.handled_at,
                "created_at": case.created_at,
                "updated_at": case.updated_at
            },
            "customer": {
                "id": customer.id,
                "customer_code": customer.customer_code,
                "customer_name": customer.customer_name,
                "customer_level": customer.customer_level,
                "is_frozen": customer.is_frozen
            },
            "related_requests": [
                {
                    "id": r.id,
                    "request_no": r.request_no,
                    "change_type": r.change_type,
                    "status": r.status,
                    "approval_level": r.approval_level,
                    "created_at": r.created_at
                }
                for r in related_requests
            ],
            "operation_logs": [
                {
                    "id": log.id,
                    "operation_type": log.operation_type,
                    "operator": log.operator,
                    "detail": log.detail,
                    "created_at": log.created_at
                }
                for log in operation_logs
            ]
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result
    }


def get_risk_trace(db: Session, customer_id: int = None, customer_code: str = None,
                   change_request_id: int = None) -> Dict[str, Any]:
    """
    获取风控追踪详情：查看每次变更命中了哪条规则、为什么只是提示或为什么被拦住
    可以按客户、客户编码、或变更申请ID查询
    """
    if change_request_id:
        change_request = db.query(ChangeRequest).filter(
            ChangeRequest.id == change_request_id
        ).first()
        if not change_request:
            raise ValueError("变更申请不存在")
        customer = change_request.customer
    elif customer_id:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise ValueError("客户不存在")
    elif customer_code:
        customer = db.query(Customer).filter(Customer.customer_code == customer_code).first()
        if not customer:
            raise ValueError("客户不存在")
    else:
        raise ValueError("必须指定查询条件")

    change_requests = db.query(ChangeRequest).filter(
        ChangeRequest.customer_id == customer.id
    ).order_by(ChangeRequest.created_at.desc()).all()

    change_details = []
    for cr in change_requests:
        risk_info = {
            "risk_triggered": cr.risk_triggered,
            "risk_reason": cr.risk_reason,
            "matched_rule_id": cr.matched_rule_id,
            "matched_rule_name": cr.matched_rule_name,
        }

        approval_records = db.query(ApprovalRecord).filter(
            ApprovalRecord.change_request_id == cr.id
        ).order_by(ApprovalRecord.node_order).all()

        approval_flow = []
        for record in approval_records:
            approval_flow.append({
                "node_name": record.node_name,
                "node_order": record.node_order,
                "approver_role": record.approver_role,
                "approver": record.approver,
                "assignee": record.assignee,
                "action": record.action,
                "comment": record.comment,
                "approved_at": record.approved_at,
                "is_overdue": record.is_overdue
            })

        change_details.append({
            "request_id": cr.id,
            "request_no": cr.request_no,
            "change_type": cr.change_type,
            "status": cr.status,
            "created_at": cr.created_at,
            "risk_info": risk_info,
            "approval_flow": approval_flow,
            "sync_status": cr.sync_status
        })

    warnings = db.query(RiskWarning).filter(
        RiskWarning.customer_id == customer.id
    ).order_by(RiskWarning.created_at.desc()).all()

    warning_list = []
    for w in warnings:
        warning_list.append({
            "id": w.id,
            "warning_type": w.warning_type,
            "warning_level": w.warning_level,
            "description": w.description,
            "change_count_30d": w.change_count_30d,
            "is_handled": w.is_handled,
            "handled_by": w.handled_by,
            "handle_comment": w.handle_comment,
            "created_at": w.created_at
        })

    cases = db.query(RiskCase).filter(
        RiskCase.customer_id == customer.id
    ).order_by(RiskCase.created_at.desc()).all()

    case_list = []
    for c in cases:
        case_list.append({
            "id": c.id,
            "case_no": c.case_no,
            "risk_type": c.risk_type,
            "risk_level": c.risk_level,
            "status": c.status,
            "description": c.description,
            "matched_rule_name": c.matched_rule_name,
            "match_reason": c.match_reason,
            "freeze_reason": c.freeze_reason,
            "unfreeze_reason": c.unfreeze_reason,
            "handler": c.handler,
            "handled_at": c.handled_at,
            "created_at": c.created_at
        })

    return {
        "customer": {
            "id": customer.id,
            "customer_code": customer.customer_code,
            "customer_name": customer.customer_name,
            "customer_level": customer.customer_level,
            "is_frozen": customer.is_frozen,
            "freeze_reason": customer.freeze_reason
        },
        "change_history": change_details,
        "risk_warnings": warning_list,
        "risk_cases": case_list
    }


def mark_warning_handled(db: Session, warning_id: int, handler: str,
                         comment: str = None) -> RiskWarning:
    """标记预警为已处理"""
    warning = db.query(RiskWarning).filter(RiskWarning.id == warning_id).first()
    if not warning:
        raise ValueError("风控预警不存在")

    warning.is_handled = True
    warning.handled_by = handler
    warning.handle_comment = comment
    warning.handled_at = datetime.now()

    log_operation(
        db,
        operation_type="HANDLE_RISK_WARNING",
        operator=handler,
        target_type="RISK_WARNING",
        target_id=warning_id,
        detail=f"标记预警为已处理: {comment or '无'}"
    )

    return warning


def get_rule_hit_reason(customer: Customer, change_count: int,
                        threshold: int) -> Dict[str, Any]:
    """
    分析风控规则命中原因，返回规则名称和详细原因
    """
    if change_count <= threshold:
        return {
            "matched": False,
            "rule_name": None,
            "reason": "变更次数未超过阈值"
        }

    if change_count == threshold + 1:
        return {
            "matched": True,
            "rule_name": "频繁变更预警规则",
            "rule_code": "RISK-001-WARNING",
            "level": "WARNING",
            "action": "预警不拦截",
            "reason": f"30天内变更{change_count}次，已达预警阈值{threshold}次，触发预警但不拦截，申请正常流转。"
        }
    else:
        return {
            "matched": True,
            "rule_name": "频繁变更冻结规则",
            "rule_code": "RISK-001-FREEZE",
            "level": "DANGER",
            "action": "冻结拦截",
            "reason": f"30天内变更{change_count}次，超过阈值{threshold}次，触发冻结拦截，申请将被挂起，需人工解除后方可继续。"
        }
