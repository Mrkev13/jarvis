"""Process-local, non-sensitive job observations; reset on process restart."""
from datetime import datetime, timezone
from functools import wraps
from threading import RLock

_lock = RLock()
_history = {}


def job_history(job_id):
    with _lock:
        return dict(_history.get(job_id, {"last_started": None, "last_run": None, "last_result": None, "running": False}))


def job_failed(job_id):
    with _lock:
        _history.setdefault(job_id, {})["last_result"] = "failed"


def tracked_job(job_id):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            with _lock:
                previous = job_history(job_id)
                _history[job_id] = {**previous, "last_started": datetime.now(timezone.utc).isoformat(), "last_result": "running", "running": True}
            try:
                return fn(*args, **kwargs)
            except Exception:
                job_failed(job_id)
                raise
            finally:
                with _lock:
                    state = _history[job_id]
                    state["last_run"] = datetime.now(timezone.utc).isoformat()
                    state["running"] = False
                    if state["last_result"] == "running":
                        state["last_result"] = "success"
        return run
    return decorate
