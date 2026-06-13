from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models import ChangeRequest, Customer, ApprovalRecord, ApprovalNode
from app.services.utils import log_operation, json_to_dict, dict_to_json
from app.services.sync_service import sync_to_systems
from app.services.notification_service import send_notification
from app.services import approval_rule_service, assignment_service


def _send_approval_notification(db: Session, change_request: ChangeRequest,
                               node_info: Dict, notification_type: str,
                               title: str, content: str,
                               assignee: str = None) -> bool:
    """
    发送审批相关通知，优先发给具体指派人，否则用角色/部门格式
    返回: 是否成功发送
    """
    approver = node_info.get("approver", "")
    approver_role = node_info.get("approver_role", "")
    department = node_info.get("department", "")

    if assignee and assignee.strip():
        recipient = assignee
    elif approver and approver.strip():
        recipient = approver
    elif approver_role and department:
        recipient = f"@{department}_{approver_role}"
    elif approver_role:
        recipient = f"@ROLE_{approver_role}"
    elif department:
        recipient = f"@DEPT_{department}"
    else:
        return False

    send_notification(
        db,
        change_request_id=change_request.id,
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        content=content
    )
    return True


def _setup_candidates_and_assignment(db: Session, change_request: ChangeRequest,
                                     node_info: Dict, approval_record: ApprovalRecord):
    """
    设置候选处理人并尝试自动指派
    """
    role = node_info.get("approver_role")
    department = node_info.get("department") or change_request.department

    candidates = assignment_service.get_candidate_users(db, role=role, department=department)
    approval_record.candidate_users = dict_to_json(candidates)

    if candidates:
        assignee = assignment_service.auto_assign(db, change_request, node_info)
        if assignee:
            approval_record.assignee = assignee
            approval_record.assignment_type = "AUTO"
            return assignee

    return None


def init_approval_flow(db: Session, change_request: ChangeRequest, customer: Customer,
                       diff_fields_count: int) -> Dict[str, Any]:
    """
    初始化审批流程：匹配规则、创建初始审批记录、判断是否自动审批、自动指派处理人
    """
    match_result = approval_rule_service.match_approval_rule(
        db, customer, change_request.change_type,
        change_request.department, diff_fields_count
    )

    if not match_result["matched"]:
        return {
            "success": False,
            "message": match_result["match_reason"]
        }

    chain = match_result["chain"]
    rule = match_result.get("rule")
    change_request.approval_chain_id = chain.id
    change_request.current_node_index = 0
    change_request.approval_level = chain.chain_name
    if rule:
        change_request.matched_rule_id = rule.id
        change_request.matched_rule_name = rule.rule_name

    first_node_info = approval_rule_service.get_next_approver(chain, 0)

    first_record = ApprovalRecord(
        change_request_id=change_request.id,
        node_id=first_node_info.get("node_id"),
        node_name=first_node_info.get("node_name", "待审批"),
        node_order=0,
        approver_role=first_node_info.get("approver_role"),
        approver=first_node_info.get("approver"),
        action="PENDING"
    )
    db.add(first_record)
    db.flush()

    if not first_node_info["has_next"]:
        change_request.status = "APPROVED"
        change_request.approved_at = datetime.now()
        auto_approved = True
    else:
        auto_approved = False
        assignee = _setup_candidates_and_assignment(db, change_request, first_node_info, first_record)
        _send_approval_notification(
            db,
            change_request=change_request,
            node_info=first_node_info,
            notification_type="APPROVAL_TODO",
            title="您有新的待审批申请",
            content=f"变更申请 {change_request.request_no} 已提交，请及时处理。",
            assignee=assignee
        )

    db.flush()

    return {
        "success": True,
        "matched_rule": match_result["rule_name"],
        "matched_rule_id": rule.id if rule else None,
        "match_reason": match_result["match_reason"],
        "chain_name": chain.chain_name,
        "total_nodes": len(chain.nodes),
        "current_node_index": 0,
        "next_approver": first_node_info,
        "auto_approved": auto_approved,
        "assignee": first_record.assignee,
        "candidate_users": json_to_dict(first_record.candidate_users) if first_record.candidate_users else []
    }


