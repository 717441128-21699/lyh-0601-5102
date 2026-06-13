from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.routers import (
    customer_router,
    change_request_router,
    risk_router,
    notification_router,
    report_router,
    export_router,
    sync_router,
    approval_router
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="客户主数据变更管理系统",
    description="客户主数据变更管理中心，支持可配置审批流程、多维度规则匹配、"
                "审批待办中心、超时催办、风控预警、多系统同步、每日统计报告等功能。",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customer_router.router)
app.include_router(change_request_router.router)
app.include_router(approval_router.router)
app.include_router(risk_router.router)
app.include_router(notification_router.router)
app.include_router(report_router.router)
app.include_router(export_router.router)
app.include_router(sync_router.router)


@app.get("/", tags=["系统"])
def root():
    return {
        "name": "客户主数据变更管理系统",
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "healthy"}


@app.get("/api/dashboard", tags=["首页统计"])
def dashboard(approver: str = None):
    """首页统计数据：今日提交、今日通过、待办统计、7日趋势"""
    from app.database import SessionLocal
    from app.services import change_request_service

    db = SessionLocal()
    try:
        stats = change_request_service.get_dashboard_stats(db, approver=approver)
        return stats
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    from app.scheduler import start_scheduler
    app.state.scheduler = start_scheduler()

    from app.database import SessionLocal
    from app.scripts import init_approval_data
    db = SessionLocal()
    try:
        init_approval_data.init_default_approval_rules(db)
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown_event():
    from app.scheduler import stop_scheduler
    if hasattr(app.state, "scheduler"):
        stop_scheduler(app.state.scheduler)
