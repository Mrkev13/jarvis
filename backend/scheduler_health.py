"""Thread-safe process-local job observations. Never retain exception text or payloads."""
import logging
from datetime import datetime, timezone
from functools import wraps
from threading import RLock
from time import monotonic

from monitoring_service import job_state

JOB_IDS = frozenset({'standa_hub_hourly', 'standa_hub_reminders', 'standa_hub_briefing', 'standa_hub_weekly_review'})


class JobTracker:
    def __init__(self, clock=None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._history = {}

    def snapshot(self, job_id):
        if job_id not in JOB_IDS:
            raise ValueError('Unknown scheduler job')
        with self._lock:
            state = dict(self._history.get(job_id, {
                'last_started_at': None, 'last_finished_at': None, 'last_success_at': None,
                'last_failure_at': None, 'last_result': None, 'consecutive_failures': 0,
                'running': False, 'duration_seconds': None,
            }))
        state['status'] = job_state(state['consecutive_failures']) if state['last_result'] else 'unknown'
        return state

    def failed(self, job_id):
        # Caught substep errors count once per overall run, not once per substep.
        with self._lock:
            if job_id in self._history and self._history[job_id]['running']:
                self._history[job_id]['last_result'] = 'failed'

    def tracked(self, job_id):
        if job_id not in JOB_IDS:
            raise ValueError('Unknown scheduler job')
        def decorate(fn):
            @wraps(fn)
            def run(*args, **kwargs):
                with self._lock:
                    state = self.snapshot(job_id)
                    state.pop('status')
                    state.update(last_started_at=self._clock().isoformat(), running=True, last_result='running')
                    self._history[job_id] = state
                started = monotonic()
                try:
                    return fn(*args, **kwargs)
                except Exception:
                    self.failed(job_id)
                    raise
                finally:
                    with self._lock:
                        state = self._history[job_id]
                        stamp = self._clock().isoformat()
                        state.update(last_finished_at=stamp, running=False,
                                     duration_seconds=round(max(0, monotonic()-started), 3))
                        if state['last_result'] == 'failed':
                            state['last_failure_at'] = stamp
                            state['consecutive_failures'] += 1
                        else:
                            state.update(last_result='success', last_success_at=stamp, consecutive_failures=0)
                        logger = logging.getLogger('standa_hub.monitoring')
                        if logger.handlers:
                            logger.info('', extra={'monitoring': {'signal': 'scheduler',
                                        'state': job_state(state['consecutive_failures']),
                                        'consecutive_failures': state['consecutive_failures']}})
            return run
        return decorate


tracker = JobTracker()