def approve_request(db: Session, request_id: int, approver: str,
                    comment: str = "") -> ChangeRequest:
    """审批通过（当前节点）"""
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法审批")

    current_index = change_request.current_node_index
    chain = change_request.approval_chain

    if not chain or current_index >= len(chain.nodes):
        raise ValueError("审批链配置异常")

    current_node = chain.nodes[current_index]

    now = datetime.now()
    node_start_time = change_request.created_at
    if current_index > 0:
        prev_record = db.query(ApprovalRecord).filter(
            and_(
                ApprovalRecord.change_request_id == request_id,
                ApprovalRecord.node_order == current_index - 1
            )
        ).first()
        if prev_record and prev_record.approved_at:
            node_start_time = prev_record.approved_at

    is_overdue = False
    if current_node.timeout_hours and node_start_time:
        delta_hours = (now - node_start_time).total_seconds() / 3600
        is_overdue = delta_hours > current_node.timeout_hours

    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == request_id,
            ApprovalRecord.node_order == current_index
        )
    ).first()

    if current_record:
        current_record.approver = approver
        current_record.action = "APPROVED"
        current_record.comment = comment
        current_record.approved_at = now
        current_record.is_overdue = is_overdue

    next_index = current_index + 1
    next_node_info = approval_rule_service.get_next_approver(chain, next_index)

    if next_node_info["has_next"]:
        change_request.current_node_index = next_index

        next_record = ApprovalRecord(
            change_request_id=request_id,
            node_id=next_node_info.get("node_id"),
            node_name=next_node_info.get("node_name"),
            node_order=next_index,
            approver_role=next_node_info.get("approver_role"),
            approver=next_node_info.get("approver"),
            action="PENDING"
        )
        db.add(next_record)
        db.flush()

        next_assignee = _setup_candidates_and_assignment(db, change_request, next_node_info, next_record)

        _send_approval_notification(
            db,
            change_request=change_request,
            node_info=next_node_info,
            notification_type="APPROVAL_TODO",
            title="您有新的待审批申请",
            content=f"变更申请 {change_request.request_no} 已提交至您审批，请及时处理。",
            assignee=next_assignee
        )
    else:
        change_request.status = "APPROVED"
        change_request.approver = approver
        change_request.approval_comment = comment
        change_request.approved_at = now
        change_request.sync_status = "PENDING"

        _apply_changes_to_customer(db, change_request)
        db.flush()
        sync_to_systems(db, change_request)

        send_notification(
            db,
            change_request_id=request_id,
            recipient=change_request.submitter,
            notification_type="APPROVAL_NOTICE",
            title="变更申请已审批通过",
            content=f"您的变更申请 {change_request.request_no} 已全部审批通过，正在同步至各业务系统。"
        )

    log_operation(
        db,
        operation_type="APPROVE",
        operator=approver,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"审批通过，当前节点: {current_node.node_name}"
    )

    db.commit()
    db.refresh(change_request)
    return change_request


def reject_request(db: Session, request_id: int, approver: str, comment: str) -> ChangeRequest:
    """驳回申请"""
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法驳回")

    current_index = change_request.current_node_index
    chain = change_request.approval_chain
    current_node = chain.nodes[current_index] if chain and current_index < len(chain.nodes) else None

    change_request.status = "REJECTED"
    change_request.approver = approver
    change_request.approval_comment = comment
    change_request.approved_at = datetime.now()
    change_request.sync_status = "CANCELLED"

    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == request_id,
            ApprovalRecord.node_order == current_index
        )
    ).first()
    if current_record:
        current_record.approver = approver
        current_record.action = "REJECTED"
        current_record.comment = comment
        current_record.approved_at = datetime.now()

    log_operation(
        db,
        operation_type="REJECT",
        operator=approver,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"驳回申请: {comment}"
    )

    send_notification(
        db,
        change_request_id=request_id,
        recipient=change_request.submitter,
        notification_type="REJECTION_NOTICE",
        title="变更申请已被驳回",
        content=f"您的变更申请 {change_request.request_no} 已被 {approver} 驳回，原因：{comment}"
    )

    db.commit()
    db.refresh(change_request)
    return change_request


