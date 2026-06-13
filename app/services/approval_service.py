from datetime import datetime
from sqlalchemy.orm import Session
from app.models import ChangeRequest, Customer
from app.services.utils import log_operation, json_to_dict
from app.services.sync_service import sync_to_systems
from app.services.notification_service import send_notification


def auto_approve_if_applicable(db: Session, change_request: ChangeRequest):
    customer = db.query(Customer).filter(Customer.id == change_request.customer_id).first()

    if customer.customer_level == "NORMAL" and not change_request.risk_triggered:
        change_request.status = "APPROVED"
        change_request.approver = "SYSTEM_AUTO"
        change_request.approval_comment = "普通客户变更，系统自动审批通过"
        change_request.approved_at = datetime.now()
        change_request.sync_status = "PENDING"

        log_operation(
            db,
            operation_type="AUTO_APPROVE",
            operator="SYSTEM",
            target_type="CHANGE_REQUEST",
            target_id=change_request.id,
            detail="系统自动审批通过"
        )

        _apply_changes_to_customer(db, change_request)

        db.flush()

        sync_to_systems(db, change_request)

        send_notification(
            db,
            change_request_id=change_request.id,
            recipient=change_request.submitter,
            notification_type="APPROVAL_NOTICE",
            title="变更申请已自动审批通过",
            content=f"您的变更申请 {change_request.request_no} 已由系统自动审批通过，正在同步至各业务系统。"
        )


def manual_approve(db: Session, request_id: int, approver: str, comment: str = "") -> ChangeRequest:
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法审批")

    if change_request.risk_triggered:
        raise ValueError("该申请触发风控预警，需先处理风控后再审批")

    change_request.status = "APPROVED"
    change_request.approver = approver
    change_request.approval_comment = comment or "人工审批通过"
    change_request.approved_at = datetime.now()
    change_request.sync_status = "PENDING"

    log_operation(
        db,
        operation_type="MANUAL_APPROVE",
        operator=approver,
        target_type="CHANGE_REQUEST",
        target_id=change_request.id,
        detail=f"人工审批通过: {comment}"
    )

    _apply_changes_to_customer(db, change_request)

    db.flush()

    sync_to_systems(db, change_request)

    send_notification(
        db,
        change_request_id=change_request.id,
        recipient=change_request.submitter,
        notification_type="APPROVAL_NOTICE",
        title="变更申请已审批通过",
        content=f"您的变更申请 {change_request.request_no} 已由 {approver} 审批通过，正在同步至各业务系统。"
    )

    db.commit()
    db.refresh(change_request)
    return change_request


def reject_request(db: Session, request_id: int, approver: str, comment: str) -> ChangeRequest:
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法驳回")

    change_request.status = "REJECTED"
    change_request.approver = approver
    change_request.approval_comment = comment
    change_request.approved_at = datetime.now()
    change_request.sync_status = "CANCELLED"

    log_operation(
        db,
        operation_type="REJECT",
        operator=approver,
        target_type="CHANGE_REQUEST",
        target_id=change_request.id,
        detail=f"驳回申请: {comment}"
    )

    send_notification(
        db,
        change_request_id=change_request.id,
        recipient=change_request.submitter,
        notification_type="REJECTION_NOTICE",
        title="变更申请已被驳回",
        content=f"您的变更申请 {change_request.request_no} 已被 {approver} 驳回，原因：{comment}"
    )

    db.commit()
    db.refresh(change_request)
    return change_request


def _apply_changes_to_customer(db: Session, change_request: ChangeRequest):
    customer = db.query(Customer).filter(Customer.id == change_request.customer_id).first()
    if not customer:
        return

    new_data = json_to_dict(change_request.new_data)

    for field, value in new_data.items():
        if hasattr(customer, field) and value is not None:
            setattr(customer, field, value)

    customer.updated_at = datetime.now()
