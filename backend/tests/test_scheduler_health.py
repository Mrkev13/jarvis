from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest


def test_tracker_success_failures_and_recovery():
    from scheduler_health import JobTracker
    tracker = JobTracker(clock=lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))
    def broken():
        raise RuntimeError('secret-canary')
    run = tracker.tracked('standa_hub_reminders')(broken)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            run()
    state = tracker.snapshot('standa_hub_reminders')
    assert state['consecutive_failures'] == 3
    assert state['last_failure_at'] and state['last_finished_at']
    assert state['last_success_at'] is None
    assert state['status'] == 'warning'
    tracker.tracked('standa_hub_reminders')(lambda: None)()
    state = tracker.snapshot('standa_hub_reminders')
    assert state['consecutive_failures'] == 0
    assert state['last_success_at'] and state['last_failure_at']
    assert state['last_result'] == 'success'
    assert 'secret-canary' not in str(state)


def test_caught_failure_and_fresh_tracker_unknown():
    from scheduler_health import JobTracker
    tracker = JobTracker()
    assert tracker.snapshot('standa_hub_hourly')['last_result'] is None
    tracker.tracked('standa_hub_hourly')(lambda: tracker.failed('standa_hub_hourly'))()
    assert tracker.snapshot('standa_hub_hourly')['last_result'] == 'failed'
    assert tracker.snapshot('standa_hub_hourly')['consecutive_failures'] == 1


def test_scheduler_snapshot_stopped_disabled_and_streak():
    import scheduler_service as service
    from scheduler_health import tracker
    with patch.object(service, 'SCHEDULER_ENABLED', False), patch.object(service, 'REMINDERS_CHECK_ENABLED', False), \
         patch.object(service, 'DAILY_BRIEFING_ENABLED', False), patch.object(service, 'WEEKLY_REVIEW_ENABLED', False):
        assert service.scheduler_snapshot()['status'] == 'disabled'
    with patch.object(service, 'REMINDERS_CHECK_ENABLED', True), patch.object(service, '_scheduler', None):
        assert service.scheduler_snapshot()['status'] == 'stopped'
    fake = Mock(running=True)
    with patch.object(service, 'REMINDERS_CHECK_ENABLED', True), patch.object(service, '_scheduler', fake):
        for _ in range(3):
            tracker.tracked('standa_hub_reminders')(lambda: tracker.failed('standa_hub_reminders'))()
        try:
            assert service.scheduler_snapshot()['status'] == 'degraded'
        finally:
            tracker.tracked('standa_hub_reminders')(lambda: None)()


def test_hourly_retention_kept_and_error_safe(caplog, capsys):
    import scheduler_service as service
    from scheduler_health import tracker
    db = Mock()
    access = Mock()
    access.contributions.return_value = []
    with patch.object(service, 'SessionLocal', return_value=db), patch.object(service, 'current_access', return_value=access), \
         patch.object(service, 'create_all_overdue_and_upcoming_notifications', side_effect=RuntimeError('secret-canary')), \
         patch('domain_events.cleanup_domain_events', return_value=4) as retention, \
         patch('backup_service.should_run_backup_daily', return_value=False):
        service._run_hourly_job()
        retention.assert_called_once_with(db)
    assert tracker.snapshot('standa_hub_hourly')['last_result'] == 'failed'
    assert 'secret-canary' not in caplog.text + capsys.readouterr().out
