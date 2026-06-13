import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import OperationLog


def generate_request_no():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = str(uuid.uuid4().hex[:8]).upper()
    return f"CR{timestamp}{suffix}"


def dict_to_json(data) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, default=str)


def json_to_dict(data: str):
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    return json.loads(data)


def log_operation(
    db: Session,
    operation_type: str,
    operator: str,
    target_type: str,
    target_id: int = None,
    detail: str = "",
    ip_address: str = ""
):
    log = OperationLog(
        operation_type=operation_type,
        operator=operator,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address
    )
    db.add(log)
    db.flush()
    return log


def calculate_diff(old_data: dict, new_data: dict) -> list:
    diff_fields = []
    for key in new_data:
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if old_val != new_val:
            diff_fields.append({
                "field": key,
                "old_value": old_val,
                "new_value": new_val
            })
    return diff_fields


def customer_to_dict(customer) -> dict:
    return {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "customer_level": customer.customer_level,
        "contact_person": customer.contact_person,
        "contact_phone": customer.contact_phone,
        "contact_email": customer.contact_email,
        "address": customer.address,
        "industry": customer.industry,
        "department": customer.department,
        "order_manager": customer.order_manager
    }