def batch_approve(db: Session, request_ids: List[int], approver: str,
                  comment: str = "") -> Dict[str, Any]:
    """批量审批通过"""
    success_count = 0
    fail_count = 0
    fail_details = []

    for request_id in request_ids:
        try:
            approve_request(db, request_id, approver, comment)
            success_count += 1
        except ValueError as e:
            fail_count += 1
            fail_details.append({
                "request_id": request_id,
                "reason": str(e)
            })

    log_operation(
        db,
        operation_type="BATCH_APPROVE",
        operator=approver,
        target_type="CHANGE_REQUEST",
        detail=f"批量审批 {len(request_ids)} 条，成功 {success_count} 条，失败 {fail_count} 条"
    )

    return {
        "total": len(request_ids),
        "success_count": success_count,
        "fail_count": fail_count,
        "fail_details": fail_details
    }


def batch_reject(db: Session, request_ids: List[int], approver: str,
                 comment: str) -> Dict[str, Any]:
    """批量驳回"""
    success_count = 0
    fail_count = 0
    fail_details = []

    for request_id in request_ids:
        try:
            reject_request(db, request_id, approver, comment)
            success_count += 1
        except ValueError as e:
            fail_count += 1
            fail_details.append({
                "request_id": request_id,
                "reason": str(e)
            })

    log_operation(
        db,
        operation_type="BATCH_REJECT",
        operator=approver,
        target_type="CHANGE_REQUEST",
        detail=f"批量驳回 {len(request_ids)} 条，成功 {success_count} 条，失败 {fail_count} 条"
    )

    return {
        "total": len(request_ids),
        "success_count": success_count,
        "fail_count": fail_count,
        "fail_details": fail_details
    }


def get_my_todo(db: Session, approver: str = None, role: str = None,
                department: str = None, priority: str = None,
                urgency: str = None, is_overdue: bool = None, page: int = 1,
                page_size: int = 20, include_claimable: bool = False) -> Dict[str, Any]:
    """
    获取我的待审批列表
    支持按审批人、角色、部门、优先级、加急、是否超时筛选
    include_claimable=True 时也返回可签收的任务（角色/部门匹配但未指派给具体人的）
    """
    subquery = db.query(ApprovalRecord.change_request_id).filter(
        ApprovalRecord.action == "PENDING"
    )
    if approver:
        if include_claimable:
            subquery = subquery.filter(
                or_(
                    ApprovalRecord.assignee == approver,
                    ApprovalRecord.approver == approver,
                    and_(
                        ApprovalRecord.assignee.is_(None),
                        or_(
                            and_(ApprovalRecord.approver_role == role, role is not None),
                            and_(ApprovalRecord.department == department, department is not None)
                        )
                    )
                )
            )
        else:
            subquery = subquery.filter(
                or_(
                    ApprovalRecord.assignee == approver,
                    ApprovalRecord.approver == approver
                )
            )
    if role:
        subquery = subquery.filter(ApprovalRecord.approver_role == role)
    if department:
        subquery = subquery.filter(ApprovalRecord.department == department)

    query = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.id.in_(subquery),
            ChangeRequest.status == "PENDING"
        )
    )

    if priority:
        query = query.filter(ChangeRequest.priority == priority)

    if urgency:
        query = query.filter(ChangeRequest.urgency == urgency)

    if is_overdue is not None:
        query = query.filter(ChangeRequest.is_overdue == is_overdue)

    total = query.count()
    items = query.order_by(
        ChangeRequest.urgency.desc(),
        ChangeRequest.priority.desc(),
        ChangeRequest.created_at.asc()
    ).offset((page - 1) * page_size).limit(page_size).all()

    result_items = []
    for item in items:
        item_dict = {c.name: getattr(item, c.name) for c in item.__table__.columns}
        current_record = next((r for r in item.approval_records if r.action == "PENDING"), None)
        if current_record:
            item_dict["current_assignee"] = current_record.assignee
            item_dict["current_claimed_by"] = current_record.claimed_by
            item_dict["candidate_users"] = json_to_dict(current_record.candidate_users) if current_record.candidate_users else []
            item_dict["assignment_type"] = current_record.assignment_type
        result_items.append(item_dict)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result_items
    }


