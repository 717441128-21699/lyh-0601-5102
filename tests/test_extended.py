import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from app.database import SessionLocal, engine, Base
from app.models import Customer, ChangeRequest
from app.schemas import CustomerCreate, ChangeRequestCreate
from app.services import (
    customer_service,
    change_request_service,
    approval_service,
    approval_rule_service,
    risk_service,
    report_service
)
from app.scripts import init_approval_data


def run_extended_tests():
    print("=" * 60)
    print("扩展功能测试 - 审批链、待办中心、风控、报表深化")
    print("=" * 60)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("\n【1】初始化审批规则...")
        init_approval_data.init_default_approval_rules(db)
        rules = approval_rule_service.list_approval_rules(db)
        print(f"✓ 已加载 {len(rules)} 条审批规则")

        chains = approval_rule_service.list_approval_chains(db)
        print(f"✓ 已加载 {len(chains)} 条审批链")

        print("\n【2】创建测试客户...")
        normal_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="EXT001",
                customer_name="扩展测试普通客户",
                customer_level="NORMAL",
                contact_person="测试员A",
                contact_phone="13800000001",
                contact_email="a@test.com",
                address="测试地址",
                industry="信息技术",
                department="销售一部",
                order_manager="李经理"
            ),
            "admin"
        )
        print(f"✓ 创建普通客户: {normal_customer.customer_name}")

        vip_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="EXT002",
                customer_name="扩展测试VIP客户",
                customer_level="VIP",
                contact_person="测试员B",
                contact_phone="13900000002",
                contact_email="b@test.com",
                address="VIP测试地址",
                industry="金融",
                department="销售二部",
                order_manager="王总监"
            ),
            "admin"
        )
        print(f"✓ 创建VIP客户: {vip_customer.customer_name} (金融行业)")

        print("\n【3】测试普通客户自动审批规则匹配...")
        result = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="EXT001",
                change_type="BASIC_INFO",
                submitter="员工A",
                department="销售一部",
                new_data={"contact_phone": "13811111111"}
            ),
            priority="NORMAL"
        )

        assert result["risk_triggered"] == False
        assert result["approval_flow"] is not None
        assert result["request"]["status"] == "APPROVED"
        assert result["approval_flow"]["matched_rule"] == "普通客户自动审批"
        print(f"✓ 命中规则: {result['approval_flow']['matched_rule']}")
        print(f"✓ 匹配原因: {result['approval_flow']['match_reason']}")
        print(f"✓ 审批链: {result['approval_flow']['chain_name']}")
        print(f"✓ 总节点数: {result['approval_flow']['total_nodes']}")
        print(f"✓ 申请状态: {result['request']['status']}")

        print("\n【4】测试VIP客户+金融行业 - 匹配高优先级规则...")
        result2 = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="EXT002",
                change_type="BASIC_INFO",
                submitter="员工B",
                department="销售二部",
                new_data={"contact_phone": "13922222222"}
            ),
            priority="HIGH"
        )

        assert result2["request"]["status"] == "PENDING"
        assert result2["approval_flow"] is not None
        print(f"✓ 命中规则: {result2['approval_flow']['matched_rule']}")
        print(f"✓ 匹配原因: {result2['approval_flow']['match_reason']}")
        print(f"✓ 审批链: {result2['approval_flow']['chain_name']}")
        print(f"✓ 总节点数: {result2['approval_flow']['total_nodes']}")
        print(f"✓ 当前节点: 第 {result2['approval_flow']['current_node_index'] + 1} 级")
        print(f"✓ 下一步处理人角色: {result2['approval_flow']['next_approver']['approver_role']}")
        print(f"✓ 超时时限: {result2['approval_flow']['next_approver']['timeout_hours']} 小时")
        print(f"✓ 优先级: {result2['request']['priority']}")

        print("\n【5】测试审批待办中心...")
        todo_stats = approval_service.get_todo_stats(db, role="REGIONAL_MANAGER")
        print(f"✓ 区域经理待办统计: {todo_stats}")

        todo_list = approval_service.get_my_todo(
            db, role="REGIONAL_MANAGER", page=1, page_size=10
        )
        print(f"✓ 区域经理待办列表: 共 {todo_list['total']} 条")

        todo_list_priority = approval_service.get_my_todo(
            db, role="REGIONAL_MANAGER", priority="HIGH", page=1, page_size=10
        )
        print(f"✓ 高优先级待办: {todo_list_priority['total']} 条")

        print("\n【6】测试多级审批流程...")
        request_id = result2["request"]["id"]
        approved = approval_service.approve_request(
            db, request_id, "区域经理张三", "一级审批通过"
        )

        detail = change_request_service.get_change_request_detail(db, request_id)
        print(f"✓ 一级审批后状态: {detail['status']}")
        print(f"✓ 当前节点索引: {detail['current_node_index']}")
        print(f"✓ 审批记录数: {len(detail['approval_records'])}")

        if detail["status"] == "PENDING":
            print("  → 还有下一级审批，继续审批...")
            approved2 = approval_service.approve_request(
                db, request_id, "总监李四", "二级审批通过"
            )
            detail2 = change_request_service.get_change_request_detail(db, request_id)
            print(f"✓ 二级审批后状态: {detail2['status']}")

            if detail2["status"] == "PENDING":
                approved3 = approval_service.approve_request(
                    db, request_id, "总裁王五", "三级审批通过"
                )
                detail3 = change_request_service.get_change_request_detail(db, request_id)
                print(f"✓ 三级审批后状态: {detail3['status']}")
                print(f"✓ 全部审批通过!")

        print("\n【7】测试批量审批...")
        for i in range(3):
            change_request_service.submit_change_request(
                db,
                ChangeRequestCreate(
                    customer_code="EXT002",
                    change_type=f"BATCH_TEST_{i}",
                    submitter=f"员工{i}",
                    department="销售二部",
                    new_data={"contact_email": f"batch{i}@test.com"}
                ),
                priority="NORMAL"
            )

        pending = approval_service.get_my_todo(
            db, role="REGIONAL_MANAGER", page=1, page_size=20
        )
        pending_ids = [r.id for r in pending["items"][:3]]
        print(f"✓ 获取 {len(pending_ids)} 条待办用于批量测试")

        batch_result = approval_service.batch_approve(
            db, pending_ids, "批量审批人", "批量通过"
        )
        print(f"✓ 批量审批结果: 成功 {batch_result['success_count']} 条, 失败 {batch_result['fail_count']} 条")

        print("\n【8】测试快捷查询（最近7天/30天）...")
        result_7d = change_request_service.query_change_requests_quick(
            db, quick_range="7d", page=1, page_size=10
        )
        print(f"✓ 最近7天申请数: {result_7d['total']}")

        result_30d = change_request_service.query_change_requests_quick(
            db, quick_range="30d", page=1, page_size=10
        )
        print(f"✓ 最近30天申请数: {result_30d['total']}")

        print("\n【9】测试风控规则 - 超过阈值才拦截（第4次才冻结）...")
        risk_customer = customer_service.create_customer(
            db,
            CustomerCreate(
                customer_code="EXTRISK001",
                customer_name="风控测试客户",
                customer_level="NORMAL",
                contact_person="风控测试",
                contact_phone="13700000001",
                contact_email="risk@test.com",
                address="风控测试地址",
                industry="测试行业",
                department="风控部门",
                order_manager="风控经理"
            ),
            "admin"
        )

        for i in range(3):
            result_r = change_request_service.submit_change_request(
                db,
                ChangeRequestCreate(
                    customer_code="EXTRISK001",
                    change_type=f"RISK_TEST_{i}",
                    submitter=f"风控测试员{i}",
                    department="风控部门",
                    new_data={"contact_phone": f"1370000000{i + 2}"}
                )
            )
            print(f"  第{i+1}次提交: 状态={result_r['request']['status']}, 风控触发={result_r['risk_triggered']}")

        risk_status = risk_service.get_customer_risk_status(db, risk_customer.id)
        print(f"\n✓ 3次变更后风控状态: {risk_status['status']}")
        print(f"  - 30天变更数: {risk_status['change_count_30d']}")
        print(f"  - 风控阈值: {risk_status['risk_threshold']}")
        print(f"  - 剩余可用次数: {risk_status['remaining_changes']}")
        print(f"  - 是否已冻结: {risk_status['is_frozen']}")

        print("\n第4次提交 - 应该触发冻结...")
        result_r4 = change_request_service.submit_change_request(
            db,
            ChangeRequestCreate(
                customer_code="EXTRISK001",
                change_type="RISK_TRIGGER",
                submitter="风控测试员3",
                department="风控部门",
                new_data={"contact_phone": "13799999999"}
            )
        )
        print(f"✓ 第4次提交: 风控触发={result_r4['risk_triggered']}")
        print(f"  申请状态: {result_r4['request']['status']}")
        print(f"  风控原因: {result_r4['risk_reason']}")

        risk_status2 = risk_service.get_customer_risk_status(db, risk_customer.id)
        print(f"✓ 4次变更后风控状态: {risk_status2['status']}")
        print(f"  - 是否已冻结: {risk_status2['is_frozen']}")

        print("\n【10】测试风控解除后恢复审批流程...")
        warnings = risk_service.get_risk_warnings(db, customer_id=risk_customer.id)
        warning_id = warnings["items"][0].id
        print(f"✓ 找到风控预警: {warning_id}")

        handled = risk_service.handle_risk_warning(
            db, warning_id, "风控专员", "已核实，解除冻结", unfreeze=True
        )
        print(f"✓ 预警处理完成: is_handled={handled.is_handled}")

        risk_status3 = risk_service.get_customer_risk_status(db, risk_customer.id)
        print(f"✓ 解除后风控状态: {risk_status3['status']}")
        print(f"  - 是否已冻结: {risk_status3['is_frozen']}")

        risk_hold_requests = db.query(ChangeRequest).filter(
            ChangeRequest.customer_id == risk_customer.id,
            ChangeRequest.status == "RISK_HOLD"
        ).count()
        print(f"✓ 剩余风控暂停申请数: {risk_hold_requests} (应该为0，已自动恢复)")

        pending_after = db.query(ChangeRequest).filter(
            ChangeRequest.customer_id == risk_customer.id,
            ChangeRequest.status == "PENDING"
        ).count()
        print(f"✓ 恢复为待审批的申请数: {pending_after}")

        print("\n【11】测试日报生成（含各部门详细统计）...")
        from datetime import date
        report = report_service.generate_daily_report(db, report_date=date.today())
        print(f"✓ 日报生成完成: {report.report_date}")
        print(f"  - 总申请数: {report.total_requests}")
        print(f"  - 通过数: {report.approved_count}")
        print(f"  - 通过率: {report.approval_rate}%")
        print(f"  - 风控预警数: {report.risk_warning_count}")
        print(f"  - 超时申请数: {report.overdue_count}")

        from app.services.utils import json_to_dict
        dept_stats = json_to_dict(report.department_stats)
        print(f"✓ 涉及部门数: {len(dept_stats)}")
        for dept, stats in list(dept_stats.items())[:3]:
            print(f"  - {dept}: 申请{stats['total']}件, 通过率{stats['approval_rate']}%, "
                  f"同步成功率{stats['sync_success_rate']}%, "
                  f"平均时长{stats['avg_processing_hours']}h, "
                  f"超时{stats['overdue_count']}件")

        print("\n【12】测试趋势数据（7天/30天）...")
        trend_7d = report_service.get_7day_trend(db)
        print(f"✓ 7日趋势数据: {len(trend_7d)} 天")
        print(f"  最近1天: 申请{trend_7d[-1]['total_requests']}件, "
              f"通过{trend_7d[-1]['approved_count']}件")

        trend_30d = report_service.get_30day_trend(db)
        print(f"✓ 30日趋势数据: {len(trend_30d)} 天")

        print("\n【13】测试审批流程记录查询...")
        req_id = result2["request"]["id"]
        records = approval_service.get_approval_records(db, req_id)
        print(f"✓ 申请 {req_id} 的审批记录: {len(records)} 条")
        for r in records:
            print(f"  - {r.node_name}: {r.action} by {r.approver or '待处理'}")

        print("\n【14】测试首页统计...")
        dashboard = change_request_service.get_dashboard_stats(db, approver=None)
        print(f"✓ 首页统计:")
        print(f"  - 今日提交: {dashboard['today_submitted']}")
        print(f"  - 今日通过: {dashboard['today_approved']}")
        print(f"  - 待办总数: {dashboard['todo_stats']['total_todo']}")
        print(f"  - 今日待办: {dashboard['todo_stats']['today_todo']}")
        print(f"  - 超时待办: {dashboard['todo_stats']['overdue_count']}")
        print(f"  - 高优先级待办: {dashboard['todo_stats']['high_priority_count']}")

        print("\n" + "=" * 60)
        print("所有扩展测试通过！")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    run_extended_tests()
