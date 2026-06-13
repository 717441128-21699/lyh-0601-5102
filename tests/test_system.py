import sys
import os
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models import Customer, ChangeRequest
from app.schemas import CustomerCreate, ChangeRequestCreate
from app.services import customer_service, change_request_service, approval_service
from app.services import risk_service, sync_service, notification_service, report_service


@pytest.fixture(scope="module")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_customer(db):
    customer_data = CustomerCreate(
        customer_code="TEST001",
        customer_name="测试普通客户有限公司",
        customer_level="NORMAL",
        contact_person="测试员",
        contact_phone="13800000001",
        contact_email="test@test.com",
        address="测试地址",
        industry="测试行业",
        department="测试部门",
        order_manager="测试经理"
    )
    customer = customer_service.create_customer(db, customer_data, "admin")
    assert customer is not None
    assert customer.customer_code == "TEST001"
    assert customer.customer_level == "NORMAL"
    assert customer.is_frozen is False
    print("✓ 创建普通客户测试通过")


def test_create_vip_customer(db):
    customer_data = CustomerCreate(
        customer_code="TEST002",
        customer_name="测试VIP客户有限公司",
        customer_level="VIP",
        contact_person="VIP测试员",
        contact_phone="13900000002",
        contact_email="vip@test.com",
        address="VIP测试地址",
        industry="VIP行业",
        department="VIP部门",
        order_manager="VIP经理"
    )
    customer = customer_service.create_customer(db, customer_data, "admin")
    assert customer is not None
    assert customer.customer_level == "VIP"
    print("✓ 创建VIP客户测试通过")


def test_submit_normal_customer_change_auto_approve(db):
    new_data = {
        "contact_phone": "13800000099",
        "address": "新地址更新"
    }
    request_data = ChangeRequestCreate(
        customer_code="TEST001",
        change_type="BASIC_INFO",
        submitter="测试员工",
        department="测试部门",
        new_data=new_data
    )
    request = change_request_service.submit_change_request(db, request_data)
    assert request is not None
    assert request.status == "APPROVED"
    assert request.approver == "SYSTEM_AUTO"
    assert request.sync_status == "SUCCESS"
    assert request.risk_triggered is False

    customer = customer_service.get_customer(db, request.customer_id)
    assert customer.contact_phone == "13800000099"
    assert customer.address == "新地址更新"
    print("✓ 普通客户变更自动审批测试通过")


def test_submit_vip_customer_change_pending(db):
    new_data = {
        "contact_person": "新VIP联系人",
        "contact_email": "new_vip@test.com"
    }
    request_data = ChangeRequestCreate(
        customer_code="TEST002",
        change_type="CONTACT_INFO",
        submitter="测试员工",
        department="VIP部门",
        new_data=new_data
    )
    request = change_request_service.submit_change_request(db, request_data)
    assert request is not None
    assert request.status == "PENDING"
    assert request.approval_level == "REGIONAL_MANAGER"
    assert request.approver is None
    print("✓ VIP客户变更待审批测试通过")


def test_vip_customer_manual_approve(db):
    pending_requests = change_request_service.query_change_requests(
        db,
        change_request_service.ChangeRequestQuery(
            customer_name="VIP",
            status="PENDING",
            page=1,
            page_size=10
        )
    )
    assert pending_requests["total"] > 0

    request_id = pending_requests["items"][0].id
    approved = approval_service.manual_approve(
        db, request_id, "区域经理A", "同意变更"
    )

    assert approved.status == "APPROVED"
    assert approved.approver == "区域经理A"
    assert approved.approval_comment == "同意变更"
    assert approved.sync_status == "SUCCESS"

    customer = customer_service.get_customer(db, approved.customer_id)
    assert customer.contact_person == "新VIP联系人"
    print("✓ VIP客户人工审批测试通过")


def test_change_diff_calculation(db):
    new_data = {
        "contact_phone": "13811111111"
    }
    request_data = ChangeRequestCreate(
        customer_code="TEST001",
        change_type="PHONE_CHANGE",
        submitter="测试员工2",
        department="测试部门",
        new_data=new_data
    )
    request = change_request_service.submit_change_request(db, request_data)

    diff_data = change_request_service.json_to_dict(request.diff_data)
    assert len(diff_data) == 1
    assert diff_data[0]["field"] == "contact_phone"
    assert diff_data[0]["new_value"] == "13811111111"
    print("✓ 变更差异计算测试通过")


