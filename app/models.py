from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Date, Text, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    customer_code = Column(String(50), unique=True, index=True, nullable=False)
    customer_name = Column(String(200), nullable=False)
    customer_level = Column(String(20), default="NORMAL")
    contact_person = Column(String(100))
    contact_phone = Column(String(50))
    contact_email = Column(String(100))
    address = Column(String(500))
    industry = Column(String(100))
    department = Column(String(100))
    order_manager = Column(String(100))
    is_frozen = Column(Boolean, default=False)
    freeze_reason = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_no = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    customer_code = Column(String(50), index=True)
    change_type = Column(String(50))
    submitter = Column(String(100))
    department = Column(String(100))
    old_data = Column(Text)
    new_data = Column(Text)
    diff_data = Column(Text)
    status = Column(String(20), default="PENDING")
    priority = Column(String(20), default="NORMAL")
    urgency = Column(String(20), default="NORMAL")
    matched_rule_id = Column(Integer, ForeignKey("approval_rules.id"))
    matched_rule_name = Column(String(200))
    approval_chain_id = Column(Integer, ForeignKey("approval_chains.id"))
    current_node_index = Column(Integer, default=0)
    approval_level = Column(String(50))
    approver = Column(String(100))
    approval_comment = Column(String(500))
    approved_at = Column(DateTime)
    is_overdue = Column(Boolean, default=False)
    risk_triggered = Column(Boolean, default=False)
    risk_reason = Column(String(500))
    sync_status = Column(String(20), default="PENDING")
    synced_at = Column(DateTime)
    order_manager_notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    customer = relationship("Customer", backref="change_requests")
    approval_chain = relationship("ApprovalChain", backref="change_requests")
    matched_rule = relationship("ApprovalRule")
    approval_records = relationship("ApprovalRecord", back_populates="change_request", order_by="ApprovalRecord.node_order")
    sync_records = relationship("SyncRecord", back_populates="change_request")
    notifications = relationship("Notification", back_populates="change_request")
    assignments = relationship("ApprovalAssignment", back_populates="change_request")
    reminders = relationship("ApprovalReminder", back_populates="change_request")


class SyncRecord(Base):
    __tablename__ = "sync_records"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    target_system = Column(String(50))
    status = Column(String(20), default="PENDING")
    sync_data = Column(Text)
    response_data = Column(Text)
    error_message = Column(String(500))
    retry_count = Column(Integer, default=0)
    synced_at = Column(DateTime)

    change_request = relationship("ChangeRequest", back_populates="sync_records")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    recipient = Column(String(100))
    recipient_role = Column(String(50))
    recipient_department = Column(String(100))
    notification_type = Column(String(50))
    title = Column(String(200))
    content = Column(Text)
    is_read = Column(Boolean, default=False)
    is_delivered = Column(Boolean, default=True)
    delivered_at = Column(DateTime, default=datetime.now)
    sent_at = Column(DateTime, default=datetime.now)

    change_request = relationship("ChangeRequest", back_populates="notifications")


class RiskWarning(Base):
    __tablename__ = "risk_warnings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    customer_code = Column(String(50), index=True)
    warning_type = Column(String(50))
    warning_level = Column(String(20))
    description = Column(String(500))
    change_count_30d = Column(Integer)
    is_handled = Column(Boolean, default=False)
    handled_by = Column(String(100))
    handle_comment = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)
    handled_at = Column(DateTime)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    operation_type = Column(String(50), index=True)
    operator = Column(String(100))
    target_type = Column(String(50))
    target_id = Column(Integer)
    detail = Column(Text)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.now, index=True)


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(Date, unique=True, index=True)
    total_requests = Column(Integer, default=0)
    approved_count = Column(Integer, default=0)
    approval_rate = Column(Float, default=0.0)
    sync_success_count = Column(Integer, default=0)
    sync_success_rate = Column(Float, default=0.0)
    avg_processing_hours = Column(Float, default=0.0)
    department_stats = Column(Text)
    change_type_stats = Column(Text)
    risk_warning_count = Column(Integer, default=0)
    overdue_count = Column(Integer, default=0)
    pdf_path = Column(String(500))
    excel_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)


