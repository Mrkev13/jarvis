from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from notifications_service import create_all_overdue_and_upcoming_notifications
from env_config import env_bool, env_int
from module_registry import current_access
from scheduler_health import tracker

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


@tracker.tracked("standa_hub_hourly")
def _run_hourly_job() -> None:
    print(f"[scheduler] hourly job started at {datetime.utcnow().isoformat()}")
    db = SessionLocal()
    try:
        # MRK-20: kroky, které patří modulům (např. snímky automatických cílů), z `ModuleIntegrations.hourly`
        # dostupných modulů – stav modulů jednou za běh. Chyba jednoho kroku neblokuje ostatní ani notifikace.
        for owner, step in current_access().contributions("hourly"):
            try:
                result = step.run(db)
                print(f"[scheduler] {step.name}: {result}")
                db.commit()
            except Exception:  # noqa: BLE001 - modulový krok nesmí shodit hodinový job
                db.rollback()
                tracker.failed("standa_hub_hourly")
                print("[scheduler] module step failed")
        # Infrastruktura (notifikace, zálohy) zůstává globální.
        try:
            notif_count = create_all_overdue_and_upcoming_notifications(db)
            print(f"[scheduler] notifications created: {notif_count}")
            db.commit()
        except Exception:
            db.rollback()
            tracker.failed("standa_hub_hourly")
            print("[scheduler] notifications failed")
        try:
            # MRK-19: retence přenosové historie událostí (jen domain_events; Aktivita a historie zůstávají)
            from domain_events import cleanup_domain_events
            removed = cleanup_domain_events(db)
            db.commit()
            if removed:
                print(f"[scheduler] domain events retention removed: {removed}")
        except Exception:
            db.rollback()
            tracker.failed("standa_hub_hourly")
            print("[scheduler] domain events retention failed")
        try:
            from backup_service import run_backup, should_run_backup_daily
            if should_run_backup_daily():
                bid = run_backup(db)
                print(f"[scheduler] daily backup ran id={bid}")
                from models import BackupLog
                if bid != -1 and db.get(BackupLog, bid).status != "success":
                    tracker.failed("standa_hub_hourly")
        except Exception:
            tracker.failed("standa_hub_hourly")
            print("[scheduler] daily backup failed")
    except Exception:
        tracker.failed("standa_hub_hourly")
        print("[scheduler] hourly job failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
    print(f"[scheduler] hourly job finished at {datetime.utcnow().isoformat()}")


@tracker.tracked("standa_hub_reminders")
def _run_reminders_job() -> None:
    from reminder_service import process_due_reminders

    db = SessionLocal()
    try:
        stats = process_due_reminders(db)
        if stats["failed"]:
            tracker.failed("standa_hub_reminders")
        if stats["fired"] or stats["failed"]:
            print(f"[scheduler] reminders: {stats}")
    except Exception:  # noqa: BLE001 - job nesmí shodit scheduler
        try:
            db.rollback()
        except Exception:
            pass
        tracker.failed("standa_hub_reminders")
        print("[scheduler] reminders job failed")
    # Phase E: externí doručení až po zazvonění a odděleně – jeho chyba nesmí ovlivnit připomínky.
    try:
        from delivery_service import run_delivery_cycle

        dstats = run_delivery_cycle(db)
        if dstats.get("failed"):
            tracker.failed("standa_hub_reminders")
        if dstats.get("enqueued") or dstats.get("sent") or dstats.get("failed") or dstats.get("retry"):
            print(f"[scheduler] external delivery: {dstats}")
    except Exception:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        tracker.failed("standa_hub_reminders")
        print("[scheduler] external delivery failed")
    finally:
        db.close()


@tracker.tracked("standa_hub_briefing")
def _run_briefing_job() -> None:
    from briefing_service import run_scheduled

    db = SessionLocal()
    try:
        state = run_scheduled(db)
        if state == "gave_up":
            tracker.failed("standa_hub_briefing")
        if state in ("generated", "retried"):
            print(f"[scheduler] daily briefing: {state}")
    except Exception:  # noqa: BLE001 - přehled nesmí shodit scheduler ani ostatní joby
        try:
            db.rollback()
        except Exception:
            pass
        tracker.failed("standa_hub_briefing")
        print("[scheduler] daily briefing job failed")
    finally:
        db.close()


@tracker.tracked("standa_hub_weekly_review")
def _run_weekly_review_job() -> None:
    from weekly_review_service import run_scheduled

    db = SessionLocal()
    try:
        state = run_scheduled(db)
        if state == "gave_up":
            tracker.failed("standa_hub_weekly_review")
        if state in ("generated", "retried"):
            print(f"[scheduler] weekly review: {state}")
    except Exception:  # noqa: BLE001 - přehled nesmí shodit scheduler ani ostatní joby
        try:
            db.rollback()
        except Exception:
            pass
        tracker.failed("standa_hub_weekly_review")
        print("[scheduler] weekly review job failed")
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
    enabled = {
        "standa_hub_hourly": SCHEDULER_ENABLED, "standa_hub_reminders": REMINDERS_CHECK_ENABLED,
        "standa_hub_briefing": DAILY_BRIEFING_ENABLED, "standa_hub_weekly_review": WEEKLY_REVIEW_ENABLED,
    }
    jobs = [{"id": name, "enabled": active, **tracker.snapshot(name)} for name, active in enabled.items()]
    status = "disabled" if not any(enabled.values()) else "running" if _scheduler and _scheduler.running else "stopped"
    if status == "running" and any(j["enabled"] and j["status"] == "warning" for j in jobs):
        status = "degraded"
    return {"status": status, "backup_job_enabled": SCHEDULER_ENABLED, "jobs": jobs}
