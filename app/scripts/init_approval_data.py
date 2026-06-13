from app.services import approval_rule_service
from app.models import ApprovalChain, ApprovalRule


def init_default_approval_rules(db):
    """初始化默认审批规则和审批链"""

    default_chain = db.query(ApprovalChain).filter(
        ApprovalChain.chain_name == "默认审批链"
    ).first()

    if not default_chain:
        default_chain = approval_rule_service.create_approval_chain(
            db,
            chain_name="默认审批链",
            description="适用于所有未匹配到特殊规则的变更申请",
            nodes=[
                {
                    "node_name": "部门主管审批",
                    "approver_role": "DEPT_MANAGER",
                    "department": None,
                    "timeout_hours": 24
                }
            ]
        )
        print(f"已创建默认审批链")
    else:
        print("默认审批链已存在")

    normal_chain = db.query(ApprovalChain).filter(
        ApprovalChain.chain_name == "普通客户审批链"
    ).first()

    if not normal_chain:
        normal_chain = approval_rule_service.create_approval_chain(
            db,
            chain_name="普通客户审批链",
            description="普通客户变更，系统自动审批",
            nodes=[]
        )
        print(f"已创建普通客户审批链（自动审批）")
    else:
        print("普通客户审批链已存在")

    vip_chain = db.query(ApprovalChain).filter(
        ApprovalChain.chain_name == "VIP客户审批链"
    ).first()

    if not vip_chain:
        vip_chain = approval_rule_service.create_approval_chain(
            db,
            chain_name="VIP客户审批链",
            description="VIP客户变更，需区域经理审批",
            nodes=[
                {
                    "node_name": "区域经理审批",
                    "approver_role": "REGIONAL_MANAGER",
                    "department": None,
                    "timeout_hours": 48
                }
            ]
        )
        print(f"已创建VIP客户审批链")
    else:
        print("VIP客户审批链已存在")

    high_value_chain = db.query(ApprovalChain).filter(
        ApprovalChain.chain_name == "高风险行业审批链"
    ).first()

    if not high_value_chain:
        high_value_chain = approval_rule_service.create_approval_chain(
            db,
            chain_name="高风险行业审批链",
            description="金融、医疗等特殊行业，需多级审批",
            nodes=[
                {
                    "node_name": "部门主管审批",
                    "approver_role": "DEPT_MANAGER",
                    "department": None,
                    "timeout_hours": 24
                },
                {
                    "node_name": "区域经理审批",
                    "approver_role": "REGIONAL_MANAGER",
                    "department": None,
                    "timeout_hours": 48
                },
                {
                    "node_name": "总监审批",
                    "approver_role": "DIRECTOR",
                    "department": None,
                    "timeout_hours": 72
                }
            ]
        )
        print(f"已创建高风险行业审批链（三级审批）")
    else:
        print("高风险行业审批链已存在")

    sales_dept_chain = db.query(ApprovalChain).filter(
        ApprovalChain.chain_name == "销售一部快速审批链"
    ).first()

    if not sales_dept_chain:
        sales_dept_chain = approval_rule_service.create_approval_chain(
            db,
            chain_name="销售一部快速审批链",
            description="销售一部普通信息变更快速通道",
            nodes=[
                {
                    "node_name": "销售主管审批",
                    "approver_role": "SALES_MANAGER",
                    "department": "销售一部",
                    "timeout_hours": 12
                }
            ]
        )
        print(f"已创建销售一部快速审批链")
    else:
        print("销售一部快速审批链已存在")

    rules = [
        {
            "rule_name": "普通客户自动审批",
            "chain_id": normal_chain.id,
            "priority": 100,
            "customer_level": "NORMAL",
            "change_type": None,
            "department": None,
            "industry": None,
            "min_change_fields": 0,
            "description": "普通客户所有变更，系统自动审批"
        },
        {
            "rule_name": "VIP客户区域经理审批",
            "chain_id": vip_chain.id,
            "priority": 90,
            "customer_level": "VIP",
            "change_type": None,
            "department": None,
            "industry": None,
            "min_change_fields": 0,
            "description": "VIP客户变更，需区域经理审批"
        },
        {
            "rule_name": "金融行业三级审批",
            "chain_id": high_value_chain.id,
            "priority": 95,
            "customer_level": None,
            "change_type": None,
            "department": None,
            "industry": "金融",
            "min_change_fields": 0,
            "description": "金融行业客户，需三级审批"
        },
        {
            "rule_name": "销售一部快速通道",
            "chain_id": sales_dept_chain.id,
            "priority": 80,
            "customer_level": None,
            "change_type": "BASIC_INFO",
            "department": "销售一部",
            "industry": None,
            "min_change_fields": 0,
            "description": "销售一部的基本信息变更，走快速审批"
        },
        {
            "rule_name": "多字段变更主管审批",
            "chain_id": vip_chain.id,
            "priority": 85,
            "customer_level": None,
            "change_type": None,
            "department": None,
            "industry": None,
            "min_change_fields": 5,
            "description": "变更字段超过5个，需区域经理审批"
        }
    ]

    for rule_data in rules:
        existing = db.query(ApprovalRule).filter(
            ApprovalRule.rule_name == rule_data["rule_name"]
        ).first()
        if not existing:
            approval_rule_service.create_approval_rule(db, **rule_data)
            print(f"已创建规则: {rule_data['rule_name']}")
        else:
            print(f"规则已存在: {rule_data['rule_name']}")

    print("\n审批规则初始化完成")


if __name__ == "__main__":
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        init_default_approval_rules(db)
    finally:
        db.close()
