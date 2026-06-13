from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Customer, ChangeRequest, RiskWarning
from app.services.utils import log_operation

RISK_THRESHOLD = 3


def check_risk_and_freeze(db: Session, customer_id: int,
                           threshold: int = RISK_THRESHOLD) -> dict:
    """
    检查风控规则，超过阈值才冻结
    默认阈值3次：即第4次提交时触发冻结
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return {"triggered": False, "reason": "", "change_count": 0}

    thirty_days_ago = datetime.now() - timedelta(days=30)
    change_count = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.created_at >= thirty_days_ago,
            ChangeRequest.status.in_(["APPROVED", "PENDING", "RISK_HOLD"])
        )
    ).count()

    remaining = threshold - change_count

    if change_count > threshold:
        if not customer.is_frozen:
            customer.is_frozen = True
            customer.freeze_reason = f"30天内变更次数达到{change_count}次，超过阈值{threshold}次，触发风控冻结"

            warning = RiskWarning(
                customer_id=customer.id,
                customer_code=customer.customer_code,
                warning_type="FREQUENT_CHANGE",
                warning_level="HIGH",
                description=f"客户 {customer.customer_name} 30天内变更{change_count}次，超过阈值{threshold}次，已冻结同步",
                change_count_30d=change_count
            )
            db.add(warning)
            db.flush()

            log_operation(
                db,
                operation_type="RISK_FREEZE",
                operator="SYSTEM",
                target_type="CUSTOMER",
                target_id=customer.id,
                detail=f"触发风控预警，30天变更{change_count}次，超过阈值{threshold}次，客户已冻结"
            )

        return {
            "triggered": True,
            "frozen": True,
            "reason": f"30天内变更{change_count}次，超过阈值{threshold}次，触发风控冻结",
            "change_count": change_count,
            "threshold": threshold,
            "customer_risk_status": "frozen",
            "remaining_changes": 0
        }
    elif change_count >= threshold:
        warning = RiskWarning(
            customer_id=customer.id,
            customer_code=customer.customer_code,
            warning_type="FREQUENT_CHANGE_WARNING",
            warning_level="MEDIUM",
            description=f"客户 {customer.customer_name} 30天内变更{change_count}次，已达阈值{threshold}次，请注意关注",
            change_count_30d=change_count
        )
        db.add(warning)
        db.flush()

        return {
            "triggered": True,
            "frozen": False,
            "reason": f"30天内变更{change_count}次，已达阈值{threshold}次，请注意风控",
            "change_count": change_count,
            "threshold": threshold,
            "remaining_changes": 0,
            "customer_risk_status": "warning"
        }
    else:
        return {
            "triggered": False,
            "frozen": False,
            "reason": "",
            "change_count": change_count,
            "threshold": threshold,
            "remaining_changes": remaining,
            "customer_risk_status": "normal"
        }


def get_risk_warnings(db: Session, customer_id: int = None, is_handled: bool = None,
                     page: int = 1, page_size: int = 20) -> dict:
    query = db.query(RiskWarning)

    if customer_id:
        query = query.filter(RiskWarning.customer_id == customer_id)

    if is_handled is not None:
        query = query.filter(RiskWarning.is_handled == is_handled)

    total = query.count()
    items = query.order_by(RiskWarning.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }


def handle_risk_warning(db: Session, warning_id: int, handler: str, comment: str,
                     unfreeze: bool = False) -> RiskWarning:
    warning = db.query(RiskWarning).filter(RiskWarning.id == warning_id).first()
    if not warning:
        raise ValueError("风控预警不存在")

    warning.is_handled = True
    warning.handled_by = handler
    warning.handle_comment = comment
    warning.handled_at = datetime.now()

    if unfreeze:
        customer = db.query(Customer).filter(Customer.id == warning.customer_id).first()
        if customer:
            customer.is_frozen = False
            customer.freeze_reason = None

            log_operation(
                db,
                operation_type="UNFREEZE_CUSTOMER",
                operator=handler,
                target_type="CUSTOMER",
                target_id=customer.id,
                detail=f"解除客户冻结，原因: {comment}"
            )

            from app.services.change_request_service import continue_after_risk_unfreeze
            continue_after_risk_unfreeze(db, customer.id)

            db.flush()

    log_operation(
        db,
        operation_type="HANDLE_RISK",
        operator=handler,
        target_type="RISK_WARNING",
        target_id=warning.id,
        detail=f"处理风控预警: {comment}"
    )

    db.commit()
    db.refresh(warning)
    return warning


def get_customer_risk_status(db: Session, customer_id: int) -> dict:
    """获取客户的风控状态"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise ValueError("客户不存在")

    thirty_days_ago = datetime.now() - timedelta(days=30)
    change_count = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.created_at >= thirty_days_ago,
            ChangeRequest.status.in_(["APPROVED", "PENDING", "RISK_HOLD"])
        )
    ).count()

    active_warnings = db.query(RiskWarning).filter(
        and_(
            RiskWarning.customer_id == customer_id,
            RiskWarning.is_handled == False
        )
    ).count()

    remaining = max(0, RISK_THRESHOLD - change_count)

    return {
        "customer_id": customer_id,
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "is_frozen": customer.is_frozen,
        "freeze_reason": customer.freeze_reason,
        "change_count_30d": change_count,
        "risk_threshold": RISK_THRESHOLD,
        "remaining_changes": remaining,
        "active_warnings": active_warnings,
        "status": "frozen" if customer.is_frozen else ("warning" if change_count >= RISK_THRESHOLD else "normal")
    }
