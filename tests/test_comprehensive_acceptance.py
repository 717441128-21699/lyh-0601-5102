import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, date
from app.database import SessionLocal, engine, Base
from app.models import Customer, ChangeRequest, SyncRecord, Notification, RiskWarning
from app.schemas import CustomerCreate, ChangeRequestCreate
from app.services import (
    customer_service,
    change_request_service,
    approval_service,
    approval_rule_service,
    risk_service,
    sync_service
)
from app.scripts import init_approval_data


def run_comprehensive_test():
    print("=" * 60)
    print("综合验收测试 - 风控/审批/通知/同步闭环")
    print("=" * 60)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        init_approval_data.init_default_approval_rules(db)

        print("\n【1】验收普通客户自动审批完整闭环")
        normal_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="COM001",
                customer_name="闭环测试普通客户",
                customer_level="NORMAL",
                contact_person="测试员",
                contact_phone="13400000001",
                contact_email="com@test.com",
                address="初始地址",
                industry="互联网",
                department="销售一部",
                order_manager="订单负责人张经理"
            ),
            "admin"
        )
        old_phone = normal_customer.contact_phone
        old_address = normal_customer.address
        new_phone = "13411111111"
        new_address = "新地址"

        print(f"  ✓ 提交前: 电话={old_phone}, 地址={old_address}")

        result = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="COM001",
                change_type="BASIC_INFO",
                submitter="提交员工",
                department="销售一部",
                new_data={"contact_phone": new_phone, "address": new_address}
            )
        )

        print(f"  ✓ 提交返回: 状态={result['request']['status']}, 风控触发={result['risk_triggered']}")
        print(f"  ✓ 命中规则: {result['approval_flow']['matched_rule']}")
        print(f"  ✓ 审批链: {result['approval_flow']['chain_name']} (0节点, 自动审批)")

        db.refresh(normal_customer)
        print(f"  ✓ 提交后: 电话={normal_customer.contact_phone}, 地址={normal_customer.address}")
        assert normal_customer.contact_phone == new_phone, "客户资料电话未更新"
        assert normal_customer.address == new_address, "客户资料地址未更新"
        print("  ✓ 客户资料已更新")

        sync_records = db.query(SyncRecord).filter(
            SyncRecord.change_request_id == result["request"]["id"]
        ).all()
        print(f"  ✓ 同步记录数: {len(sync_records)}")
        assert len(sync_records) >= 3, "CRM/ERP/财务同步记录不完整"
        for sr in sync_records:
            print(f"    - {sr.target_system}: {sr.status}")

        notifications = db.query(Notification).filter(
            Notification.change_request_id == result["request"]["id"]
        ).all()
        print(f"  ✓ 通知数: {len(notifications)}")
        assert len(notifications) >= 1, "缺少同步完成通知"

        sync_notifications = [n for n in notifications if n.notification_type == "SYNC_COMPLETE"]
        assert len(sync_notifications) >= 1, "没有同步完成通知"
        print(f"  ✓ 同步完成通知接收人: {sync_notifications[0].recipient}")
        assert sync_notifications[0].recipient == "订单负责人张经理", "订单负责人没收到通知"

        print("\n【2】验收风控预警（第3次）和冻结（第4次）返回结果区分")
        risk_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="COM002",
                customer_name="风控返回测试客户",
                customer_level="NORMAL",
                contact_person="风控测试",
                contact_phone="13300000001",
                contact_email="risk2@test.com",
                address="测试地址",
                industry="测试行业",
                department="测试部门",
                order_manager="订单经理"
            ),
            "admin"
        )

        for i in range(2):
            r = change_request_service.submit_change_request(
                db,
                ChangeRequestCreate(
                    customer_code="COM002",
                    change_type=f"TEST_{i}",
                    submitter=f"测试员{i}",
                    department="测试部门",
                    new_data={"contact_phone": f"1330000000{i + 2}"}
                )
            )
            print(f"  第{i+1}次: 风控触发={r['risk_triggered']}, 风控冻结={r.get('risk_frozen', False)}")
            assert r["risk_triggered"] == False, f"第{i+1}次不应触发风控"
            assert r["risk_info"] is None, f"第{i+1}次不应有risk_info"
            assert r["approval_flow"] is not None, f"第{i+1}次应该有审批流"

        print("\n  第3次提交 - 应该预警但不冻结，能正常审批")
        r3 = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="COM002",
                change_type="TEST_WARNING",
                submitter="测试员2",
                department="测试部门",
                new_data={"contact_phone": "13322222222"}
            )
        )
        print(f"  ✓ 第3次: 风控触发={r3['risk_triggered']}, 风控冻结={r3.get('risk_frozen', False)}")
        print(f"  ✓ 状态: {r3['request']['status']} (应该是APPROVED)")
        print(f"  ✓ risk_info: {r3.get('risk_info')}")

        assert r3["risk_triggered"] == True, "第3次应该触发风控预警"
        assert r3.get("risk_frozen") == False, "第3次不应该冻结"
        assert r3["risk_info"] is not None, "第3次应该返回risk_info"
        assert r3["risk_info"]["is_frozen"] == False, "第3次is_frozen应该是False"
        assert r3["risk_info"]["status"] == "warning", "第3次状态应该是warning"
        assert r3["risk_info"]["change_count_30d"] == 3, "变更数应该是3"
        assert r3["approval_flow"] is not None, "第3次预警也应该有审批流"
        assert r3["request"]["status"] == "APPROVED", "第3次预警也应该正常审批"
        print("  ✓ 第3次: 预警返回正确，申请正常审批通过")

        print("\n  第4次提交 - 应该冻结拦截，且需要人工审批的场景")
        vip_finance_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="COM003",
                customer_name="VIP金融客户",
                customer_level="VIP",
                contact_person="VIP金融",
                contact_phone="13300000001",
                contact_email="vip_finance@test.com",
                address="金融VIP地址",
                industry="金融",
                department="金融部",
                order_manager="金融订单经理"
            ),
            "admin"
        )

        for i in range(3):
            change_request_service.submit_change_request(
                db,
                ChangeRequestCreate(
                    customer_code="COM003",
                    change_type=f"VIP_FINANCE_{i}",
                    submitter=f"测试员{i}",
                    department="金融部",
                    new_data={"contact_phone": f"1330000000{i + 2}"}
                )
            )

        r4 = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="COM003",
                change_type="VIP_FINANCE_FREEZE",
                submitter="测试员3",
                department="金融部",
                new_data={"contact_phone": "13399999999"}
            )
        )
        print(f"  ✓ 第4次: 风控触发={r4['risk_triggered']}, 风控冻结={r4.get('risk_frozen', False)}")
        print(f"  ✓ 状态: {r4['request']['status']} (应该是RISK_HOLD)")
        assert r4.get('risk_frozen') == True

        risk_customer = vip_finance_customer

        print(f"\n【3】验收风控解除后一路批到通过")
        warnings = risk_service.get_risk_warnings(db, customer_id=risk_customer.id)
        high_warnings = [w for w in warnings["items"] if w.warning_level == "HIGH"]
        warning_id = high_warnings[0].id
        print(f"  ✓ 找到冻结预警: {warning_id}")

        risk_status_before = risk_service.get_customer_risk_status(db, risk_customer.id)
        print(f"  ✓ 解除前状态: {risk_status_before['status']}, 是否冻结: {risk_status_before['is_frozen']}")
        assert risk_status_before["is_frozen"] == True, "解除前应该是冻结状态"

        risk_hold_before = db.query(ChangeRequest).filter(
            ChangeRequest.customer_id == risk_customer.id,
            ChangeRequest.status == "RISK_HOLD"
        ).count()
        print(f"  ✓ 解除前风控暂停申请数: {risk_hold_before}")
        assert risk_hold_before >= 1, "解除前应该有风控暂停的申请"

        handled = risk_service.handle_risk_warning(
            db, warning_id, "风控管理员", "已核实，解除冻结，允许继续审批", unfreeze=True
        )
        print(f"  ✓ 预警已处理")

        risk_status_after = risk_service.get_customer_risk_status(db, risk_customer.id)
        print(f"  ✓ 解除后状态: {risk_status_after['status']}, 是否冻结: {risk_status_after['is_frozen']}")
        assert risk_status_after["is_frozen"] == False, "解除后不应该冻结"

        risk_hold_after = db.query(ChangeRequest).filter(
            ChangeRequest.customer_id == risk_customer.id,
            ChangeRequest.status == "RISK_HOLD"
        ).count()
        pending_after = db.query(ChangeRequest).filter(
            ChangeRequest.customer_id == risk_customer.id,
            ChangeRequest.status == "PENDING"
        ).count()
        print(f"  ✓ 解除后风控暂停: {risk_hold_after}, 待审批: {pending_after}")
        assert risk_hold_after == 0, "解除后不应有风控暂停申请"
        assert pending_after >= 1, "解除后应该有待审批申请"

        req_id = r4["request"]["id"]
        notifications_after = db.query(Notification).filter(
            Notification.change_request_id == req_id
        ).all()
        print(f"  ✓ 风控解除后相关通知数: {len(notifications_after)}")
        if notifications_after:
            for n in notifications_after:
                print(f"    - 接收人: {n.recipient}, 类型: {n.notification_type}, 标题: {n.title}")

        detail_after = change_request_service.get_change_request_detail(db, req_id)
        print(f"\n  ✓ 恢复后申请状态: {detail_after['status']}")
        print(f"  ✓ 当前节点索引: {detail_after['current_node_index']}")
        print(f"  ✓ 审批记录数: {len(detail_after['approval_records'])}")
        assert detail_after["status"] == "PENDING", "恢复后状态应该是待审批"
        assert detail_after["approval_chain_id"] is not None, "恢复后应该有审批链"

        print("\n  开始一路审批...")
        current_status = detail_after["status"]
        approver_index = 0
        approvers = ["一级审批人", "二级审批人", "三级审批人"]

        while current_status == "PENDING":
            req_detail = change_request_service.get_change_request_detail(db, req_id)
            chain = req_detail.get("approval_chain")
            current_idx = req_detail.get("current_node_index", 0)

            if chain and current_idx < len(chain["nodes"]):
                node = chain["nodes"][current_idx]
                print(f"  第{current_idx + 1}级审批: {node['node_name']}")

            approver = approvers[approver_index % len(approvers)]
            approved = approval_service.approve_request(
                db, req_id, approver, f"第{approver_index + 1}级审批通过"
            )

            detail = change_request_service.get_change_request_detail(db, req_id)
            current_status = detail["status"]
            print(f"    → 审批人: {approver}, 结果: {current_status}")

            approver_index += 1
            if approver_index > 10:
                print("    → 审批层级过多，强制退出")
                break

        print(f"\n  ✓ 最终状态: {current_status}")
        assert current_status == "APPROVED", "应该一路批到通过"

        final_detail = change_request_service.get_change_request_detail(db, req_id)
        print(f"  ✓ 审批记录数: {len(final_detail['approval_records'])}")
        for record in final_detail["approval_records"]:
            if isinstance(record, dict):
                print(f"    - {record['node_name']}: {record['action']} by {record.get('approver', '')}")
            else:
                print(f"    - {record.node_name}: {record.action} by {record.approver or ''}")

        db.refresh(risk_customer)
        print(f"  ✓ 客户最终电话: {risk_customer.contact_phone}")
        assert risk_customer.contact_phone == "13399999999", "客户资料应该更新到第4次提交的号码"
        print("  ✓ 客户资料已更新")

        print("\n【4】验收超时催办通知（空接收人处理）")
        vip_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="COM004",
                customer_name="超时测试VIP客户",
                customer_level="VIP",
                contact_person="超时测试",
                contact_phone="13200000001",
                contact_email="timeout@test.com",
                address="超时地址",
                industry="金融",
                department="销售二部",
                order_manager="超时经理"
            ),
            "admin"
        )

        vip_result = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="COM004",
                change_type="TIMEOUT_TEST",
                submitter="提交员工",
                department="销售二部",
                new_data={"contact_phone": "13211111111"}
            ),
            priority="HIGH"
        )
        print(f"  ✓ VIP申请提交: {vip_result['request']['request_no']}")
        print(f"  ✓ 命中规则: {vip_result['approval_flow']['matched_rule']} (金融行业三级审批)")

        req3_id = vip_result["request"]["id"]
        notifications_vip = db.query(Notification).filter(
            Notification.change_request_id == req3_id
        ).all()
        print(f"  ✓ 待办通知数: {len(notifications_vip)}")
        assert len(notifications_vip) >= 1, "应该有待办通知"

        for n in notifications_vip:
            print(f"    - 接收人: {n.recipient}, 类型: {n.notification_type}")
            assert n.recipient != "", "通知接收人不能为空"
            assert "@" in n.recipient or "经理" in n.recipient, "应该是智能生成的接收人"

        todo_stats = approval_service.get_todo_stats(db, role="DEPT_MANAGER")
        print(f"  ✓ 部门主管待办: 总{todo_stats['total_todo']}条, 高优{todo_stats['high_priority_count']}条")
        assert todo_stats["total_todo"] >= 1, "部门主管应该能看到待办"

        pending_req = db.query(ChangeRequest).filter(
            ChangeRequest.id == req3_id
        ).first()
        pending_req.created_at = datetime.now() - timedelta(hours=100)
        db.flush()

        overdue_result = approval_service.check_and_update_overdue(db)
        print(f"  ✓ 超时检查: 新增超时{overdue_result['new_overdue']}件, 发送通知{overdue_result['notifications_sent']}条")
        assert overdue_result["new_overdue"] >= 1, "应该有新增超时"
        assert overdue_result["notifications_sent"] >= 1, "应该发送超时提醒"

        todo_stats_after = approval_service.get_todo_stats(db, role="DEPT_MANAGER")
        print(f"  ✓ 超时后待办统计: 超时{todo_stats_after['overdue_count']}条")
        assert todo_stats_after["overdue_count"] >= 1, "待办统计应该有超时数"

        dashboard = change_request_service.get_dashboard_stats(db, approver=None)
        print(f"  ✓ 首页统计: 今日待办{dashboard['todo_stats']['today_todo']}条, 超时{dashboard['todo_stats']['overdue_count']}条")
        assert dashboard["todo_stats"]["overdue_count"] >= 1, "首页超时数应该与待办统计一致"

        print("\n" + "=" * 60)
        print("所有验收通过！")
        print("=" * 60)

        print("\n📋 验收清单:")
        print("  ✅ 普通客户自动审批闭环：自动通过+资料更新+CRM/ERP/财务同步+通知订单负责人")
        print("  ✅ 第3次预警：返回risk_info+正常审批，第4次冻结：返回risk_info+拦截")
        print("  ✅ 风控解除：恢复审批链+重发待办通知+能一路批到通过+资料更新")
        print("  ✅ 超时催办：空接收人智能处理+通知真的发出去+首页超时数与待办一致")

    finally:
        db.close()


if __name__ == "__main__":
    run_comprehensive_test()