class ApprovalChain(Base):
    __tablename__ = "approval_chains"

    id = Column(Integer, primary_key=True, index=True)
    chain_name = Column(String(100), nullable=False)
    description = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    nodes = relationship("ApprovalNode", back_populates="chain", order_by="ApprovalNode.node_order")
    rules = relationship("ApprovalRule", back_populates="chain")


class ApprovalNode(Base):
    __tablename__ = "approval_nodes"

    id = Column(Integer, primary_key=True, index=True)
    chain_id = Column(Integer, ForeignKey("approval_chains.id"), nullable=False)
    node_name = Column(String(100), nullable=False)
    node_order = Column(Integer, default=0)
    approver_role = Column(String(50))
    approver = Column(String(100))
    department = Column(String(100))
    timeout_hours = Column(Integer, default=24)
    created_at = Column(DateTime, default=datetime.now)

    chain = relationship("ApprovalChain", back_populates="nodes")


class ApprovalRule(Base):
    __tablename__ = "approval_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(100), nullable=False)
    chain_id = Column(Integer, ForeignKey("approval_chains.id"), nullable=False)
    priority = Column(Integer, default=0)
    customer_level = Column(String(20))
    change_type = Column(String(50))
    department = Column(String(100))
    industry = Column(String(100))
    min_change_fields = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)

    chain = relationship("ApprovalChain", back_populates="rules")


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("approval_nodes.id"))
    node_name = Column(String(100))
    node_order = Column(Integer, default=0)
    approver_role = Column(String(50))
    approver = Column(String(100))
    assignee = Column(String(100))
    candidate_users = Column(Text)
    claimed_at = Column(DateTime)
    claimed_by = Column(String(100))
    assignment_type = Column(String(20))
    action = Column(String(20))
    comment = Column(String(500))
    approved_at = Column(DateTime)
    is_overdue = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    change_request = relationship("ChangeRequest", back_populates="approval_records")
    node = relationship("ApprovalNode")


class ApprovalCandidate(Base):
    __tablename__ = "approval_candidates"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(50), index=True)
    department = Column(String(100), index=True)
    username = Column(String(100), nullable=False)
    real_name = Column(String(100), nullable=False)
    email = Column(String(100))
    phone = Column(String(50))
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class ApprovalAssignment(Base):
    __tablename__ = "approval_assignments"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    approval_record_id = Column(Integer, ForeignKey("approval_records.id"))
    node_order = Column(Integer, default=0)
    assignment_type = Column(String(20))
    from_user = Column(String(100))
    to_user = Column(String(100), nullable=False)
    reason = Column(String(500))
    operator = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)

    change_request = relationship("ChangeRequest", back_populates="assignments")
    approval_record = relationship("ApprovalRecord")


class ApprovalReminder(Base):
    __tablename__ = "approval_reminders"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    approval_record_id = Column(Integer, ForeignKey("approval_records.id"))
    reminder_type = Column(String(20))
    reminder_level = Column(String(20), default="NORMAL")
    target_user = Column(String(100), nullable=False)
    operator = Column(String(100))
    reason = Column(String(500))
    is_escalated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    change_request = relationship("ChangeRequest", back_populates="reminders")
    approval_record = relationship("ApprovalRecord")


class RiskCase(Base):
    __tablename__ = "risk_cases"

    id = Column(Integer, primary_key=True, index=True)
    case_no = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    customer_code = Column(String(50), index=True)
    risk_type = Column(String(50))
    risk_level = Column(String(20))
    status = Column(String(20), default="OPEN")
    description = Column(String(500))
    related_warning_id = Column(Integer, ForeignKey("risk_warnings.id"))
    related_change_request_ids = Column(Text)
    matched_rule_name = Column(String(200))
    match_reason = Column(String(500))
    freeze_reason = Column(String(500))
    unfreeze_reason = Column(String(500))
    handler = Column(String(100))
    handled_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    customer = relationship("Customer")
    warning = relationship("RiskWarning")
