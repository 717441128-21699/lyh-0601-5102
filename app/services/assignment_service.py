import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models import (
    ApprovalCandidate, ApprovalAssignment, ApprovalReminder,
    ChangeRequest, ApprovalRecord, Customer
)
from app.services.utils import log_operation, dict_to_json, json_to_dict
from app.services.notification_service import send_notification
from app.services import approval_rule_service


def get_candidates(db: Session, role: str = None, department: str = None,
                   is_active: bool = True) -> List[ApprovalCandidate]:
    """
    根据角色和部门获取候选处理人列表
    优先级：精确匹配(role+department) > 只匹配role(department=None) > 只匹配department
    """
    if not role and not department:
        return []

    query = db.query(ApprovalCandidate)

    if is_active is not None:
        query = query.filter(ApprovalCandidate.is_active == is_active)

    candidates = []
    if role and department:
        exact_match = query.filter(
            and_(
                ApprovalCandidate.role == role,
                ApprovalCandidate.department == department
            )
        ).all()
        if exact_match:
            return exact_match

        role_generic = query.filter(
            and_(
                ApprovalCandidate.role == role,
                ApprovalCandidate.department.is_(None)
            )
        ).all()
        if role_generic:
            return role_generic

        dept_match = query.filter(
            and_(
                ApprovalCandidate.department == department
            )
        ).all()
        return dept_match
    elif role:
        return query.filter(ApprovalCandidate.role == role).all()
    elif department:
        return query.filter(ApprovalCandidate.department == department).all()

    return []


def get_candidate_users(db: Session, role: str = None, department: str = None) -> List[Dict[str, Any]]:
    """获取候选处理人列表，返回格式化的用户信息"""
    candidates = get_candidates(db, role=role, department=department)
    return [
        {
            "username": c.username,
            "real_name": c.real_name,
            "role": c.role,
            "department": c.department,
            "email": c.email,
            "phone": c.phone,
            "is_default": c.is_default
        }
        for c in candidates
    ]


def auto_assign(db: Session, change_request: ChangeRequest, node_info: Dict) -> Optional[str]:
    """
    自动指派处理人
    优先选 is_default=True 的候选人，否则选第一个
    返回指派的用户名
    """
    role = node_info.get("approver_role")
    department = node_info.get("department") or change_request.department

    if not role and not department:
        return None

    candidates = get_candidates(db, role=role, department=department)
    if not candidates:
        return None

    default_candidate = next((c for c in candidates if c.is_default), None)
    if default_candidate:
        assignee = default_candidate.username
    else:
        assignee = candidates[0].username

    assignment = ApprovalAssignment(
        change_request_id=change_request.id,
        node_order=change_request.current_node_index,
        assignment_type="AUTO",
        from_user=None,
        to_user=assignee,
        reason="系统自动指派",
        operator="SYSTEM"
    )
    db.add(assignment)

    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == change_request.id,
            ApprovalRecord.node_order == change_request.current_node_index
        )
    ).first()
    if current_record:
        current_record.assignee = assignee
        current_record.assignment_type = "AUTO"
        current_record.candidate_users = dict_to_json(get_candidate_users(db, role=role, department=department))

    db.flush()
    return assignee


def claim_task(db: Session, request_id: int, claimer: str) -> Dict[str, Any]:
    """
    签收任务
    """
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法签收")

    current_index = change_request.current_node_index
    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == request_id,
            ApprovalRecord.node_order == current_index,
            ApprovalRecord.action == "PENDING"
        )
    ).first()

    if not current_record:
        raise ValueError("当前没有待处理的审批节点")

    if current_record.assignee and current_record.assignee != claimer:
        raise ValueError(f"该任务已指派给 {current_record.assignee}，如需处理请先转派")

    current_record.assignee = claimer
    current_record.claimed_at = datetime.now()
    current_record.claimed_by = claimer
    current_record.assignment_type = "CLAIM"

    assignment = ApprovalAssignment(
        change_request_id=request_id,
        approval_record_id=current_record.id,
        node_order=current_index,
        assignment_type="CLAIM",
        from_user=None,
        to_user=claimer,
        reason="用户自主签收",
        operator=claimer
    )
    db.add(assignment)

    log_operation(
        db,
        operation_type="CLAIM_TASK",
        operator=claimer,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"签收审批任务: 节点={current_record.node_name}"
    )

    db.commit()
    db.refresh(change_request)

    return {
        "success": True,
        "request_id": request_id,
        "assignee": claimer,
        "node_name": current_record.node_name
    }


