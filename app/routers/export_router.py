from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date
from app.database import get_db
from app.schemas import ChangeRequestQuery, PaginatedResponse
from app.services import export_service
from app.models import OperationLog

router = APIRouter(prefix="/api/export", tags=["数据导出"])


@router.get("/change-requests", summary="导出变更申请列表")
def export_change_requests(
    customer_name: Optional[str] = Query(None, description="客户名称"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    quick_range: Optional[str] = Query(None, description="快捷范围: today/yesterday/7d/30d"),
    status: Optional[str] = Query(None, description="状态"),
    department: Optional[str] = Query(None, description="部门"),
    db: Session = Depends(get_db)
):
    query = ChangeRequestQuery(
        customer_name=customer_name,
        start_date=start_date,
        end_date=end_date,
        status=status,
        department=department,
        page=1,
        page_size=10000
    )
    filepath = export_service.export_change_requests_excel(db, query, quick_range=quick_range)
    filename = filepath.split("\\")[-1]
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )


@router.post("/change-requests/batch", summary="批量导出变更明细")
def batch_export_details(
    request_ids: List[int] = Body(..., embed=True, description="申请ID列表"),
    db: Session = Depends(get_db)
):
    if not request_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的记录")
    filepath = export_service.batch_export_change_details(db, request_ids)
    filename = filepath.split("\\")[-1]
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )


@router.get("/operation-logs", summary="导出操作日志")
def export_operation_logs(
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    quick_range: Optional[str] = Query(None, description="快捷范围: today/yesterday/7d/30d"),
    operator: Optional[str] = Query(None, description="操作人"),
    operation_type: Optional[str] = Query(None, description="操作类型"),
    db: Session = Depends(get_db)
):
    filepath = export_service.export_operation_logs_excel(
        db, start_date=start_date, end_date=end_date,
        quick_range=quick_range,
        operator=operator, operation_type=operation_type
    )
    filename = filepath.split("\\")[-1]
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )


@router.get("/operation-logs/list", response_model=PaginatedResponse, summary="查询操作日志")
def list_operation_logs(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    quick_range: Optional[str] = Query(None, description="快捷范围: today/yesterday/7d/30d"),
    operator: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(OperationLog)

    from datetime import datetime, timedelta
    if quick_range:
        today = date.today()
        if quick_range == "today":
            start_dt = datetime.combine(today, datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        elif quick_range == "yesterday":
            yesterday = today - timedelta(days=1)
            start_dt = datetime.combine(yesterday, datetime.min.time())
            end_dt = datetime.combine(yesterday, datetime.max.time())
        elif quick_range == "7d":
            start_dt = datetime.combine(today - timedelta(days=6), datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        elif quick_range == "30d":
            start_dt = datetime.combine(today - timedelta(days=29), datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time())
        else:
            start_dt, end_dt = None, None
    else:
        start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
        end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None

    if start_dt:
        query = query.filter(OperationLog.created_at >= start_dt)
    if end_dt:
        query = query.filter(OperationLog.created_at <= end_dt)
    if operator:
        query = query.filter(OperationLog.operator == operator)
    if operation_type:
        query = query.filter(OperationLog.operation_type == operation_type)

    total = query.count()
    items = query.order_by(OperationLog.created_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }
