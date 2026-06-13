from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.database import SessionLocal
from app.services.report_service import generate_daily_report
from app.services import approval_service
import logging

logger = logging.getLogger(__name__)


def daily_report_job():
    """每日凌晨生成前一天的统计报告"""
    logger.info("开始生成每日报告...")
    db = SessionLocal()
    try:
        from datetime import timedelta
        report_date = date.today() - timedelta(days=1)
        report = generate_daily_report(db, report_date=report_date)
        logger.info(f"日报生成成功: {report.report_date}")
    except Exception as e:
        logger.error(f"日报生成失败: {e}")
    finally:
        db.close()


def check_overdue_job():
    """定期检查超时审批申请并发送催办通知"""
    logger.info("开始检查超时审批...")
    db = SessionLocal()
    try:
        result = approval_service.check_and_update_overdue(db)
        logger.info(f"超时检查完成: 新超{result['new_overdue']}件, 发送通知{result['notifications_sent']}条")
    except Exception as e:
        logger.error(f"超时检查失败: {e}")
    finally:
        db.close()


def start_scheduler():
    """启动定时任务调度器"""
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        daily_report_job,
        trigger=CronTrigger(hour=0, minute=30),
        id="daily_report_job",
        name="每日报告生成",
        replace_existing=True
    )

    scheduler.add_job(
        check_overdue_job,
        trigger=IntervalTrigger(hours=1),
        id="check_overdue_job",
        name="超时审批检查",
        replace_existing=True
    )

    scheduler.start()
    logger.info("定时任务调度器已启动")
    return scheduler


def stop_scheduler(scheduler):
    """停止定时任务调度器"""
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务调度器已停止")
