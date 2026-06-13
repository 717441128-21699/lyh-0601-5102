import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import ChangeRequest, SyncRecord, Customer, Notification
from app.services.utils import dict_to_json, log_operation, json_to_dict
from app.services.notification_service import send_notification

TARGET_SYSTEMS = ["CRM", "ERP", "FINANCE"]


def sync_to_systems(db: Session, change_request: ChangeRequest):
    customer = db.query(Customer).filter(Customer.id == change_request.customer_id).first()

    for system in TARGET_SYSTEMS:
        existing = db.query(SyncRecord).filter(
            and_(
                SyncRecord.change_request_id == change_request.id,
                SyncRecord.target_system == system
            )
        ).first()

        if existing:
            sync_record = existing
            sync_record.status = "PENDING"
            sync_record.retry_count = (sync_record.retry_count or 0)
        else:
            sync_record = SyncRecord(
                change_request_id=change_request.id,
                target_system=system,
                status="PENDING",
                sync_data=change_request.new_data,
                retry_count=0
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

    order_manager = customer.order_manager
    if order_manager:
        notified = False
        if change_request.sync_status in ["SUCCESS", "PARTIAL"]:
            send_notification(
                db,
                change_request_id=change_request.id,
                recipient=order_manager,
                notification_type="SYNC_NOTICE",
                title="客户主数据已更新",
                content=f"客户 {customer.customer_name} 的主数据已变更并同步完成，请关注相关订单。变更单号：{change_request.request_no}"
            )
            change_request.order_manager_notified = True
            notified = True

        log_operation(
            db,
            operation_type="NOTIFY_ORDER_MANAGER",
            operator="SYSTEM",
            target_type="CHANGE_REQUEST",
            target_id=change_request.id,
            detail=f"订单负责人通知: 已发送={notified}, 状态={change_request.sync_status}"
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


def retry_sync(db: Session, sync_record_id: int, operator: str = None) -> SyncRecord:
    """重试单个系统同步"""
    sync_record = db.query(SyncRecord).filter(SyncRecord.id == sync_record_id).first()
    if not sync_record:
        raise ValueError("同步记录不存在")

    change_request = db.query(ChangeRequest).filter(
        ChangeRequest.id == sync_record.change_request_id
    ).first()
    customer = db.query(Customer).filter(
        Customer.id == change_request.customer_id
    ).first()

    sync_record.retry_count = (sync_record.retry_count or 0) + 1
    sync_record.status = "PENDING"
    db.flush()

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
        operator=operator or "SYSTEM",
        target_type="SYNC_RECORD",
        target_id=sync_record.id,
        detail=f"重试同步至{sync_record.target_system}系统: {'成功' if success else '失败'}, 重试次数: {sync_record.retry_count}"
    )

    _update_request_sync_status(db, change_request.id)

    db.commit()
    db.refresh(sync_record)
    return sync_record


def retry_sync_all(db: Session, request_id: int, operator: str = None) -> Dict[str, Any]:
    """重试申请单的所有失败同步"""
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    failed_records = db.query(SyncRecord).filter(
        and_(
            SyncRecord.change_request_id == request_id,
            SyncRecord.status == "FAILED"
        )
    ).all()

    results = []
    for record in failed_records:
        try:
            retried = retry_sync(db, record.id, operator=operator)
            results.append({
                "sync_record_id": record.id,
                "target_system": record.target_system,
                "success": retried.status == "SUCCESS",
                "retry_count": retried.retry_count
            })
        except Exception as e:
            results.append({
                "sync_record_id": record.id,
                "target_system": record.target_system,
                "success": False,
                "error": str(e)
            })

    success_count = sum(1 for r in results if r["success"])
    total_count = len(results)

    return {
        "request_id": request_id,
        "total_retried": total_count,
        "success_count": success_count,
        "fail_count": total_count - success_count,
        "results": results
    }


def get_sync_summary(db: Session, request_id: int) -> Dict[str, Any]:
    """
    获取同步结果汇总
    包含各系统状态、重试次数、通知状态
    """
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    sync_records = db.query(SyncRecord).filter(
        SyncRecord.change_request_id == request_id
    ).all()

    system_status = {}
    total_retry_count = 0
    success_count = 0
    failed_count = 0

    for record in sync_records:
        system_status[record.target_system] = {
            "status": record.status,
            "retry_count": record.retry_count or 0,
            "error_message": record.error_message,
            "synced_at": record.synced_at
        }
        total_retry_count += (record.retry_count or 0)
        if record.status == "SUCCESS":
            success_count += 1
        elif record.status == "FAILED":
            failed_count += 1

    order_manager_notified = change_request.order_manager_notified

    notifications = db.query(Notification).filter(
        and_(
            Notification.change_request_id == request_id,
            Notification.notification_type.in_(["SYNC_NOTICE", "SYNC_COMPLETE"])
        )
    ).all()

    notification_list = []
    for n in notifications:
        notification_list.append({
            "id": n.id,
            "recipient": n.recipient,
            "title": n.title,
            "content": n.content,
            "is_read": n.is_read,
            "is_delivered": n.is_delivered,
            "sent_at": n.sent_at
        })

    return {
        "request_id": request_id,
        "overall_status": change_request.sync_status,
        "system_status": system_status,
        "success_count": success_count,
        "failed_count": failed_count,
        "pending_count": len(system_status) - success_count - failed_count,
        "total_retry_count": total_retry_count,
        "order_manager_notified": order_manager_notified,
        "notifications": notification_list,
        "synced_at": change_request.synced_at
    }


def _update_request_sync_status(db: Session, request_id: int):
    """更新申请单的同步状态"""
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        return

    success_count = db.query(SyncRecord).filter(
        and_(
            SyncRecord.change_request_id == request_id,
            SyncRecord.status == "SUCCESS"
        )
    ).count()

    total_count = db.query(SyncRecord).filter(
        SyncRecord.change_request_id == request_id
    ).count()

    if total_count == 0:
        return

    if success_count == total_count:
        change_request.sync_status = "SUCCESS"
    elif success_count > 0:
        change_request.sync_status = "PARTIAL"
    else:
        all_failed = db.query(SyncRecord).filter(
            and_(
                SyncRecord.change_request_id == request_id,
                SyncRecord.status == "FAILED"
            )
        ).count() == total_count
        if all_failed:
            change_request.sync_status = "FAILED"
        else:
            change_request.sync_status = "PARTIAL"

    change_request.synced_at = datetime.now()
    db.flush()


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

