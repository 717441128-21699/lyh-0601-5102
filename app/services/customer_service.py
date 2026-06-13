from typing import Optional
from sqlalchemy.orm import Session
from app.models import Customer
from app.schemas import CustomerCreate, CustomerUpdate
from app.services.utils import log_operation


def create_customer(db: Session, customer_data: CustomerCreate, operator: str = "SYSTEM") -> Customer:
    existing = db.query(Customer).filter(Customer.customer_code == customer_data.customer_code).first()
    if existing:
        raise ValueError(f"客户编码 {customer_data.customer_code} 已存在")

    customer = Customer(**customer_data.model_dump())
    db.add(customer)
    db.flush()

    log_operation(
        db,
        operation_type="CREATE_CUSTOMER",
        operator=operator,
        target_type="CUSTOMER",
        target_id=customer.id,
        detail=f"创建客户: {customer.customer_name}"
    )

    db.commit()
    db.refresh(customer)
    return customer


def get_customer(db: Session, customer_id: int) -> Optional[Customer]:
    return db.query(Customer).filter(Customer.id == customer_id).first()


def get_customers(db: Session, name: str = None, level: str = None,
                  page: int = 1, page_size: int = 20) -> dict:
    query = db.query(Customer)

    if name:
        query = query.filter(Customer.customer_name.like(f"%{name}%"))

    if level:
        query = query.filter(Customer.customer_level == level)

    total = query.count()
    items = query.order_by(Customer.id.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }


def update_customer(db: Session, customer_id: int, update_data: CustomerUpdate,
                    operator: str) -> Customer:
    customer = get_customer(db, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(customer, key, value)

    log_operation(
        db,
        operation_type="UPDATE_CUSTOMER",
        operator=operator,
        target_type="CUSTOMER",
        target_id=customer.id,
        detail=f"更新客户: {customer.customer_name}, 字段: {list(update_dict.keys())}"
    )

    db.commit()
    db.refresh(customer)
    return customer


def delete_customer(db: Session, customer_id: int, operator: str):
    customer = get_customer(db, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    db.delete(customer)

    log_operation(
        db,
        operation_type="DELETE_CUSTOMER",
        operator=operator,
        target_type="CUSTOMER",
        target_id=customer_id,
        detail=f"删除客户: {customer.customer_name}"
    )

    db.commit()
