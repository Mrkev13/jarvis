from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from notifications_service import create_all_overdue_and_upcoming_notifications
from goal_history_service import ensure_goal_progress_snapshot_for_all_active_automatic_goals
from env_config import env_bool, env_int
from scheduler_health import tracked_job, job_failed, job_history

_scheduler: BackgroundScheduler | None = None
SCHEDULER_ENABLED = env_bool("SCHEDULER_ENABLED", False)
SCHEDULER_INTERVAL_SECONDS = env_int("SCHEDULER_INTERVAL_SECONDS", 3600, minimum=60)
# Phase D: kontrola splatných připomínek – vlastní lehký job ve STEJNÉM scheduleru, defaultně zapnutý
# i bez hodinového jobu. Zpracování je idempotentní (víc workerů / lazy kontrola při čtení notifikací
# nic nezdvojí), takže krátký interval je bezpečný.
REMINDERS_CHECK_ENABLED = env_bool("REMINDERS_CHECK_ENABLED", True)
REMINDERS_CHECK_SECONDS = env_int("REMINDERS_CHECK_SECONDS", 60, minimum=15)
# Phase F: Denní přehled – vlastní job (pomalé LLM volání nesmí brzdit připomínky). Čas v Europe/Prague.
DAILY_BRIEFING_ENABLED = env_bool("DAILY_BRIEFING_ENABLED", True)  # stejný parser jako briefing_service
DAILY_BRIEFING_CHECK_SECONDS = env_int("DAILY_BRIEFING_CHECK_SECONDS", 300, minimum=60)
# Phase G: Týdenní přehled – další samostatný job (neblokuje připomínky ani Denní přehled).
WEEKLY_REVIEW_ENABLED = env_bool("WEEKLY_REVIEW_ENABLED", True)  # stejný parser jako weekly_review_service
WEEKLY_REVIEW_CHECK_SECONDS = env_int("WEEKLY_REVIEW_CHECK_SECONDS", 900, minimum=60)
SINGLE_WORKER_ASSUMPTION_DOC = (
    "Scheduler assumes single backend worker (uvicorn --workers 1). "
    "If you run multiple workers, scheduler will fire multiple times per hour."
)


@tracked_job("standa_hub_hourly")
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
            job_failed("standa_hub_hourly")
            db.rollback()
            print(f"[scheduler] notifications failed: {_nerr}")
        try:
            from backup_service import run_backup, should_run_backup_daily
            if should_run_backup_daily():
                bid = run_backup(db)
                print(f"[scheduler] daily backup ran id={bid}")
        except Exception as _berr:
            job_failed("standa_hub_hourly")
            print(f"[scheduler] daily backup skipped: {_berr}")
    except Exception as _jerr:
        job_failed("standa_hub_hourly")
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


@tracked_job("standa_hub_reminders")
def _run_reminders_job() -> None:
    from reminder_service import process_due_reminders

    db = SessionLocal()
    try:
        stats = process_due_reminders(db)
        if stats.get("failed"):
            job_failed("standa_hub_reminders")
        if stats["fired"] or stats["failed"]:
            print(f"[scheduler] reminders: {stats}")
    except Exception as _rerr:  # noqa: BLE001 - job nesmí shodit scheduler
        job_failed("standa_hub_reminders")
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] reminders job failed: {type(_rerr).__name__}: {_rerr}")
    # Phase E: externí doručení až po zazvonění a odděleně – jeho chyba nesmí ovlivnit připomínky.
    try:
        from delivery_service import run_delivery_cycle

        dstats = run_delivery_cycle(db)
        if dstats.get("failed"):
            job_failed("standa_hub_reminders")
        if dstats.get("enqueued") or dstats.get("sent") or dstats.get("failed") or dstats.get("retry"):
            print(f"[scheduler] external delivery: {dstats}")
    except Exception as _derr:  # noqa: BLE001
        job_failed("standa_hub_reminders")
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] external delivery failed: {type(_derr).__name__}")
    finally:
        db.close()


