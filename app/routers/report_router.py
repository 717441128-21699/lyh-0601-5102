from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.schemas import PaginatedResponse
from app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["统计报表"])


@router.get("/daily", response_model=PaginatedResponse, summary="获取日报列表")
def list_daily_reports(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    return report_service.get_reports_list(db, page=page, page_size=page_size)


@router.get("/daily/{report_date}", summary="获取指定日期的日报")
def get_daily_report(report_date: date, db: Session = Depends(get_db)):
    report = report_service.get_report_by_date(db, report_date)
    if not report:
        raise HTTPException(status_code=404, detail="日报不存在")
    return report


@router.post("/daily/{report_date}/generate", summary="手动生成日报")
def generate_report(report_date: date, db: Session = Depends(get_db)):
    try:
        report = report_service.generate_daily_report(db, report_date)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily/{report_date}/download-pdf", summary="下载日报PDF")
def download_pdf(report_date: date, db: Session = Depends(get_db)):
    report = report_service.get_report_by_date(db, report_date)
    if not report or not report.pdf_path:
        raise HTTPException(status_code=404, detail="PDF报告不存在")
    return FileResponse(
        report.pdf_path,
        media_type="application/pdf",
        filename=f"日报_{report_date}.pdf"
    )


@router.get("/daily/{report_date}/download-excel", summary="下载日报Excel")
def download_excel(report_date: date, db: Session = Depends(get_db)):
    report = report_service.get_report_by_date(db, report_date)
    if not report or not report.excel_path:
        raise HTTPException(status_code=404, detail="Excel报告不存在")
    return FileResponse(
        report.excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"日报_{report_date}.xlsx"
    )


@router.get("/trend/7day", summary="获取7日趋势数据")
def get_7day_trend(end_date: date = Query(None, description="结束日期"), db: Session = Depends(get_db)):
    trend = report_service.get_7day_trend(db, end_date)
    return {"trend": trend}


@router.get("/trend/30day", summary="获取30日趋势数据")
def get_30day_trend(end_date: date = Query(None, description="结束日期"), db: Session = Depends(get_db)):
    trend = report_service.get_30day_trend(db, end_date)
    return {"trend": trend}


@router.get("/daily/{report_date}/detail", summary="获取日报详情（含结构化统计）")
def get_report_detail(report_date: date, db: Session = Depends(get_db)):
    detail = report_service.get_report_detail(db, report_date)
    if not detail:
        raise HTTPException(status_code=404, detail="日报不存在")
    return detail
