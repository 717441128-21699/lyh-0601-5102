import os
import json
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models import ChangeRequest, DailyReport, RiskWarning, Customer
from app.services.utils import dict_to_json, json_to_dict, log_operation

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def generate_daily_report(db: Session, report_date: date = None) -> DailyReport:
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    existing = db.query(DailyReport).filter(DailyReport.report_date == report_date).first()
    if existing:
        return existing

    start_of_day = datetime.combine(report_date, datetime.min.time())
    end_of_day = datetime.combine(report_date, datetime.max.time())

    day_requests = db.query(ChangeRequest).filter(
        and_(
            ChangeRequest.created_at >= start_of_day,
            ChangeRequest.created_at <= end_of_day
        )
    ).all()

    total_requests = len(day_requests)
    approved_count = sum(1 for r in day_requests if r.status == "APPROVED")
    approval_rate = (approved_count / total_requests * 100) if total_requests > 0 else 0.0

    approved_requests = [r for r in day_requests if r.status == "APPROVED"]
    sync_success_count = sum(1 for r in approved_requests if r.sync_status == "SUCCESS")
    sync_success_rate = (sync_success_count / len(approved_requests) * 100) if len(approved_requests) > 0 else 0.0

    processing_hours = []
    for r in day_requests:
        if r.approved_at and r.created_at:
            delta = r.approved_at - r.created_at
            processing_hours.append(delta.total_seconds() / 3600)
    avg_processing_hours = sum(processing_hours) / len(processing_hours) if processing_hours else 0.0

    department_stats = {}
    for r in day_requests:
        dept = r.department or "未分配"
        if dept not in department_stats:
            department_stats[dept] = {
                "total": 0,
                "approved": 0,
                "rejected": 0,
                "pending": 0
            }
        department_stats[dept]["total"] += 1
        if r.status == "APPROVED":
            department_stats[dept]["approved"] += 1
        elif r.status == "REJECTED":
            department_stats[dept]["rejected"] += 1
        else:
            department_stats[dept]["pending"] += 1

    change_type_stats = {}
    for r in day_requests:
        ctype = r.change_type or "其他"
        if ctype not in change_type_stats:
            change_type_stats[ctype] = 0
        change_type_stats[ctype] += 1

    risk_count = db.query(RiskWarning).filter(
        and_(
            RiskWarning.created_at >= start_of_day,
            RiskWarning.created_at <= end_of_day
        )
    ).count()

    report = DailyReport(
        report_date=report_date,
        total_requests=total_requests,
        approved_count=approved_count,
        approval_rate=round(approval_rate, 2),
        sync_success_count=sync_success_count,
        sync_success_rate=round(sync_success_rate, 2),
        avg_processing_hours=round(avg_processing_hours, 2),
        department_stats=dict_to_json(department_stats),
        change_type_stats=dict_to_json(change_type_stats),
        risk_warning_count=risk_count
    )

    db.add(report)
    db.flush()

    pdf_path = generate_pdf_report(report)
    excel_path = generate_excel_report(report)

    report.pdf_path = pdf_path
    report.excel_path = excel_path

    log_operation(
        db,
        operation_type="GENERATE_REPORT",
        operator="SYSTEM",
        target_type="DAILY_REPORT",
        target_id=report.id,
        detail=f"生成日报: {report_date}"
    )

    db.commit()
    db.refresh(report)
    return report


def get_7day_trend(db: Session, end_date: date = None) -> dict:
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    trend_data = []
    for i in range(6, -1, -1):
        d = end_date - timedelta(days=i)
        report = db.query(DailyReport).filter(DailyReport.report_date == d).first()
        if report:
            trend_data.append({
                "date": d.strftime("%Y-%m-%d"),
                "total_requests": report.total_requests,
                "approved_count": report.approved_count,
                "approval_rate": report.approval_rate,
                "sync_success_rate": report.sync_success_rate
            })
        else:
            trend_data.append({
                "date": d.strftime("%Y-%m-%d"),
                "total_requests": 0,
                "approved_count": 0,
                "approval_rate": 0,
                "sync_success_rate": 0
            })

    return trend_data


