"""Monitoring foundations never call providers or mutate application state."""
import json

import pytest

from monitoring_service import backup_state, disk_state, job_state, daily_budget_state, version_metadata
from monitoring_logging import configure_monitoring_logger


def test_backup_boundary_and_failed_attempt():
    assert backup_state(26 * 3600) == 'ok'
    assert backup_state(26 * 3600 + 1) == 'warning'
    assert backup_state(60, last_attempt_failed=True) == 'warning'
    assert backup_state(None) == 'unknown'
    assert backup_state(-1) == 'unknown'
    assert backup_state(float('nan')) == 'unknown'


@pytest.mark.parametrize('failures,expected', [(None, 'unknown'), (0, 'ok'), (2, 'ok'), (3, 'warning'), (10, 'warning')])
def test_job_failure_threshold(failures, expected):
    assert job_state(failures) == expected


def test_disk_thresholds_and_invalid_observation():
    gib = 1024 ** 3
    assert disk_state(20 * gib, 2 * gib) == 'ok'
    assert disk_state(20 * gib, 2 * gib - 1) == 'warning'
    assert disk_state(100 * gib, 5 * gib) == 'warning'
    assert disk_state(20 * gib, 512 * 1024 ** 2 - 1) == 'critical'
    assert disk_state(0, 0) == 'unknown'
    assert disk_state(10, 11) == 'unknown'


def test_daily_budget_requires_explicit_observation():
    assert daily_budget_state(None) == 'unknown'
    assert daily_budget_state(False) == 'ok'
    assert daily_budget_state(True) == 'warning'


def test_version_does_not_read_git_or_expose_invalid_values():
    assert version_metadata({}) == {'version': None, 'commit': None}
    assert version_metadata({'APP_VERSION': '1.2.3-rc.1+build.7'})['version'] == '1.2.3-rc.1+build.7'
    assert version_metadata({'APP_VERSION': '1.2.3-..'})['version'] is None
    assert version_metadata({'APP_VERSION': '١.٢.٣'})['version'] is None
    assert version_metadata({'APP_VERSION': '1.2.3', 'APP_COMMIT': 'abcdef1234567'}) == {'version': '1.2.3', 'commit': 'abcdef1234567'}
    assert version_metadata({'APP_VERSION': '/private/name', 'APP_COMMIT': 'secret'}) == {'version': None, 'commit': None}


def test_logger_suppresses_private_messages_exceptions_and_untrusted_fields(tmp_path):
    path = tmp_path / 'monitoring.log'
    logger = configure_monitoring_logger(path)
    try:
        raise ValueError('private patient data token=secret')
    except ValueError:
        logger.exception('https://user:password@example.com/private', extra={'monitoring': {'signal': 'backup', 'state': 'warning', 'detail': 'secret'}})
    logger.info('ignored', extra={'monitoring': {'signal': 'backup', 'state': 'warning', 'age_seconds': 95000}})
    logger.info('ignored', extra={'monitoring': {'signal': 'secret', 'state': 'private', 'age_seconds': 'secret'}})
    content = path.read_text()
    assert not any(value in content for value in ['secret', 'patient', 'password', 'example.com', 'Traceback'])
    records = [json.loads(line) for line in content.splitlines()]
    assert records[1]['age_seconds'] == 95000
    assert records[2] == {}
    logger.handlers[0].close()


def test_rotation_and_reconfiguration_are_bounded_and_idempotent(tmp_path):
    path = tmp_path / 'monitoring.log'
    logger = configure_monitoring_logger(path, max_bytes=100, backup_count=2)
    assert configure_monitoring_logger(path, max_bytes=100, backup_count=2) is logger
    assert len(logger.handlers) == 1
    assert logger.propagate is False
    for _ in range(30):
        logger.info('ignored', extra={'monitoring': {'signal': 'disk', 'state': 'warning'}})
    assert path.exists()
    assert (tmp_path / 'monitoring.log.1').exists()
    assert len(list(tmp_path.iterdir())) <= 3
    logger.handlers[0].close()


def test_untrusted_structured_values_and_invalid_rotation(tmp_path):
    logger = configure_monitoring_logger(tmp_path / 'safe.log')
    logger.info('secret', extra={'monitoring': {'signal': [], 'state': {}, 'age_seconds': float('inf')}})
    assert (tmp_path / 'safe.log').read_text().strip() == '{}'
    logger.handlers[0].close()
    with pytest.raises(ValueError):
        configure_monitoring_logger(tmp_path / 'invalid.log', backup_count=0)


def test_logger_failure_never_echoes_original_record(tmp_path, capsys, monkeypatch):
    logger = configure_monitoring_logger(tmp_path / 'failure.log')
    logger.info('dummy-secret-canary', extra={'monitoring': {'age_seconds': 10 ** 1000}})
    assert 'dummy-secret-canary' not in capsys.readouterr().err
    handler = logger.handlers[0]

    def fail_format(record):
        raise ValueError('private-exception-canary')

    monkeypatch.setattr(handler.formatter, 'format', fail_format)
    logger.error('dummy-secret-canary')
    error = capsys.readouterr().err
    assert error == 'monitoring_log_write_failed\n'
    assert 'private-exception-canary' not in error
    handler.close()


def test_logger_io_failure_is_sanitized(tmp_path, capsys, monkeypatch):
    logger = configure_monitoring_logger(tmp_path / 'io.log')
    handler = logger.handlers[0]

    def fail_write(value):
        raise OSError('private-path-canary')

    monkeypatch.setattr(handler.stream, 'write', fail_write)
    logger.error('dummy-secret-canary')
    assert capsys.readouterr().err == 'monitoring_log_write_failed\n'
    handler.close()


def test_configuration_replaces_unsafe_preexisting_handler(tmp_path):
    import logging
    from logging.handlers import RotatingFileHandler

    path = tmp_path / 'existing.log'
    logger = logging.getLogger('standa_hub.monitoring')
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    unsafe = RotatingFileHandler(path, maxBytes=100, backupCount=2)
    logger.addHandler(unsafe)
    logger.propagate = True
    configure_monitoring_logger(path, max_bytes=100, backup_count=2)
    logger.info('dummy-secret-canary')
    assert 'dummy-secret-canary' not in path.read_text()
    assert logger.propagate is False
    logger.handlers[0].close()