def reassign_task(db: Session, request_id: int, from_user: str, to_user: str,
                  reason: str, operator: str, is_manager: bool = False) -> Dict[str, Any]:
    """
    转派任务
    """
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法转派")

    current_index = change_request.current_node_index
    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == request_id,
            ApprovalRecord.node_order == current_index,
            ApprovalRecord.action == "PENDING"
        )
    ).first()

    if not current_record:
        raise ValueError("当前没有待处理的审批节点")

    if not is_manager and current_record.assignee and current_record.assignee != from_user:
        raise ValueError("只能转派自己负责的任务")

    old_assignee = current_record.assignee
    current_record.assignee = to_user
    current_record.assignment_type = "REASSIGN"

    assignment = ApprovalAssignment(
        change_request_id=request_id,
        approval_record_id=current_record.id,
        node_order=current_index,
        assignment_type="REASSIGN",
        from_user=old_assignee or from_user,
        to_user=to_user,
        reason=reason,
        operator=operator
    )
    db.add(assignment)

    send_notification(
        db,
        change_request_id=request_id,
        recipient=to_user,
        notification_type="APPROVAL_TODO",
        title="审批任务转派通知",
        content=f"审批任务已转派给您处理：{change_request.request_no}，原因：{reason}"
    )

    if old_assignee and old_assignee != to_user:
        send_notification(
            db,
            change_request_id=request_id,
            recipient=old_assignee,
            notification_type="APPROVAL_NOTICE",
            title="您的审批任务已被转派",
            content=f"您负责的审批任务 {change_request.request_no} 已转派给 {to_user}，原因：{reason}"
        )

    log_operation(
        db,
        operation_type="REASSIGN_TASK",
        operator=operator,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"转派审批任务: 从{old_assignee or '未指派'}到{to_user}, 原因: {reason}"
    )

    db.commit()
    db.refresh(change_request)

    return {
        "success": True,
        "request_id": request_id,
        "old_assignee": old_assignee,
        "new_assignee": to_user,
        "node_name": current_record.node_name
    }


def send_reminder(db: Session, request_id: int, operator: str,
                 reason: str = None, is_escalated: bool = False) -> Dict[str, Any]:
    """
    发送催办
    """
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    if change_request.status != "PENDING":
        raise ValueError(f"当前状态为 {change_request.status}，无法催办")

    current_index = change_request.current_node_index
    current_record = db.query(ApprovalRecord).filter(
        and_(
            ApprovalRecord.change_request_id == request_id,
            ApprovalRecord.node_order == current_index,
            ApprovalRecord.action == "PENDING"
        )
    ).first()

    if not current_record:
        raise ValueError("当前没有待处理的审批节点")

    target_user = current_record.assignee
    if not target_user:
        node = current_record.node
        if node:
            candidates = get_candidate_users(db, role=node.approver_role, department=node.department)
            if candidates:
                target_user = candidates[0]["username"]

    if not target_user:
        raise ValueError("无法确定催办对象，任务尚未指派也没有候选处理人")

    reminder = ApprovalReminder(
        change_request_id=request_id,
        approval_record_id=current_record.id,
        reminder_type="MANUAL" if not is_escalated else "ESCALATED",
        reminder_level="HIGH" if is_escalated else "NORMAL",
        target_user=target_user,
        operator=operator,
        reason=reason or "请及时处理审批任务",
        is_escalated=is_escalated
    )
    db.add(reminder)

    notification_title = "审批催办通知" if not is_escalated else "审批加急催办通知"
    notification_content = f"请及时处理审批任务：{change_request.request_no}"
    if reason:
        notification_content += f"，催办原因：{reason}"

    send_notification(
        db,
        change_request_id=request_id,
        recipient=target_user,
        notification_type="OVERDUE_REMINDER" if is_escalated else "APPROVAL_TODO",
        title=notification_title,
        content=notification_content
    )

    log_operation(
        db,
        operation_type="SEND_REMINDER",
        operator=operator,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"发送催办: 目标用户={target_user}, 原因: {reason or '无'}, 加急: {is_escalated}"
    )

    db.commit()

    return {
        "success": True,
        "request_id": request_id,
        "target_user": target_user,
        "reminder_id": reminder.id,
        "is_escalated": is_escalated
    }


def set_urgency(db: Session, request_id: int, urgency: str, operator: str) -> Dict[str, Any]:
    """
    设置加急状态
    """
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not change_request:
        raise ValueError("变更申请不存在")

    change_request.urgency = urgency

    log_operation(
        db,
        operation_type="SET_URGENCY",
        operator=operator,
        target_type="CHANGE_REQUEST",
        target_id=request_id,
        detail=f"设置加急状态: {urgency}"
    )

    db.commit()
    db.refresh(change_request)

    return {
        "success": True,
        "request_id": request_id,
        "urgency": urgency
    }