def generate_pdf_report(report: DailyReport) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    pdf_path = os.path.join(REPORTS_DIR, f"daily_report_{report.report_date}.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=18, spaceAfter=20)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Heading2'], fontSize=14, spaceAfter=10)
    normal_style = styles['Normal']

    story = []

    story.append(Paragraph("客户主数据变更管理日报", title_style))
    story.append(Paragraph(f"报告日期: {report.report_date}", subtitle_style))
    story.append(Spacer(1, 0.5 * cm))

    summary_data = [
        ["指标", "数值"],
        ["变更申请总数", str(report.total_requests)],
        ["审批通过数", str(report.approved_count)],
        ["审批通过率", f"{report.approval_rate}%"],
        ["同步成功数", str(report.sync_success_count)],
        ["同步成功率", f"{report.sync_success_rate}%"],
        ["平均处理时长(小时)", str(report.avg_processing_hours)],
        ["风控预警数", str(report.risk_warning_count)]
    ]

    summary_table = Table(summary_data, colWidths=[8 * cm, 6 * cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F2F2F2')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#D9D9D9'))
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 1 * cm))

    chart_path = _generate_trend_chart(report.report_date)
    if chart_path:
        story.append(Paragraph("7日趋势图", subtitle_style))
        img = Image(chart_path, width=16 * cm, height=8 * cm)
        story.append(img)
        story.append(Spacer(1, 0.5 * cm))

    dept_stats = json_to_dict(report.department_stats)
    if dept_stats:
        story.append(Paragraph("各部门统计", subtitle_style))
        dept_data = [["部门", "申请数", "通过数", "驳回数", "待审批"]]
        for dept, stats in dept_stats.items():
            dept_data.append([
                dept,
                str(stats["total"]),
                str(stats["approved"]),
                str(stats["rejected"]),
                str(stats["pending"])
            ])
        dept_table = Table(dept_data, colWidths=[5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
        dept_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#70AD47')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#D9D9D9'))
        ]))
        story.append(dept_table)
        story.append(Spacer(1, 0.5 * cm))

    doc.build(story)
    return pdf_path


def _generate_trend_chart(report_date: date) -> str:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    import platform

    system_name = platform.system()
    if system_name == "Windows":
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
    elif system_name == "Darwin":
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
    else:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    db = SessionLocal()
    try:
        trend = get_7day_trend(db, report_date)
    finally:
        db.close()

    if not trend:
        return None

    dates = [d["date"][5:] for d in trend]
    totals = [d["total_requests"] for d in trend]
    approved = [d["approved_count"] for d in trend]

    chart_path = os.path.join(REPORTS_DIR, f"trend_{report_date}.png")

    fig, ax1 = plt.subplots(figsize=(10, 5))

    bar_width = 0.35
    x = range(len(dates))

    ax1.bar([i - bar_width / 2 for i in x], totals, width=bar_width,
            label='申请总数', color='#4472C4', alpha=0.8)
    ax1.bar([i + bar_width / 2 for i in x], approved, width=bar_width,
            label='通过数', color='#70AD47', alpha=0.8)

    ax1.set_xlabel('日期')
    ax1.set_ylabel('数量')
    ax1.set_title('7日申请趋势')
    ax1.set_xticks(x)
    ax1.set_xticklabels(dates)
    ax1.legend(loc='upper left')

    plt.tight_layout()
    plt.savefig(chart_path, dpi=100, bbox_inches='tight')
    plt.close()

    return chart_path


