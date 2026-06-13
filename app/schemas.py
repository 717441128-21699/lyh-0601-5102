from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class CustomerBase(BaseModel):
    customer_code: str
    customer_name: str
    customer_level: str = "NORMAL"
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    department: Optional[str] = None
    order_manager: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_level: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    department: Optional[str] = None
    order_manager: Optional[str] = None


class CustomerResponse(CustomerBase):
    id: int
    is_frozen: bool = False
    freeze_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChangeRequestCreate(BaseModel):
    customer_code: str
    change_type: str
    submitter: str
    department: str
    new_data: Dict[str, Any]


class DiffField(BaseModel):
    field: str
    old_value: Any
    new_value: Any


class ChangeRequestResponse(BaseModel):
    id: int
    request_no: str
    customer_id: int
    customer_code: str
    change_type: str
    submitter: str
    department: str
    old_data: Dict[str, Any]
    new_data: Dict[str, Any]
    diff_data: List[DiffField]
    status: str
    approval_level: Optional[str] = None
    approver: Optional[str] = None
    approval_comment: Optional[str] = None
    approved_at: Optional[datetime] = None
    risk_triggered: bool = False
    risk_reason: Optional[str] = None
    sync_status: str
    synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApprovalAction(BaseModel):
    action: str
    approver: str
    comment: Optional[str] = None


class SyncRecordResponse(BaseModel):
    id: int
    change_request_id: int
    target_system: str
    status: str
    error_message: Optional[str] = None
    retry_count: int
    synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationResponse(BaseModel):
    id: int
    change_request_id: int
    recipient: str
    notification_type: str
    title: str
    content: str
    is_read: bool
    sent_at: datetime

    class Config:
        from_attributes = True


class RiskWarningResponse(BaseModel):
    id: int
    customer_id: int
    customer_code: str
    warning_type: str
    warning_level: str
    description: str
    change_count_30d: int
    is_handled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OperationLogResponse(BaseModel):
    id: int
    operation_type: str
    operator: str
    target_type: str
    target_id: Optional[int] = None
    detail: str
    created_at: datetime

    class Config:
        from_attributes = True


class DailyReportResponse(BaseModel):
    id: int
    report_date: date
    total_requests: int
    approved_count: int
    approval_rate: float
    sync_success_count: int
    sync_success_rate: float
    avg_processing_hours: float
    risk_warning_count: int
    department_stats: Dict[str, Any]
    change_type_stats: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class ChangeRequestQuery(BaseModel):
    customer_name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    department: Optional[str] = None
    page: int = 1
    page_size: int = 20


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]