def get_todo_stats(db: Session, approver: str = None, role: str = None,
                   department: str = None) -> Dict[str, Any]:
    """获取待办统计数据（今日待办、超时数量、各部门分布等）"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    subquery = db.query(ApprovalRecord.change_request_id).filter(
        ApprovalRecord.action == "PENDING"
    )
    if approver:
        subquery = subquery.filter(ApprovalRecord.approver == approver)
    if role:
        subquery = subquery.filter(ApprovalRecord.approver_role == role)
    if department:
        subquery = subquery.filter(ApprovalRecord.department == department)

    total_todo = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.id.in_(subquery),
            ChangeRequest.status == "PENDING"
        )
    ).count()

    today_todo = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.id.in_(subquery),
            ChangeRequest.status == "PENDING",
            ChangeRequest.created_at >= today_start
        )
    ).count()

    overdue_count = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.id.in_(subquery),
            ChangeRequest.status == "PENDING",
            ChangeRequest.is_overdue == True
        )
    ).count()

    high_priority_count = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.id.in_(subquery),
            ChangeRequest.status == "PENDING",
            ChangeRequest.priority == "HIGH"
        )
    ).count()

    return {
        "total_todo": total_todo,
        "today_todo": today_todo,
        "overdue_count": overdue_count,
        "high_priority_count": high_priority_count
    }


def check_and_update_overdue(db: Session) -> dict:
    """
    检查并更新超时的审批申请，发送超时催办通知
    返回: {"new_overdue": 新增超时数量, "notifications_sent": 发送通知数量}
    """
    from app.models import ApprovalChain
    from app.services import assignment_service

    pending_requests = db.query(ChangeRequest).filter(
        ChangeRequest.status == "PENDING"
    ).all()

    new_overdue = 0
    notifications_sent = 0
    now = datetime.now()

    for req in pending_requests:
        if not req.approval_chain:
            continue

        current_index = req.current_node_index
        if current_index >= len(req.approval_chain.nodes):
            continue

        current_node = req.approval_chain.nodes[current_index]
        if not current_node.timeout_hours:
            continue

        node_start_time = req.created_at
        if current_index > 0:
            prev_record = db.query(ApprovalRecord).filter(
                and_(
                    ApprovalRecord.change_request_id == req.id,
                    ApprovalRecord.node_order == current_index - 1
                )
            ).first()
            if prev_record and prev_record.approved_at:
                node_start_time = prev_record.approved_at

        delta_hours = (now - node_start_time).total_seconds() / 3600
        if delta_hours > current_node.timeout_hours:
            if not req.is_overdue:
                req.is_overdue = True
                new_overdue += 1

                current_record = db.query(ApprovalRecord).filter(
                    and_(
                        ApprovalRecord.change_request_id == req.id,
                        ApprovalRecord.node_order == current_index
                    )
                ).first()
                if current_record:
                    current_record.is_overdue = True

                assignee = current_record.assignee if current_record else None

                node_info = {
                    "approver": current_node.approver,
                    "approver_role": current_node.approver_role,
                    "department": current_node.department
                }

                assignment_service.send_reminder(
                    db,
                    request_id=req.id,
                    operator="SYSTEM",
                    reason=f"审批申请已超过 {current_node.timeout_hours} 小时未处理",
                    is_escalated=False
                )

                sent = _send_approval_notification(
                    db,
                    change_request=req,
                    node_info=node_info,
                    notification_type="OVERDUE_REMINDER",
                    title="审批申请超时提醒",
                    content=f"变更申请 {req.request_no} 已超过 {current_node.timeout_hours} 小时未处理，请尽快审批！",
                    assignee=assignee
                )
                if sent:
                    notifications_sent += 1

    db.commit()
    return {
        "new_overdue": new_overdue,
        "notifications_sent": notifications_sent
    }


def auto_approve_if_applicable(db: Session, change_request: ChangeRequest):
    """
    兼容旧接口：自动审批（针对单节点自动审批的情况）
    已由 init_approval_flow 替代，保留用于兼容
    """
    pass


def _apply_changes_to_customer(db: Session, change_request: ChangeRequest):
    customer = db.query(Customer).filter(Customer.id == change_request.customer_id).first()
    if not customer:
        return

    new_data = json_to_dict(change_request.new_data)

    for field, value in new_data.items():
        if hasattr(customer, field) and value is not None:
            setattr(customer, field, value)

    customer.updated_at = datetime.now()


def get_approval_records(db: Session, change_request_id: int) -> List[ApprovalRecord]:
    """获取审批流程记录"""
    return db.query(ApprovalRecord).filter(
        ApprovalRecord.change_request_id == change_request_id
    ).order_by(ApprovalRecord.node_order).all()
