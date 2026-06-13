from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import SessionLocal
from app.services import assignment_service, approval_service
from pydantic import BaseModel

router = APIRouter(prefix="/api/assignment", tags=["审批指派与催办"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ClaimTaskRequest(BaseModel):
    request_id: int
    claimer: str


class ReassignTaskRequest(BaseModel):
    request_id: int
    from_user: str
    to_user: str
    reason: str
    operator: str
    is_manager: bool = False


class SendReminderRequest(BaseModel):
    request_id: int
    operator: str
    reason: Optional[str] = None
    is_escalated: bool = False


class SetUrgencyRequest(BaseModel):
    request_id: int
    urgency: str
    operator: str


@router.get("/candidates")
def get_candidates(role: str = None, department: str = None, db: Session = Depends(get_db)):
    """获取候选处理人列表"""
    try:
        candidates = assignment_service.get_candidate_users(db, role=role, department=department)
        return {
            "success": True,
            "total": len(candidates),
            "items": candidates
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/claim")
def claim_task(req: ClaimTaskRequest, db: Session = Depends(get_db)):
    """签收任务"""
    try:
        result = assignment_service.claim_task(
            db,
            request_id=req.request_id,
            claimer=req.claimer
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reassign")
def reassign_task(req: ReassignTaskRequest, db: Session = Depends(get_db)):
    """转派任务"""
    try:
        result = assignment_service.reassign_task(
            db,
            request_id=req.request_id,
            from_user=req.from_user,
            to_user=req.to_user,
            reason=req.reason,
            operator=req.operator,
            is_manager=req.is_manager
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reminder")
def send_reminder(req: SendReminderRequest, db: Session = Depends(get_db)):
    """发送催办"""
    try:
        result = assignment_service.send_reminder(
            db,
            request_id=req.request_id,
            operator=req.operator,
            reason=req.reason,
            is_escalated=req.is_escalated
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/urgency")
def set_urgency(req: SetUrgencyRequest, db: Session = Depends(get_db)):
    """设置加急状态"""
    try:
        result = assignment_service.set_urgency(
            db,
            request_id=req.request_id,
            urgency=req.urgency,
            operator=req.operator
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}/reminders")
def get_reminder_history(request_id: int, db: Session = Depends(get_db)):
    """获取催办历史"""
    try:
        reminders = assignment_service.get_reminder_history(db, request_id)
        return {
            "success": True,
            "total": len(reminders),
            "items": reminders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}/assignments")
def get_assignment_history(request_id: int, db: Session = Depends(get_db)):
    """获取指派历史"""
    try:
        assignments = assignment_service.get_assignment_history(db, request_id)
        return {
            "success": True,
            "total": len(assignments),
            "items": assignments
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/todo")
def get_my_todo(
    approver: str = None,
    role: str = None,
    department: str = None,
    priority: str = None,
    urgency: str = None,
    is_overdue: bool = None,
    page: int = 1,
    page_size: int = 20,
    include_claimable: bool = False,
    db: Session = Depends(get_db)
):
    """
    获取我的待办列表（含候选处理人视图）
    include_claimable: 是否包含可签收的任务
    """
    try:
        result = approval_service.get_my_todo(
            db,
            approver=approver,
            role=role,
            department=department,
            priority=priority,
            urgency=urgency,
            is_overdue=is_overdue,
            page=page,
            page_size=page_size,
            include_claimable=include_claimable
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
