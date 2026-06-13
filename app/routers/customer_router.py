from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.schemas import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    PaginatedResponse
)
from app.services import customer_service

router = APIRouter(prefix="/api/customers", tags=["客户管理"])


@router.post("", response_model=CustomerResponse, summary="创建客户")
def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    try:
        return customer_service.create_customer(db, customer_data, "admin")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=PaginatedResponse, summary="查询客户列表")
def list_customers(
    name: Optional[str] = Query(None, description="客户名称模糊搜索"),
    level: Optional[str] = Query(None, description="客户等级"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    result = customer_service.get_customers(db, name=name, level=level, page=page, page_size=page_size)
    return {
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"]
    }


@router.get("/{customer_id}", response_model=CustomerResponse, summary="获取客户详情")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse, summary="更新客户信息")
def update_customer(customer_id: int, update_data: CustomerUpdate, db: Session = Depends(get_db)):
    try:
        return customer_service.update_customer(db, customer_id, update_data, "admin")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{customer_id}", summary="删除客户")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    try:
        customer_service.delete_customer(db, customer_id, "admin")
        return {"message": "删除成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