def get_reminder_history(db: Session, request_id: int) -> List[Dict[str, Any]]:
    """
    获取催办历史
    """
    reminders = db.query(ApprovalReminder).filter(
        ApprovalReminder.change_request_id == request_id
    ).order_by(ApprovalReminder.created_at.desc()).all()

    return [
        {
            "id": r.id,
            "reminder_type": r.reminder_type,
            "reminder_level": r.reminder_level,
            "target_user": r.target_user,
            "operator": r.operator,
            "reason": r.reason,
            "is_escalated": r.is_escalated,
            "created_at": r.created_at
        }
        for r in reminders
    ]


def get_assignment_history(db: Session, request_id: int) -> List[Dict[str, Any]]:
    """
    获取指派/转派历史
    """
    assignments = db.query(ApprovalAssignment).filter(
        ApprovalAssignment.change_request_id == request_id
    ).order_by(ApprovalAssignment.created_at.desc()).all()

    return [
        {
            "id": a.id,
            "assignment_type": a.assignment_type,
            "from_user": a.from_user,
            "to_user": a.to_user,
            "reason": a.reason,
            "operator": a.operator,
            "created_at": a.created_at
        }
        for a in assignments
    ]


def create_candidate(db: Session, role: str, department: str, username: str,
                     real_name: str, email: str = None, phone: str = None,
                     is_default: bool = False) -> ApprovalCandidate:
    """
    创建候选处理人
    """
    existing = db.query(ApprovalCandidate).filter(
        and_(
            ApprovalCandidate.role == role,
            ApprovalCandidate.department == department,
            ApprovalCandidate.username == username
        )
    ).first()

    if existing:
        raise ValueError("该角色+部门下已存在相同的用户名")

    if is_default:
        db.query(ApprovalCandidate).filter(
            and_(
                ApprovalCandidate.role == role,
                ApprovalCandidate.department == department,
                ApprovalCandidate.is_default == True
            )
        ).update({"is_default": False})

    candidate = ApprovalCandidate(
        role=role,
        department=department,
        username=username,
        real_name=real_name,
        email=email,
        phone=phone,
        is_default=is_default
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def init_default_candidates(db: Session):
    """
    初始化默认候选处理人
    """
    default_candidates = [
        {"role": "DEPT_MANAGER", "department": "销售一部", "username": "zhangsan", "real_name": "张三", "email": "zhangsan@company.com", "phone": "13800000001", "is_default": True},
        {"role": "DEPT_MANAGER", "department": "销售一部", "username": "lisi", "real_name": "李四", "email": "lisi@company.com", "phone": "13800000002", "is_default": False},
        {"role": "DEPT_MANAGER", "department": "销售二部", "username": "wangwu", "real_name": "王五", "email": "wangwu@company.com", "phone": "13800000003", "is_default": True},
        {"role": "DEPT_MANAGER", "department": "金融部", "username": "zhaoliu", "real_name": "赵六", "email": "zhaoliu@company.com", "phone": "13800000004", "is_default": True},
        {"role": "DEPT_MANAGER", "department": "金融部", "username": "sunqi", "real_name": "孙七", "email": "sunqi@company.com", "phone": "13800000005", "is_default": False},
        {"role": "REGIONAL_MANAGER", "department": None, "username": "zhouba", "real_name": "周八", "email": "zhouba@company.com", "phone": "13800000006", "is_default": True},
        {"role": "REGIONAL_MANAGER", "department": None, "username": "wujiu", "real_name": "吴九", "email": "wujiu@company.com", "phone": "13800000007", "is_default": False},
        {"role": "DIRECTOR", "department": None, "username": "zhengshi", "real_name": "郑十", "email": "zhengshi@company.com", "phone": "13800000008", "is_default": True},
        {"role": "SALES_MANAGER", "department": "销售一部", "username": "qianyi", "real_name": "钱一", "email": "qianyi@company.com", "phone": "13800000009", "is_default": True},
    ]

    for data in default_candidates:
        existing = db.query(ApprovalCandidate).filter(
            and_(
                ApprovalCandidate.role == data["role"],
                ApprovalCandidate.department == data["department"],
                ApprovalCandidate.username == data["username"]
            )
        ).first()
        if not existing:
            create_candidate(
                db,
                role=data["role"],
                department=data["department"],
                username=data["username"],
                real_name=data["real_name"],
                email=data["email"],
                phone=data["phone"],
                is_default=data["is_default"]
            )
            print(f"已创建候选处理人: {data['real_name']} ({data['role']}/{data['department'] or '跨部门'})")
        else:
            print(f"候选处理人已存在: {data['real_name']}")

    print("\n候选处理人初始化完成")
