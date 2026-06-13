from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Customer, ChangeRequest, RiskWarning
from app.services.utils import log_operation


def check_risk_and_freeze(db: Session, customer_id: int) -> dict:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return {"triggered": False, "reason": ""}

    thirty_days_ago = datetime.now() - timedelta(days=30)
    change_count = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.customer_id == customer_id,
            ChangeRequest.created_at >= thirty_days_ago,
            ChangeRequest.status.in_(["APPROVED", "PENDING"])
        )
    ).count()

    if change_count >= 3:
        if not customer.is_frozen:
            customer.is_frozen = True
            customer.freeze_reason = f"30天内变更次数达到{change_count}次，触发风控冻结"

            warning = RiskWarning(
                customer_id=customer.id,
                customer_code=customer.customer_code,
                warning_type="FREQUENT_CHANGE",
                warning_level="HIGH",
                description=f"客户 {customer.customer_name} 30天内变更{change_count}次，超过阈值，已冻结同步",
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
                detail=f"触发风控预警，30天变更{change_count}次，客户已冻结"
            )

        return {
            "triggered": True,
            "reason": f"30天内变更{change_count}次，触发风控预警，已冻结同步"
        }

    return {"triggered": False, "reason": ""}


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
