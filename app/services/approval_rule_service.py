from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models import ApprovalRule, ApprovalChain, ApprovalNode, Customer, ChangeRequest
from app.services.utils import log_operation


def match_approval_rule(db: Session, customer: Customer, change_type: str,
                        department: str, diff_fields_count: int) -> Dict[str, Any]:
    """
    多维度匹配审批规则
    匹配维度：客户等级、变更类型、所属部门、客户行业、变更字段数
    规则按priority降序匹配，命中第一个即返回
    """
    rules = db.query(ApprovalRule).filter(
        ApprovalRule.is_active == True
    ).order_by(ApprovalRule.priority.desc(), ApprovalRule.id.desc()).all()

    matched_rule = None
    for rule in rules:
        if rule.customer_level and rule.customer_level != customer.customer_level:
            continue
        if rule.change_type and rule.change_type != change_type:
            continue
        if rule.department and rule.department != department:
            continue
        if rule.industry and rule.industry != customer.industry:
            continue
        if rule.min_change_fields and diff_fields_count < rule.min_change_fields:
            continue
        matched_rule = rule
        break

    if not matched_rule:
        default_chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_name == "默认审批链"
        ).first()
        if default_chain:
            return {
                "matched": True,
                "rule": None,
                "chain": default_chain,
                "rule_name": "默认规则",
                "match_reason": "未命中特殊规则，使用默认审批链"
            }
        return {
            "matched": False,
            "rule": None,
            "chain": None,
            "rule_name": "",
            "match_reason": "未找到匹配的审批规则"
        }

    chain = db.query(ApprovalChain).filter(ApprovalChain.id == matched_rule.chain_id).first()

    match_details = []
    if matched_rule.customer_level:
        match_details.append(f"客户等级={matched_rule.customer_level}")
    if matched_rule.change_type:
        match_details.append(f"变更类型={matched_rule.change_type}")
    if matched_rule.department:
        match_details.append(f"所属部门={matched_rule.department}")
    if matched_rule.industry:
        match_details.append(f"所属行业={matched_rule.industry}")
    if matched_rule.min_change_fields:
        match_details.append(f"变更字段数≥{matched_rule.min_change_fields}")

    return {
        "matched": True,
        "rule": matched_rule,
        "chain": chain,
        "rule_name": matched_rule.rule_name,
        "match_reason": "命中规则: " + ", ".join(match_details)
    }


def get_next_approver(chain: ApprovalChain, current_node_index: int) -> Dict[str, Any]:
    """获取下一个审批节点信息"""
    if not chain or not chain.nodes:
        return {
            "has_next": False,
            "node": None,
            "approver": None,
            "node_name": "",
            "timeout_hours": 0
        }

    if current_node_index >= len(chain.nodes):
        return {
            "has_next": False,
            "node": None,
            "approver": None,
            "node_name": "已完成",
            "timeout_hours": 0
        }

    node = chain.nodes[current_node_index]
    return {
        "has_next": True,
        "node": node,
        "node_id": node.id,
        "node_name": node.node_name,
        "approver_role": node.approver_role,
        "approver": node.approver,
        "department": node.department,
        "timeout_hours": node.timeout_hours
    }


def create_approval_chain(db: Session, chain_name: str, description: str = "",
                           nodes: List[Dict] = None) -> ApprovalChain:
    """创建审批链"""
    chain = ApprovalChain(
        chain_name=chain_name,
        description=description
    )
    db.add(chain)
    db.flush()

    if nodes:
        for idx, node_data in enumerate(nodes):
            node = ApprovalNode(
                chain_id=chain.id,
                node_name=node_data.get("node_name", f"第{idx+1}级审批"),
                node_order=idx,
                approver_role=node_data.get("approver_role"),
                approver=node_data.get("approver"),
                department=node_data.get("department"),
                timeout_hours=node_data.get("timeout_hours", 24)
            )
            db.add(node)

    log_operation(
        db,
        operation_type="CREATE_APPROVAL_CHAIN",
        operator="admin",
        target_type="APPROVAL_CHAIN",
        target_id=chain.id,
        detail=f"创建审批链: {chain_name}"
    )

    db.commit()
    db.refresh(chain)
    return chain


def create_approval_rule(db: Session, rule_name: str, chain_id: int, priority: int = 0,
                         customer_level: str = None, change_type: str = None,
                         department: str = None, industry: str = None,
                         min_change_fields: int = 0, description: str = "") -> ApprovalRule:
    """创建审批规则"""
    rule = ApprovalRule(
        rule_name=rule_name,
        chain_id=chain_id,
        priority=priority,
        customer_level=customer_level,
        change_type=change_type,
        department=department,
        industry=industry,
        min_change_fields=min_change_fields,
        description=description
    )
    db.add(rule)

    log_operation(
        db,
        operation_type="CREATE_APPROVAL_RULE",
        operator="admin",
        target_type="APPROVAL_RULE",
        target_id=rule.id,
        detail=f"创建审批规则: {rule_name}"
    )

    db.commit()
    db.refresh(rule)
    return rule


def list_approval_chains(db: Session, is_active: bool = None) -> List[ApprovalChain]:
    """获取审批链列表"""
    query = db.query(ApprovalChain)
    if is_active is not None:
        query = query.filter(ApprovalChain.is_active == is_active)
    return query.order_by(ApprovalChain.id.desc()).all()


def list_approval_rules(db: Session, is_active: bool = None) -> List[ApprovalRule]:
    """获取审批规则列表"""
    query = db.query(ApprovalRule)
    if is_active is not None:
        query = query.filter(ApprovalRule.is_active == is_active)
    return query.order_by(ApprovalRule.priority.desc(), ApprovalRule.id.desc()).all()


def get_approval_chain_detail(db: Session, chain_id: int) -> Optional[ApprovalChain]:
    """获取审批链详情"""
    return db.query(ApprovalChain).filter(ApprovalChain.id == chain_id).first()


def update_approval_rule(db: Session, rule_id: int, **kwargs) -> ApprovalRule:
    """更新审批规则"""
    rule = db.query(ApprovalRule).filter(ApprovalRule.id == rule_id).first()
    if not rule:
        raise ValueError("审批规则不存在")

    for key, value in kwargs.items():
        if hasattr(rule, key) and value is not None:
            setattr(rule, key, value)

    log_operation(
        db,
        operation_type="UPDATE_APPROVAL_RULE",
        operator="admin",
        target_type="APPROVAL_RULE",
        target_id=rule.id,
        detail=f"更新审批规则: {rule.rule_name}"
    )

    db.commit()
    db.refresh(rule)
    return rule


def toggle_approval_rule(db: Session, rule_id: int, is_active: bool) -> ApprovalRule:
    """启用/禁用审批规则"""
    rule = db.query(ApprovalRule).filter(ApprovalRule.id == rule_id).first()
    if not rule:
        raise ValueError("审批规则不存在")

    rule.is_active = is_active
    db.commit()
    db.refresh(rule)
    return rule