@tracked_job("standa_hub_briefing")
def _run_briefing_job() -> None:
    from briefing_service import run_scheduled

    db = SessionLocal()
    try:
        state = run_scheduled(db)
        if state in ("generated", "retried"):
            print(f"[scheduler] daily briefing: {state}")
    except Exception as _berr:  # noqa: BLE001 - přehled nesmí shodit scheduler ani ostatní joby
        job_failed("standa_hub_briefing")
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] daily briefing job failed: {type(_berr).__name__}")
    finally:
        db.close()


@tracked_job("standa_hub_weekly_review")
def _run_weekly_review_job() -> None:
    from weekly_review_service import run_scheduled

    db = SessionLocal()
    try:
        state = run_scheduled(db)
        if state in ("generated", "retried"):
            print(f"[scheduler] weekly review: {state}")
    except Exception as _werr:  # noqa: BLE001 - přehled nesmí shodit scheduler ani ostatní joby
        job_failed("standa_hub_weekly_review")
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[scheduler] weekly review job failed: {type(_werr).__name__}")
    finally:
        db.close()


def run_job_now() -> dict:
    _run_hourly_job()
    return {"ok": True, "ran_at": datetime.utcnow().isoformat(), "doc": SINGLE_WORKER_ASSUMPTION_DOC}


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not (SCHEDULER_ENABLED or REMINDERS_CHECK_ENABLED or DAILY_BRIEFING_ENABLED or WEEKLY_REVIEW_ENABLED):
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
    if WEEKLY_REVIEW_ENABLED:
        sched.add_job(
            _run_weekly_review_job,
            trigger=IntervalTrigger(seconds=WEEKLY_REVIEW_CHECK_SECONDS),
            id="standa_hub_weekly_review",
            name="standa_hub_weekly_review",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.utcnow(),  # po startu dohnat chybějící přehled (nejvýš minulého týdne)
        )
    sched.start()
    print(f"[scheduler] started! hourly={'on' if SCHEDULER_ENABLED else 'off'} ({SCHEDULER_INTERVAL_SECONDS}s), "
          f"reminders={'on' if REMINDERS_CHECK_ENABLED else 'off'} ({REMINDERS_CHECK_SECONDS}s), "
          f"briefing={'on' if DAILY_BRIEFING_ENABLED else 'off'} ({DAILY_BRIEFING_CHECK_SECONDS}s), "
          f"weekly={'on' if WEEKLY_REVIEW_ENABLED else 'off'} ({WEEKLY_REVIEW_CHECK_SECONDS}s). "
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


def scheduler_snapshot() -> dict:
    """Only operational IDs/timestamps; no job args or business data."""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    expected = [
        ("standa_hub_hourly", SCHEDULER_ENABLED, SCHEDULER_INTERVAL_SECONDS),
        ("standa_hub_reminders", REMINDERS_CHECK_ENABLED, REMINDERS_CHECK_SECONDS),
        ("standa_hub_briefing", DAILY_BRIEFING_ENABLED, DAILY_BRIEFING_CHECK_SECONDS),
        ("standa_hub_weekly_review", WEEKLY_REVIEW_ENABLED, WEEKLY_REVIEW_CHECK_SECONDS),
    ]
    sched = _scheduler
    running = bool(sched and sched.running)
    active = {job.id: job for job in sched.get_jobs()} if running else {}
    jobs = []
    degraded = False
    for job_id, enabled, interval in expected:
        history = job_history(job_id)
        job = active.get(job_id)
        status = "disabled" if not enabled else "scheduled" if job else "missing"
        started = history["last_started"]
        if enabled and started and (now - datetime.fromisoformat(started)).total_seconds() > max(interval * 3, 300):
            status = "stale"
        if enabled and history["last_result"] == "failed":
            status = "failed"
        if enabled and status in ("missing", "stale", "failed"):
            degraded = True
        jobs.append({"id": job_id, "enabled": enabled, "status": status, **history, "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None})
    enabled = any(flag for _, flag, _ in expected)
    status = "disabled" if not enabled else "stopped" if not running else "degraded" if degraded else "running"
    return {"status": status, "running": running, "backup_job_enabled": SCHEDULER_ENABLED, "jobs": jobs}