def generate_excel_report(report: DailyReport) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.chart import BarChart, Reference

    excel_path = os.path.join(REPORTS_DIR, f"daily_report_{report.report_date}.xlsx")

    wb = Workbook()

    ws1 = wb.active
    ws1.title = "汇总"

    header_font = Font(bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    ws1.merge_cells('A1:B1')
    ws1['A1'] = f"客户主数据变更管理日报 - {report.report_date}"
    ws1['A1'].font = Font(bold=True, size=14)
    ws1['A1'].alignment = center_align

    summary_data = [
        ("指标", "数值"),
        ("变更申请总数", report.total_requests),
        ("审批通过数", report.approved_count),
        ("审批通过率(%)", report.approval_rate),
        ("同步成功数", report.sync_success_count),
        ("同步成功率(%)", report.sync_success_rate),
        ("平均处理时长(小时)", report.avg_processing_hours),
        ("风控预警数", report.risk_warning_count)
    ]

    for row_idx, (key, value) in enumerate(summary_data, start=3):
        ws1.cell(row=row_idx, column=1, value=key)
        ws1.cell(row=row_idx, column=2, value=value)
        if row_idx == 3:
            for col in range(1, 3):
                cell = ws1.cell(row=row_idx, column=col)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center_align
                cell.border = thin_border
        else:
            for col in range(1, 3):
                cell = ws1.cell(row=row_idx, column=col)
                cell.border = thin_border
                cell.alignment = center_align

    ws1.column_dimensions['A'].width = 25
    ws1.column_dimensions['B'].width = 20

    ws2 = wb.create_sheet("部门统计")
    dept_stats = json_to_dict(report.department_stats)

    headers = ["部门", "申请数", "通过数", "驳回数", "待审批"]
    for col, header in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    for row_idx, (dept, stats) in enumerate(dept_stats.items(), start=2):
        ws2.cell(row=row_idx, column=1, value=dept)
        ws2.cell(row=row_idx, column=2, value=stats["total"])
        ws2.cell(row=row_idx, column=3, value=stats["approved"])
        ws2.cell(row=row_idx, column=4, value=stats["rejected"])
        ws2.cell(row=row_idx, column=5, value=stats["pending"])
        for col in range(1, 6):
            cell = ws2.cell(row=row_idx, column=col)
            cell.border = thin_border
            cell.alignment = center_align

    ws2.column_dimensions['A'].width = 20
    for col in ['B', 'C', 'D', 'E']:
        ws2.column_dimensions[col].width = 12

    if dept_stats:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "各部门申请统计"
        chart.y_axis.title = '数量'
        chart.x_axis.title = '部门'

        data = Reference(ws2, min_col=2, min_row=1, max_row=len(dept_stats) + 1, max_col=5)
        cats = Reference(ws2, min_col=1, min_row=2, max_row=len(dept_stats) + 1)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.shape = 4
        ws2.add_chart(chart, "G2")

    ws3 = wb.create_sheet("变更类型统计")
    type_stats = json_to_dict(report.change_type_stats)

    ws3.cell(row=1, column=1, value="变更类型").font = header_font
    ws3.cell(row=1, column=1).fill = header_fill
    ws3.cell(row=1, column=1).alignment = center_align
    ws3.cell(row=1, column=2, value="数量").font = header_font
    ws3.cell(row=1, column=2).fill = header_fill
    ws3.cell(row=1, column=2).alignment = center_align

    for row_idx, (ctype, count) in enumerate(type_stats.items(), start=2):
        ws3.cell(row=row_idx, column=1, value=ctype).border = thin_border
        ws3.cell(row=row_idx, column=2, value=count).border = thin_border

    ws3.column_dimensions['A'].width = 20
    ws3.column_dimensions['B'].width = 15

    wb.save(excel_path)
    return excel_path


def get_reports_list(db: Session, page: int = 1, page_size: int = 20) -> dict:
    query = db.query(DailyReport)
    total = query.count()
    items = query.order_by(DailyReport.report_date.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    }


def get_report_by_date(db: Session, report_date: date) -> DailyReport:
    return db.query(DailyReport).filter(DailyReport.report_date == report_date).first()