def test_risk_warning_3changes_30days(db):
    risk_customer_data = CustomerCreate(
        customer_code="TEST_RISK",
        customer_name="风控测试客户有限公司",
        customer_level="NORMAL",
        contact_person="风控测试员",
        contact_phone="13600000001",
        contact_email="risk@test.com",
        address="风控测试地址",
        industry="风控行业",
        department="风控部门",
        order_manager="风控经理"
    )
    risk_customer = customer_service.create_customer(db, risk_customer_data, "admin")

    for i in range(2):
        new_data = {
            "contact_phone": f"1360000000{i + 2}"
        }
        request_data = ChangeRequestCreate(
            customer_code="TEST_RISK",
            change_type=f"RISK_TEST_{i}",
            submitter=f"风控测试员{i}",
            department="风控部门",
            new_data=new_data
        )
        change_request_service.submit_change_request(db, request_data)

    change_count = change_request_service.get_change_count_30d(db, risk_customer.id)
    print(f"当前30天变更次数: {change_count}")

    new_data = {
        "contact_phone": "13600000099"
    }
    request_data = ChangeRequestCreate(
        customer_code="TEST_RISK",
        change_type="RISK_TRIGGER",
        submitter="风险测试员",
        department="风控部门",
        new_data=new_data
    )

    request = change_request_service.submit_change_request(db, request_data)
    assert request.risk_triggered is True
    assert "30天内变更" in request.risk_reason
    assert request.status == "RISK_HOLD"
    assert request.sync_status == "BLOCKED"

    customer = customer_service.get_customer(db, request.customer_id)
    assert customer.is_frozen is True
    assert "触发风控冻结" in customer.freeze_reason
    print("✓ 30天3次变更触发风控预警测试通过")


def test_sync_records_created(db):
    records = sync_service.get_sync_records(db, change_request_id=1, page=1, page_size=10)
    assert records["total"] == 3
    systems = [r.target_system for r in records["items"]]
    assert "CRM" in systems
    assert "ERP" in systems
    assert "FINANCE" in systems

    for record in records["items"]:
        assert record.status == "SUCCESS"
        assert record.synced_at is not None
    print("✓ 多系统同步记录测试通过")


def test_notifications_created(db):
    notifications = notification_service.get_user_notifications(
        db, recipient="测试员工", page=1, page_size=10
    )
    assert notifications["total"] > 0

    unread_count = notification_service.get_unread_count(db, "测试员工")
    assert unread_count > 0
    print("✓ 通知推送测试通过")


def test_query_change_requests(db):
    result = change_request_service.query_change_requests(
        db,
        change_request_service.ChangeRequestQuery(
            customer_name="测试",
            status="APPROVED",
            page=1,
            page_size=10
        )
    )
    assert result["total"] > 0
    assert len(result["items"]) <= 10
    print("✓ 变更申请组合查询测试通过")


def test_daily_report_generation(db):
    from datetime import date
    report = report_service.generate_daily_report(db, report_date=date.today())
    assert report is not None
    assert report.total_requests > 0
    assert report.approval_rate >= 0
    assert report.sync_success_rate >= 0
    assert report.pdf_path is not None
    assert report.excel_path is not None
    assert os.path.exists(report.pdf_path)
    assert os.path.exists(report.excel_path)
    print("✓ 每日报告生成测试通过")


def test_7day_trend(db):
    trend = report_service.get_7day_trend(db)
    assert len(trend) == 7
    assert "date" in trend[0]
    assert "total_requests" in trend[0]
    print("✓ 7日趋势数据测试通过")


def test_export_change_requests(db):
    from app.services.export_service import export_change_requests_excel
    from app.schemas import ChangeRequestQuery

    query = ChangeRequestQuery(
        customer_name="测试",
        page=1,
        page_size=100
    )
    filepath = export_change_requests_excel(db, query)
    assert os.path.exists(filepath)
    assert filepath.endswith(".xlsx")
    print("✓ 变更申请导出测试通过")


def test_handle_risk_warning(db):
    risk_customer = change_request_service.get_customer_by_code(db, "TEST_RISK")
    warnings = risk_service.get_risk_warnings(
        db, customer_id=risk_customer.id, page=1, page_size=10
    )
    assert warnings["total"] > 0

    warning_id = warnings["items"][0].id
    handled = risk_service.handle_risk_warning(
        db, warning_id, "风控专员", "已核实，解除冻结", unfreeze=True
    )

    assert handled.is_handled is True
    assert handled.handled_by == "风控专员"

    customer = customer_service.get_customer(db, handled.customer_id)
    assert customer.is_frozen is False
    print("✓ 风控预警处理测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("开始运行客户主数据变更管理系统测试")
    print("=" * 60)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        test_create_customer(db)
        test_create_vip_customer(db)
        test_submit_normal_customer_change_auto_approve(db)
        test_submit_vip_customer_change_pending(db)
        test_vip_customer_manual_approve(db)
        test_change_diff_calculation(db)
        test_risk_warning_3changes_30days(db)
        test_sync_records_created(db)
        test_notifications_created(db)
        test_query_change_requests(db)
        test_daily_report_generation(db)
        test_7day_trend(db)
        test_export_change_requests(db)
        test_handle_risk_warning(db)

        print("=" * 60)
        print("所有测试通过！")
        print("=" * 60)
    finally:
        db.close()
