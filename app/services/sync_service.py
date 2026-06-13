import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import ChangeRequest, SyncRecord, Customer
from app.services.utils import dict_to_json, log_operation, json_to_dict
from app.services.notification_service import send_notification

TARGET_SYSTEMS = ["CRM", "ERP", "FINANCE"]


def sync_to_systems(db: Session, change_request: ChangeRequest):
    customer = db.query(Customer).filter(Customer.id == change_request.customer_id).first()

    for system in TARGET_SYSTEMS:
        sync_record = SyncRecord(
            change_request_id=change_request.id,
            target_system=system,
            status="PENDING",
            sync_data=change_request.new_data
        )
        db.add(sync_record)
        db.flush()

        success, message = _mock_sync(system, customer, json_to_dict(change_request.new_data))

        sync_record.status = "SUCCESS" if success else "FAILED"
        sync_record.response_data = message
        sync_record.error_message = None if success else message
        sync_record.synced_at = datetime.now()

        log_operation(
            db,
            operation_type="SYNC",
            operator="SYSTEM",
            target_type="SYNC_RECORD",
            target_id=sync_record.id,
            detail=f"同步至{system}系统: {'成功' if success else '失败 - ' + message}"
        )

    success_count = db.query(SyncRecord).filter(
        SyncRecord.change_request_id == change_request.id,
        SyncRecord.status == "SUCCESS"
    ).count()

    total_count = len(TARGET_SYSTEMS)

    if success_count == total_count:
        change_request.sync_status = "SUCCESS"
    elif success_count > 0:
        change_request.sync_status = "PARTIAL"
    else:
        change_request.sync_status = "FAILED"

    change_request.synced_at = datetime.now()

    if change_request.sync_status in ["SUCCESS", "PARTIAL"]:
        order_manager = customer.order_manager
        if order_manager:
            send_notification(
                db,
                change_request_id=change_request.id,
                recipient=order_manager,
                notification_type="SYNC_NOTICE",
                title="客户主数据已更新",
                content=f"客户 {customer.customer_name} 的主数据已变更并同步完成，请关注相关订单。变更单号：{change_request.request_no}"
            )

    db.flush()


def _mock_sync(system: str, customer: Customer, data: dict) -> tuple:
    """
    模拟同步到外部系统
    实际项目中应调用各系统的 API
    """
    try:
        sync_data = {
            "customer_code": customer.customer_code,
            "customer_name": data.get("customer_name", customer.customer_name),
            "contact_person": data.get("contact_person", customer.contact_person),
            "contact_phone": data.get("contact_phone", customer.contact_phone),
            "address": data.get("address", customer.address),
            "sync_time": datetime.now().isoformat()
        }

        response = {
            "code": 200,
            "message": f"{system}同步成功",
            "data": {"sync_id": f"{system}_{customer.customer_code}_{int(datetime.now().timestamp())}"}
        }
        return True, json.dumps(response, ensure_ascii=False)
    except Exception as e:
        return False, str(e)


def retry_sync(db: Session, sync_record_id: int) -> SyncRecord:
    sync_record = db.query(SyncRecord).filter(SyncRecord.id == sync_record_id).first()
    if not sync_record:
        raise ValueError("同步记录不存在")

    change_request = db.query(ChangeRequest).filter(
        ChangeRequest.id == sync_record.change_request_id
    ).first()
    customer = db.query(Customer).filter(
        Customer.id == change_request.customer_id
    ).first()

    sync_record.retry_count += 1
    success, message = _mock_sync(
        sync_record.target_system,
        customer,
        json_to_dict(sync_record.sync_data)
    )

    sync_record.status = "SUCCESS" if success else "FAILED"
    sync_record.response_data = message
    sync_record.error_message = None if success else message
    sync_record.synced_at = datetime.now()

    log_operation(
        db,
        operation_type="RETRY_SYNC",
        operator="SYSTEM",
        target_type="SYNC_RECORD",
        target_id=sync_record.id,
        detail=f"重试同步至{sync_record.target_system}系统: {'成功' if success else '失败'}"
    )

    db.commit()
    db.refresh(sync_record)
    return sync_record


def get_sync_records(db: Session, change_request_id: int = None, status: str = None,
                     page: int = 1, page_size: int = 20) -> dict:
    query = db.query(SyncRecord)

    if change_request_id:
        query = query.filter(SyncRecord.change_request_id == change_request_id)

    if status:
        query = query.filter(SyncRecord.status == status)

    total = query.count()
    items = query.order_by(SyncRecord.id.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }
