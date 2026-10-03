import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from notifications_service import create_all_overdue_and_upcoming_notifications
from goal_history_service import ensure_goal_progress_snapshot_for_all_active_automatic_goals

_scheduler: BackgroundScheduler | None = None
SCHEDULER_ENABLED = (os.environ.get("SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes"))
SCHEDULER_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "3600"))
# Phase D: kontrola splatných připomínek – vlastní lehký job ve STEJNÉM scheduleru, defaultně zapnutý
# i bez hodinového jobu. Zpracování je idempotentní (víc workerů / lazy kontrola při čtení notifikací
# nic nezdvojí), takže krátký interval je bezpečný.
REMINDERS_CHECK_ENABLED = (os.environ.get("REMINDERS_CHECK_ENABLED", "true").lower() in ("1", "true", "yes"))
REMINDERS_CHECK_SECONDS = max(15, int(os.environ.get("REMINDERS_CHECK_SECONDS", "60")))
# Phase F: Denní přehled – vlastní job (pomalé LLM volání nesmí brzdit připomínky). Čas v Europe/Prague.
DAILY_BRIEFING_ENABLED = (os.environ.get("DAILY_BRIEFING_ENABLED", "true").lower() in ("1", "true", "yes"))
DAILY_BRIEFING_CHECK_SECONDS = max(60, int(os.environ.get("DAILY_BRIEFING_CHECK_SECONDS", "300")))
SINGLE_WORKER_ASSUMPTION_DOC = (
    "Scheduler assumes single backend worker (uvicorn --workers 1). "
    "If you run multiple workers, scheduler will fire multiple times per hour."
)


def _run_hourly_job() -> None:
    print(f"[scheduler] hourly job started at {datetime.utcnow().isoformat()}")
    db = SessionLocal()
    try:
        snapshots = ensure_goal_progress_snapshot_for_all_active_automatic_goals(db)
        print(f"[scheduler] goal snapshots: {snapshots}")
        db.commit()
        try:
            notif_count = create_all_overdue_and_upcoming_notifications(db)
            print(f"[scheduler] notifications created: {notif_count}")
            db.commit()
        except Exception as _nerr:
            db.rollback()
            print(f"[scheduler] notifications failed: {_nerr}")
        try:
            from backup_service import run_backup, should_run_backup_daily
            if should_run_backup_daily():
                bid = run_backup(db)
                print(f"[scheduler] daily backup ran id={bid}")
        except Exception as _berr:
            print(f"[scheduler] daily backup skipped: {_berr}")
    except Exception as _jerr:
        import traceback
        print(f"[scheduler] hourly job FAILED: {_jerr}")
        traceback.print_exc()
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
    print(f"[scheduler] hourly job finished at {datetime.utcnow().isoformat()}")


def _run_reminders_job() -> None:
    from reminder_service import process_due_reminders

    db = SessionLocal()
    try:
        stats = process_due_reminders(db)
        if stats["fired"] or stats["failed"]:
            print(f"[scheduler] reminders: {stats}")
    except Exception as _rerr:  # noqa: BLE001 - job nesmí shodit scheduler
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] reminders job failed: {type(_rerr).__name__}: {_rerr}")
    # Phase E: externí doručení až po zazvonění a odděleně – jeho chyba nesmí ovlivnit připomínky.
    try:
        from delivery_service import run_delivery_cycle

        dstats = run_delivery_cycle(db)
        if dstats.get("enqueued") or dstats.get("sent") or dstats.get("failed") or dstats.get("retry"):
            print(f"[scheduler] external delivery: {dstats}")
    except Exception as _derr:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] external delivery failed: {type(_derr).__name__}")
    finally:
        db.close()


def _run_briefing_job() -> None:
    from briefing_service import run_scheduled

    db = SessionLocal()
    try:
        state = run_scheduled(db)
        if state in ("generated", "retried"):
            print(f"[scheduler] daily briefing: {state}")
    except Exception as _berr:  # noqa: BLE001 - přehled nesmí shodit scheduler ani ostatní joby
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] daily briefing job failed: {type(_berr).__name__}")
    finally:
        db.close()


def run_job_now() -> dict:
    _run_hourly_job()
    return {"ok": True, "ran_at": datetime.utcnow().isoformat(), "doc": SINGLE_WORKER_ASSUMPTION_DOC}


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not SCHEDULER_ENABLED and not REMINDERS_CHECK_ENABLED and not DAILY_BRIEFING_ENABLED:
        print(f"[scheduler] disabled (SCHEDULER_ENABLED={SCHEDULER_ENABLED}, "
              f"REMINDERS_CHECK_ENABLED={REMINDERS_CHECK_ENABLED}). "
              f"Single worker assumption: {SINGLE_WORKER_ASSUMPTION_DOC}")
        return None
    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    if SCHEDULER_ENABLED:
        sched.add_job(
            _run_hourly_job,
            trigger=IntervalTrigger(seconds=SCHEDULER_INTERVAL_SECONDS),
            id="standa_hub_hourly",
            name="standa_hub_hourly",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.utcnow(),
        )
    if REMINDERS_CHECK_ENABLED:
        sched.add_job(
            _run_reminders_job,
            trigger=IntervalTrigger(seconds=REMINDERS_CHECK_SECONDS),
            id="standa_hub_reminders",
            name="standa_hub_reminders",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.utcnow(),
        )
    if DAILY_BRIEFING_ENABLED:
        sched.add_job(
            _run_briefing_job,
            trigger=IntervalTrigger(seconds=DAILY_BRIEFING_CHECK_SECONDS),
            id="standa_hub_briefing",
            name="standa_hub_briefing",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.utcnow(),  # po startu hned dohnat chybějící dnešní přehled
        )
    sched.start()
    print(f"[scheduler] started! hourly={'on' if SCHEDULER_ENABLED else 'off'} ({SCHEDULER_INTERVAL_SECONDS}s), "
          f"reminders={'on' if REMINDERS_CHECK_ENABLED else 'off'} ({REMINDERS_CHECK_SECONDS}s), "
          f"briefing={'on' if DAILY_BRIEFING_ENABLED else 'off'} ({DAILY_BRIEFING_CHECK_SECONDS}s). "
          f"Single worker: {SINGLE_WORKER_ASSUMPTION_DOC}")
    _scheduler = sched
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        finally:
            _scheduler = None
