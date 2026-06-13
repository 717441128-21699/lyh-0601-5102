from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database import SessionLocal
from app.services.report_service import generate_daily_report
import logging

logger = logging.getLogger(__name__)


def daily_report_job():
    """每日凌晨生成前一天的统计报告"""
    logger.info("开始生成每日报告...")
    db = SessionLocal()
    try:
        report = generate_daily_report(db, report_date=date.today())
        logger.info(f"日报生成成功: {report.report_date}")
    except Exception as e:
        logger.error(f"日报生成失败: {e}")
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

    scheduler.start()
    logger.info("定时任务调度器已启动")
    return scheduler


def stop_scheduler(scheduler):
    """停止定时任务调度器"""
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务调度器已停止")
