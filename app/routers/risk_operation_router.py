from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import SessionLocal
from app.services import risk_operation_service

router = APIRouter(prefix="/api/risk-operation", tags=["风控工作台"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/summary")
def get_workbench_summary(handler: str = None, db: Session = Depends(get_db)):
    """获取风控工作台汇总数据"""
    try:
        summary = risk_operation_service.get_risk_workbench_summary(db, handler=handler)
        return {
            "success": True,
            "data": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/warning-customers")
def get_warning_customers(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    """获取预警中的客户列表"""
    try:
        result = risk_operation_service.get_warning_customers(
            db, page=page, page_size=page_size
        )
        return {
            "success": True,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "items": result["items"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frozen-customers")
def get_frozen_customers(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    """获取已冻结客户列表"""
    try:
        result = risk_operation_service.get_frozen_customers(
            db, page=page, page_size=page_size
        )
        return {
            "success": True,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "items": result["items"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery-records")
def get_recovery_records(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    """获取人工解除后的恢复记录"""
    try:
        result = risk_operation_service.get_recovery_records(
            db, page=page, page_size=page_size
        )
        return {
            "success": True,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "items": result["items"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trace")
def get_risk_trace(
    customer_id: int = None,
    customer_code: str = None,
    change_request_id: int = None,
    db: Session = Depends(get_db)
):
    """
    获取风控追踪详情
    可以按客户ID、客户编码、或变更申请ID查询
    """
    try:
        result = risk_operation_service.get_risk_trace(
            db,
            customer_id=customer_id,
            customer_code=customer_code,
            change_request_id=change_request_id
        )
        return {
            "success": True,
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/warning/{warning_id}/handle")
def mark_warning_handled(
    warning_id: int,
    handler: str,
    comment: str = None,
    db: Session = Depends(get_db)
):
    """标记预警为已处理"""
    try:
        warning = risk_operation_service.mark_warning_handled(
            db,
            warning_id=warning_id,
            handler=handler,
            comment=comment
        )
        db.commit()
        return {
            "success": True,
            "warning_id": warning.id,
            "is_handled": warning.is_handled
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/status")
def update_case_status(
    case_id: int,
    status: str,
    handler: str = None,
    comment: str = None,
    unfreeze_reason: str = None,
    db: Session = Depends(get_db)
):
    """更新风控案件状态"""
    try:
        case = risk_operation_service.update_risk_case_status(
            db,
            case_id=case_id,
            status=status,
            handler=handler,
            comment=comment,
            unfreeze_reason=unfreeze_reason
        )
        db.commit()
        return {
            "success": True,
            "case_id": case.id,
            "case_no": case.case_no,
            "status": case.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
