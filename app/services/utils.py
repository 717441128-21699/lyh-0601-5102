import json
import uuid
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from app.models import OperationLog


def get_date_range(quick_range: str = None, start_date: date = None, end_date: date = None):
    """
    统一日期范围计算口径
    - today: 今天 00:00:00 ~ 今天 23:59:59.999999
    - yesterday: 昨天 00:00:00 ~ 昨天 23:59:59.999999
    - 7d: 最近7天（含今天）: 6天前 00:00:00 ~ 今天 23:59:59.999999
    - 30d: 最近30天（含今天）: 29天前 00:00:00 ~ 今天 23:59:59.999999
    """
    today = date.today()

    if quick_range:
        if quick_range == "today":
            start_dt = datetime.combine(today, datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        elif quick_range == "yesterday":
            yesterday = today - timedelta(days=1)
            start_dt = datetime.combine(yesterday, datetime.min.time())
            end_dt = datetime.combine(yesterday, datetime.max.time())
        elif quick_range == "7d":
            start_dt = datetime.combine(today - timedelta(days=6), datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        elif quick_range == "30d":
            start_dt = datetime.combine(today - timedelta(days=29), datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        else:
            start_dt, end_dt = None, None
    else:
        start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
        end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

    return start_dt, end_dt


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
