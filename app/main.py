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
    sync_router
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="客户主数据变更管理系统",
    description="系统每天自动接收员工提交的客户主数据变更申请，自动校验新旧数据差异，"
                "根据客户等级和变更类型匹配审批流程，审批通过后自动同步至CRM、ERP、财务系统，"
                "并实时推送变更通知。当同一客户30天内变更超过3次时触发风控预警并冻结同步。",
    version="1.0.0"
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
app.include_router(risk_router.router)
app.include_router(notification_router.router)
app.include_router(report_router.router)
app.include_router(export_router.router)
app.include_router(sync_router.router)


@app.get("/", tags=["系统"])
def root():
    return {
        "name": "客户主数据变更管理系统",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    from app.scheduler import start_scheduler
    app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    from app.scheduler import stop_scheduler
    if hasattr(app.state, "scheduler"):
        stop_scheduler(app.state.scheduler)
