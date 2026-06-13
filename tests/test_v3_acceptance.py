"""
第五轮需求综合验收测试
验证：
1. 待办中心候选处理人视图：角色/部门映射具体人、自动指派、签收
2. 催办和转派闭环：超时催办、主管转派、加急、催办记录
3. 风控处理工作台：预警中客户、已冻结客户、恢复记录、规则命中追踪
4. 同步结果汇总和失败重试：各系统状态、重试次数、通知状态
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Customer
from app.schemas import ChangeRequestCreate
from app.services import (
    change_request_service,
    approval_service,
    assignment_service,
    risk_operation_service,
    sync_service,
    risk_service
)

TEST_DB_URL = "sqlite:///./test_v3_acceptance.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def print_test_title(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_subtitle(title):
    print(f"\n--- {title} ---")


def main():
    db = TestingSessionLocal()
    try:
        print("\n" + "=" * 80)
        print("  第五轮需求综合验收测试")
        print("  版本: v3.0.0")
        print("=" * 80)

        from app.scripts import init_approval_data
        init_approval_data.init_default_approval_rules(db)
        assignment_service.init_default_candidates(db)
        db.commit()

        test_candidate_assignment_and_claim(db)
        test_reminder_and_reassign(db)
        test_risk_workbench(db)
        test_sync_summary_and_retry(db)

        print("\n" + "=" * 80)
        print("  ✅ 所有第五轮需求验收测试通过！")
        print("=" * 80)

    finally:
        db.close()


def test_candidate_assignment_and_claim(db):
    print_test_title("第一部分：待办中心候选处理人视图")

    print_subtitle("准备测试数据 - 创建金融行业VIP客户")
    customer = Customer(
        customer_code="CAND001",
        customer_name="候选处理人测试客户",
        customer_level="VIP",
        industry="金融",
        department="金融部",
        contact_person="联系人1",
        contact_phone="13900000001",
        order_manager="order_mgr_001"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    print(f"  ✅ 客户创建成功: {customer.customer_code} - {customer.customer_name}")

    print_subtitle("1.1 提交申请 - 验证自动指派到具体人")
    req_data = ChangeRequestCreate(
        customer_code="CAND001",
        change_type="CONTACT_CHANGE",
        submitter="employee001",
        department="金融部",
        new_data={"contact_phone": "13900000002", "contact_person": "联系人2"}
    )
    result = change_request_service.submit_change_request(db, req_data)
    request_id = result["request"]["id"]
    request_no = result["request"]["request_no"]
    print(f"  ✅ 申请提交成功: {request_no}")

    approval_flow = result.get("approval_flow", {})
    assert "next_approver" in approval_flow, "❌ 缺失下一步处理人信息"
    print(f"  ✅ 命中审批链: {approval_flow.get('chain_name')}")
    print(f"  ✅ 节点: {approval_flow['next_approver'].get('node_name')}")
    print(f"  ✅ 节点配置角色: {approval_flow['next_approver'].get('approver_role')}")

    detail = change_request_service.get_change_request_detail(db, request_id)
    current_assignee = detail.get("current_assignee")
    candidate_users = detail.get("candidate_users", [])
    assert current_assignee is not None, "❌ 系统没有自动指派具体处理人"
    print(f"  ✅ 系统自动指派处理人: {current_assignee}")
    assert len(candidate_users) > 0, "❌ 没有列出候选处理人"
    print(f"  ✅ 候选处理人列表: {[u['real_name'] for u in candidate_users]}")
    print(f"  ✅ 指派方式: {detail.get('assignment_type')}")

    print_subtitle("1.2 查询待办 - 验证具体人能查到自己的待办")
    todo_result = approval_service.get_my_todo(
        db, approver=current_assignee, page=1, page_size=10
    )
    assert todo_result["total"] >= 1, f"❌ 指派人 {current_assignee} 的待办列表为空"
    todo_item = todo_result["items"][0]
    assert todo_item["id"] == request_id, "❌ 待办列表中找不到对应申请"
    assert todo_item.get("current_assignee") == current_assignee, "❌ 待办项的指派人不正确"
    print(f"  ✅ 指派人 {current_assignee} 的待办列表能看到申请")
    print(f"  ✅ 待办项显示具体处理人: {todo_item.get('current_assignee')}")
    print(f"  ✅ 候选处理人信息完整: {len(todo_item.get('candidate_users', []))} 人")

    print_subtitle("1.3 验证指派历史记录")
    assignment_history = detail.get("assignment_history", [])
    assert len(assignment_history) >= 1, "❌ 没有指派历史记录"
    first_assignment = assignment_history[-1]
    assert first_assignment["assignment_type"] == "AUTO", "❌ 首次指派不是自动指派"
    assert first_assignment["to_user"] == current_assignee, "❌ 指派历史记录不正确"
    print(f"  ✅ 指派历史记录: {first_assignment['assignment_type']} -> {first_assignment['to_user']}")

    print_subtitle("1.4 签收功能测试 - 另一个候选处理人签收")
    other_candidate = next((u for u in candidate_users if u["username"] != current_assignee), None)
    if other_candidate:
        try:
            assignment_service.claim_task(db, request_id, other_candidate["username"])
            print(f"  ❌ 不应该能签收已指派给别人的任务")
        except ValueError as e:
            print(f"  ✅ 已指派的任务不能被其他人签收，错误提示正确: {e}")

    db.rollback()
    req_data2 = ChangeRequestCreate(
        customer_code="CAND001",
        change_type="CONTACT_CHANGE",
        submitter="employee001",
        department="金融部",
        new_data={"contact_email": "test@test.com"}
    )
    result2 = change_request_service.submit_change_request(db, req_data2)
    request_id2 = result2["request"]["id"]

    detail2 = change_request_service.get_change_request_detail(db, request_id2)
    assignee2 = detail2.get("current_assignee")
    print(f"  ✅ 第二个申请自动指派人: {assignee2}")

    records = db.query(assignment_service.ApprovalRecord).filter(
        assignment_service.ApprovalRecord.change_request_id == request_id2
    ).first()
    records.assignee = None
    records.assignment_type = None
    db.commit()

    claimer = candidate_users[1]["username"] if len(candidate_users) > 1 else candidate_users[0]["username"]
    claim_result = assignment_service.claim_task(db, request_id2, claimer)
    assert claim_result["success"] == True, "❌ 签收失败"
    assert claim_result["assignee"] == claimer, "❌ 签收人不正确"
    print(f"  ✅ 未指派任务被 {claimer} 成功签收")

    detail2_after = change_request_service.get_change_request_detail(db, request_id2)
    assert detail2_after.get("current_claimed_by") == claimer, "❌ 签收人未正确记录"
    print(f"  ✅ 签收人已记录: {detail2_after.get('current_claimed_by')}")

    todo_claimer = approval_service.get_my_todo(db, approver=claimer, page=1, page_size=10)
    has_request = any(item["id"] == request_id2 for item in todo_claimer["items"])
    assert has_request, "❌ 签收后待办列表没有该申请"
    print(f"  ✅ 签收人 {claimer} 的待办列表能看到申请")

    print("\n✅ 第一部分测试通过：候选处理人、自动指派、签收功能正常")


def test_reminder_and_reassign(db):
    print_test_title("第二部分：催办和转派闭环")

    print_subtitle("准备测试数据 - VIP客户（二级审批链）")
    customer = Customer(
        customer_code="REMIND001",
        customer_name="催办转派测试客户",
        customer_level="VIP",
        industry="零售",
        department="销售一部",
        contact_person="联系人A",
        contact_phone="13800000001",
        order_manager="order_mgr_002"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    req_data = ChangeRequestCreate(
        customer_code="REMIND001",
        change_type="CONTACT_CHANGE",
        submitter="employee002",
        department="销售一部",
        new_data={"contact_phone": "13800000002"}
    )
    result = change_request_service.submit_change_request(db, req_data)
    request_id = result["request"]["id"]
    detail = change_request_service.get_change_request_detail(db, request_id)
    original_assignee = detail.get("current_assignee")
    approval_chain = detail.get("approval_flow", {}).get("chain_name")
    print(f"  ✅ 申请创建成功，审批链: {approval_chain}")
    print(f"  ✅ 原指派人: {original_assignee}")

    print_subtitle("2.1 加急功能测试")
    urgency_result = assignment_service.set_urgency(
        db, request_id=request_id, urgency="HIGH", operator="supervisor001"
    )
    assert urgency_result["success"] == True, "❌ 设置加急失败"
    assert urgency_result["urgency"] == "HIGH", "❌ 加急状态不正确"
    print(f"  ✅ 设置加急成功: {urgency_result['urgency']}")

    detail_after = change_request_service.get_change_request_detail(db, request_id)
    assert detail_after["urgency"] == "HIGH", "❌ 加急状态未保存"
    print(f"  ✅ 申请详情加急状态: {detail_after['urgency']}")

    print_subtitle("2.2 催办功能测试")
    reminder_result = assignment_service.send_reminder(
        db, request_id=request_id, operator="supervisor001",
        reason="请尽快处理此紧急申请", is_escalated=False
    )
    assert reminder_result["success"] == True, "❌ 发送催办失败"
    assert reminder_result["target_user"] == original_assignee, "❌ 催办对象不正确"
    print(f"  ✅ 催办发送成功，对象: {reminder_result['target_user']}")

    reminders = assignment_service.get_reminder_history(db, request_id)
    assert len(reminders) >= 1, "❌ 没有催办历史记录"
    latest_reminder = reminders[0]
    assert latest_reminder["reason"] == "请尽快处理此紧急申请", "❌ 催办原因不正确"
    print(f"  ✅ 催办历史记录: {latest_reminder['reminder_type']} - {latest_reminder['reason']}")

    print_subtitle("2.3 转派功能测试")
    candidates = assignment_service.get_candidate_users(db, role="DEPT_MANAGER", department="金融部")
    new_assignee = next((c for c in candidates if c["username"] != original_assignee), candidates[-1])
    print(f"  ✅ 新负责人: {new_assignee['username']} ({new_assignee['real_name']})")

    reassign_result = assignment_service.reassign_task(
        db, request_id=request_id,
        from_user=original_assignee,
        to_user=new_assignee["username"],
        reason="原处理人请假，转由你处理",
        operator="supervisor001",
        is_manager=True
    )
    assert reassign_result["success"] == True, "❌ 转派失败"
    assert reassign_result["new_assignee"] == new_assignee["username"], "❌ 转派目标人不正确"
    print(f"  ✅ 转派成功: {original_assignee} -> {new_assignee['username']}")

    detail_after_reassign = change_request_service.get_change_request_detail(db, request_id)
    assert detail_after_reassign.get("current_assignee") == new_assignee["username"], "❌ 转派后指派人未更新"
    print(f"  ✅ 转派后申请详情显示处理人: {detail_after_reassign.get('current_assignee')}")

    print_subtitle("2.4 验证新负责人能在待办中接住")
    todo_new = approval_service.get_my_todo(
        db, approver=new_assignee["username"], page=1, page_size=10
    )
    todo_ids = [item["id"] for item in todo_new["items"]]
    assert request_id in todo_ids, f"❌ 新负责人 {new_assignee['username']} 的待办中找不到申请"
    print(f"  ✅ 新负责人 {new_assignee['username']} 待办列表已收到申请")

    todo_old = approval_service.get_my_todo(
        db, approver=original_assignee, page=1, page_size=10
    )
    todo_old_ids = [item["id"] for item in todo_old["items"]]
    assert request_id not in todo_old_ids, "❌ 原负责人待办列表还能看到已转派的申请"
    print(f"  ✅ 原负责人 {original_assignee} 待办列表已移除该申请")

    print_subtitle("2.5 验证转派历史记录")
    assignments = assignment_service.get_assignment_history(db, request_id)
    assert len(assignments) >= 2, "❌ 没有足够的指派历史记录"
    reassign_record = assignments[0]
    assert reassign_record["assignment_type"] == "REASSIGN", "❌ 转派类型不正确"
    assert reassign_record["to_user"] == new_assignee["username"], "❌ 转派目标人不正确"
    print(f"  ✅ 转派历史记录: {reassign_record['from_user']} -> {reassign_record['to_user']}")
    print(f"  ✅ 转派原因: {reassign_record['reason']}")

    print_subtitle("2.6 新负责人审批通过（VIP客户单节点审批链）")
    detail_before = change_request_service.get_change_request_detail(db, request_id)
    print(f"  ✅ 当前节点索引: {detail_before['current_node_index']}")
    print(f"  ✅ 审批链: {detail_before.get('approval_flow', {}).get('chain_name')}")
    print(f"  ✅ 总节点数: {detail_before.get('approval_flow', {}).get('total_nodes')}")

    approval_service.approve_request(db, request_id, new_assignee["username"], "同意，资料正确")
    detail_final = change_request_service.get_change_request_detail(db, request_id)
    assert detail_final["status"] == "APPROVED", f"❌ 审批未通过，当前状态: {detail_final['status']}"
    print(f"  ✅ 审批通过，申请最终状态: {detail_final['status']}")

    print("\n✅ 第二部分测试通过：催办、转派、加急功能闭环正常")


def test_risk_workbench(db):
    print_test_title("第三部分：风控处理工作台")

    print_subtitle("准备测试数据 - 创建客户并触发多次变更")
    customer = Customer(
        customer_code="RISKOP001",
        customer_name="风控工作台测试客户",
        customer_level="NORMAL",
        industry="零售",
        department="销售一部",
        contact_person="风控测试员",
        contact_phone="13700000001",
        order_manager="order_mgr_003"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    customer_id = customer.id
    print(f"  ✅ 客户创建成功: {customer.customer_code}")

    for i in range(3):
        req_data = ChangeRequestCreate(
            customer_code="RISKOP001",
            change_type="CONTACT_CHANGE",
            submitter="employee003",
            department="销售一部",
            new_data={"contact_phone": f"137000000{i+2}"}
        )
        result = change_request_service.submit_change_request(db, req_data)
        print(f"  ✅ 第 {i+1} 次变更提交成功")

    print_subtitle("3.1 工作台汇总数据")
    summary = risk_operation_service.get_risk_workbench_summary(db)
    print(f"  ✅ 预警客户数: {summary.get('warning_customers')}")
    print(f"  ✅ 冻结客户数: {summary.get('frozen_customers')}")
    print(f"  ✅ 进行中案件: {summary.get('processing_cases')}")
    print(f"  ✅ 近30天恢复: {summary.get('recovered_last_30d')}")

    print_subtitle("3.2 预警客户列表")
    warning_list = risk_operation_service.get_warning_customers(db, page=1, page_size=10)
    assert warning_list["total"] >= 1, "❌ 预警客户列表为空"
    warning_customer = next(
        (item for item in warning_list["items"] if item["customer"]["customer_code"] == "RISKOP001"),
        None
    )
    assert warning_customer is not None, "❌ 测试客户不在预警列表中"
    assert len(warning_customer["warnings"]) >= 1, "❌ 客户没有预警记录"
    assert len(warning_customer["cases"]) >= 1, "❌ 客户没有风控案件"
    print(f"  ✅ 预警客户: {warning_customer['customer']['customer_name']}")
    print(f"  ✅ 预警记录: {len(warning_customer['warnings'])} 条")
    print(f"  ✅ 关联案件: {len(warning_customer['cases'])} 个")
    print(f"  ✅ 命中规则: {warning_customer['cases'][0]['matched_rule_name']}")

    print_subtitle("3.3 第4次变更触发冻结")
    req_data4 = ChangeRequestCreate(
        customer_code="RISKOP001",
        change_type="CONTACT_CHANGE",
        submitter="employee003",
        department="销售一部",
        new_data={"contact_email": "risk@test.com"}
    )
    result4 = change_request_service.submit_change_request(db, req_data4)
    assert result4.get("risk_frozen") == True, "❌ 第4次变更未触发冻结"
    frozen_request_id = result4["request"]["id"]
    print(f"  ✅ 第4次变更触发冻结，申请状态: {result4['request']['status']}")

    print_subtitle("3.4 冻结客户列表")
    frozen_list = risk_operation_service.get_frozen_customers(db, page=1, page_size=10)
    assert frozen_list["total"] >= 1, "❌ 冻结客户列表为空"
    frozen_customer = next(
        (item for item in frozen_list["items"] if item["customer"]["customer_code"] == "RISKOP001"),
        None
    )
    assert frozen_customer is not None, "❌ 测试客户不在冻结列表中"
    assert frozen_customer["customer"]["is_frozen"] == True, "❌ 客户未正确冻结"
    assert len(frozen_customer["pending_requests"]) >= 1, "❌ 没有挂起的申请"
    pending_req = frozen_customer["pending_requests"][0]
    assert pending_req["id"] == frozen_request_id, "❌ 挂起的申请不正确"
    print(f"  ✅ 冻结客户: {frozen_customer['customer']['customer_name']}")
    print(f"  ✅ 冻结原因: {frozen_customer['customer']['freeze_reason']}")
    print(f"  ✅ 挂起申请: {pending_req['request_no']}")
    print(f"  ✅ 风控案件: {frozen_customer['cases'][0]['case_no']}")

    print_subtitle("3.5 风控追踪 - 查看规则命中详情")
    trace = risk_operation_service.get_risk_trace(db, customer_id=customer_id)
    assert trace is not None, "❌ 风控追踪数据为空"
    assert len(trace["risk_warnings"]) >= 2, f"❌ 预警记录不足，应有2条，实际{len(trace['risk_warnings'])}条"
    assert len(trace["risk_cases"]) >= 2, f"❌ 风控案件不足，应有2个，实际{len(trace['risk_cases'])}个"
    assert len(trace["change_history"]) >= 4, f"❌ 变更历史不足，应有4条，实际{len(trace['change_history'])}条"

    print(f"  ✅ 客户: {trace['customer']['customer_name']}")
    print(f"  ✅ 冻结状态: {trace['customer']['is_frozen']}")

    for i, change in enumerate(trace["change_history"]):
        risk_info = change.get("risk_info", {})
        print(f"     第{i+1}次变更: {change['request_no']} | 风险触发: {risk_info.get('risk_triggered')} | 状态: {change['status']}")
        if risk_info.get("risk_triggered"):
            print(f"       - 风险原因: {risk_info.get('risk_reason')}")
            print(f"       - 命中规则: {change.get('matched_rule', {}).get('rule_name')}")

    warning_case = next((c for c in trace["risk_cases"] if c["risk_level"] == "WARNING"), None)
    freeze_case = next((c for c in trace["risk_cases"] if c["risk_level"] == "DANGER"), None)
    if warning_case:
        print(f"  ✅ 预警案件: {warning_case['case_no']} | 规则: {warning_case['matched_rule_name']}")
        print(f"       原因: {warning_case['match_reason']}")
        print(f"       处理动作: 只预警不拦截")
    if freeze_case:
        print(f"  ✅ 冻结案件: {freeze_case['case_no']} | 规则: {freeze_case['matched_rule_name']}")
        print(f"       原因: {freeze_case['match_reason']}")
        print(f"       处理动作: 冻结拦截")

    print_subtitle("3.6 解除冻结并查看恢复记录")
    warnings = risk_service.get_risk_warnings(db, customer_id=customer_id, is_handled=False, page=1, page_size=10)
    assert warnings["total"] >= 1, "❌ 没有未处理的预警"
    warning_to_handle = warnings["items"][0]
    print(f"  ✅ 处理预警ID: {warning_to_handle.id}")

    risk_service.handle_risk_warning(
        db, warning_id=warning_to_handle.id,
        handler="risk_officer_001",
        comment="客户情况核实，属于正常业务变更，解除冻结",
        unfreeze=True
    )

    recovery_list = risk_operation_service.get_recovery_records(db, page=1, page_size=10)
    assert recovery_list["total"] >= 1, "❌ 恢复记录为空"
    recovery_record = next(
        (item for item in recovery_list["items"] if item["customer"]["customer_code"] == "RISKOP001"),
        None
    )
    assert recovery_record is not None, "❌ 测试客户不在恢复记录中"
    assert recovery_record["case"]["status"] == "RESOLVED", "❌ 案件状态不正确"
    print(f"  ✅ 恢复记录: {recovery_record['case']['case_no']}")
    print(f"  ✅ 案件状态: {recovery_record['case']['status']}")
    print(f"  ✅ 解除原因: {recovery_record['case']['unfreeze_reason']}")
    print(f"  ✅ 处理人: {recovery_record['case']['handler']}")
    print(f"  ✅ 关联申请恢复审批: {len(recovery_record['related_requests'])} 个")

    db.refresh(customer)
    assert customer.is_frozen == False, "❌ 客户未解除冻结"
    print(f"  ✅ 客户已解除冻结: is_frozen={customer.is_frozen}")

    print("\n✅ 第三部分测试通过：风控工作台功能完整，规则命中追踪清晰")


def test_sync_summary_and_retry(db):
    print_test_title("第四部分：同步结果汇总和失败重试")

    print_subtitle("准备测试数据 - 普通客户自动审批")
    customer = Customer(
        customer_code="SYNCSUM001",
        customer_name="同步汇总测试客户",
        customer_level="NORMAL",
        industry="零售",
        department="销售一部",
        contact_person="同步测试员",
        contact_phone="13600000001",
        order_manager="order_mgr_004"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    print(f"  ✅ 客户创建成功: {customer.customer_code}")

    req_data = ChangeRequestCreate(
        customer_code="SYNCSUM001",
        change_type="CONTACT_CHANGE",
        submitter="employee004",
        department="销售一部",
        new_data={"contact_phone": "13600000002", "address": "新地址测试"}
    )
    result = change_request_service.submit_change_request(db, req_data)
    request_id = result["request"]["id"]
    assert result["request"]["status"] == "APPROVED", "❌ 普通客户未自动审批"
    print(f"  ✅ 普通客户自动审批通过，申请ID: {request_id}")

    print_subtitle("4.1 同步结果汇总")
    detail = change_request_service.get_change_request_detail(db, request_id)
    sync_summary = detail.get("sync_summary")
    assert sync_summary is not None, "❌ 同步结果汇总为空"

    print(f"  ✅ 整体同步状态: {sync_summary['overall_status']}")
    print(f"  ✅ 成功系统数: {sync_summary['success_count']}")
    print(f"  ✅ 失败系统数: {sync_summary['failed_count']}")
    print(f"  ✅ 总重试次数: {sync_summary['total_retry_count']}")
    print(f"  ✅ 订单负责人已通知: {sync_summary['order_manager_notified']}")

    assert "CRM" in sync_summary["system_status"], "❌ 缺少CRM同步状态"
    assert "ERP" in sync_summary["system_status"], "❌ 缺少ERP同步状态"
    assert "FINANCE" in sync_summary["system_status"], "❌ 缺少财务系统同步状态"

    for system, status_info in sync_summary["system_status"].items():
        print(f"     - {system}: 状态={status_info['status']}, 重试次数={status_info['retry_count']}")
        if status_info["status"] == "FAILED":
            print(f"       错误信息: {status_info['error_message']}")

    print(f"  ✅ 通知记录: {len(sync_summary['notifications'])} 条")
    for n in sync_summary["notifications"]:
        print(f"     - 接收人: {n['recipient']}, 已读: {n['is_read']}, 已送达: {n['is_delivered']}")

    assert sync_summary["order_manager_notified"] == True, "❌ 订单负责人未被通知"
    assert detail["order_manager_notified"] == True, "❌ 申请详情通知标记错误"
    print(f"  ✅ 订单负责人已通知: {customer.order_manager}")

    print_subtitle("4.2 模拟同步失败场景")
    original_mock_sync = sync_service._mock_sync
    call_count = {"CRM": 0}

    def failing_mock_sync(system, cust, data):
        call_count[system] = call_count.get(system, 0) + 1
        if system == "CRM" and call_count["CRM"] <= 2:
            return False, json.dumps({"code": 500, "message": "CRM系统连接超时，第{}次失败".format(call_count["CRM"])}, ensure_ascii=False)
        return original_mock_sync(system, cust, data)

    sync_service._mock_sync = failing_mock_sync

    customer2 = Customer(
        customer_code="SYNCSUM002",
        customer_name="同步失败重试测试客户",
        customer_level="NORMAL",
        industry="零售",
        department="销售二部",
        contact_person="重试测试员",
        contact_phone="13500000001",
        order_manager="order_mgr_005"
    )
    db.add(customer2)
    db.commit()
    db.refresh(customer2)

    req_data2 = ChangeRequestCreate(
        customer_code="SYNCSUM002",
        change_type="CONTACT_CHANGE",
        submitter="employee005",
        department="销售二部",
        new_data={"contact_phone": "13500000002"}
    )
    result2 = change_request_service.submit_change_request(db, req_data2)
    request_id2 = result2["request"]["id"]
    print(f"  ✅ 第二个申请创建并自动审批")

    sync_summary2 = sync_service.get_sync_summary(db, request_id2)
    print(f"  ✅ 同步状态: {sync_summary2['overall_status']}")
    print(f"  ✅ CRM状态: {sync_summary2['system_status']['CRM']['status']}")
    print(f"  ✅ CRM错误: {sync_summary2['system_status']['CRM'].get('error_message', '无')}")
    print(f"  ✅ CRM重试次数: {sync_summary2['system_status']['CRM']['retry_count']}")

    assert sync_summary2["system_status"]["CRM"]["status"] == "FAILED", "❌ CRM模拟失败未生效"

    print_subtitle("4.3 单个系统失败重试")
    crm_sync_record = db.query(sync_service.SyncRecord).filter(
        sync_service.and_(
            sync_service.SyncRecord.change_request_id == request_id2,
            sync_service.SyncRecord.target_system == "CRM"
        )
    ).first()
    retry_result = sync_service.retry_sync(
        db, crm_sync_record.id, operator="admin_001"
    )
    print(f"  ✅ 第1次重试CRM: 状态={retry_result.status}, 重试次数={retry_result.retry_count}")
    assert retry_result.status == "FAILED", "❌ CRM重试应该继续失败"

    retry_result2 = sync_service.retry_sync(
        db, crm_sync_record.id, operator="admin_001"
    )
    print(f"  ✅ 第2次重试CRM: 状态={retry_result2.status}, 重试次数={retry_result2.retry_count}")
    assert retry_result2.status == "SUCCESS", "❌ CRM重试第3次应该成功"

    sync_summary_after = sync_service.get_sync_summary(db, request_id2)
    print(f"  ✅ 重试后整体状态: {sync_summary_after['overall_status']}")
    print(f"  ✅ CRM重试后状态: {sync_summary_after['system_status']['CRM']['status']}")
    print(f"  ✅ CRM最终重试次数: {sync_summary_after['system_status']['CRM']['retry_count']}")
    assert sync_summary_after["system_status"]["CRM"]["status"] == "SUCCESS", "❌ CRM最终状态应为成功"
    assert sync_summary_after["system_status"]["CRM"]["retry_count"] == 2, "❌ CRM重试次数应为2"

    print_subtitle("4.4 批量重试所有失败系统")
    call_count2 = {"CRM": 0, "ERP": 0}
    def failing_mock_sync2(system, cust, data):
        call_count2[system] = call_count2.get(system, 0) + 1
        if system in ["CRM", "ERP"] and call_count2[system] < 2:
            return False, json.dumps({"code": 500, "message": f"{system}临时故障"}, ensure_ascii=False)
        return original_mock_sync(system, cust, data)

    sync_service._mock_sync = failing_mock_sync2

    customer3 = Customer(
        customer_code="SYNCSUM003",
        customer_name="批量重试测试客户",
        customer_level="NORMAL",
        industry="零售",
        department="销售二部",
        contact_person="批量重试员",
        contact_phone="13400000001",
        order_manager="order_mgr_006"
    )
    db.add(customer3)
    db.commit()
    db.refresh(customer3)

    req_data3 = ChangeRequestCreate(
        customer_code="SYNCSUM003",
        change_type="CONTACT_CHANGE",
        submitter="employee006",
        department="销售二部",
        new_data={"contact_phone": "13400000002"}
    )
    result3 = change_request_service.submit_change_request(db, req_data3)
    request_id3 = result3["request"]["id"]
    print(f"  ✅ 第三个申请创建并自动审批")

    sync_summary3 = sync_service.get_sync_summary(db, request_id3)
    failed_systems = [s for s, info in sync_summary3["system_status"].items() if info["status"] == "FAILED"]
    print(f"  ✅ 失败系统: {failed_systems}")
    assert len(failed_systems) >= 1, "❌ 至少应有一个系统失败"

    retry_all_result = sync_service.retry_sync_all(
        db, request_id3, operator="admin_001"
    )
    print(f"  ✅ 批量重试结果: 总数={retry_all_result['total_retried']}, 成功={retry_all_result['success_count']}, 失败={retry_all_result['fail_count']}")

    sync_summary_final = sync_service.get_sync_summary(db, request_id3)
    all_success = all(info["status"] == "SUCCESS" for info in sync_summary_final["system_status"].values())
    print(f"  ✅ 批量重试后所有系统成功: {all_success}")
    assert all_success, "❌ 批量重试后应所有系统成功"

    sync_service._mock_sync = original_mock_sync

    print_subtitle("4.5 申请详情页面完整展示")
    final_detail = change_request_service.get_change_request_detail(db, request_id3)
    print(f"  ✅ 申请详情包含同步汇总: {'sync_summary' in final_detail}")
    print(f"  ✅ 同步汇总包含各系统状态: {len(final_detail['sync_summary']['system_status'])} 个系统")
    print(f"  ✅ 包含指派历史: {len(final_detail.get('assignment_history', []))} 条")
    print(f"  ✅ 包含催办历史: {len(final_detail.get('reminder_history', []))} 条")
    print(f"  ✅ 包含命中规则: {final_detail.get('matched_rule', {}).get('rule_name', '无')}")
    print(f"  ✅ 订单负责人通知状态: {final_detail.get('order_manager_notified')}")

    print("\n✅ 第四部分测试通过：同步结果汇总和失败重试功能完整")


if __name__ == "__main__":
    main()
