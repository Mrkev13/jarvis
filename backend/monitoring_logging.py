"""Opt-in, isolated rotating monitoring logs with an allowlist, not regex redaction.

Never attach this handler to the root logger. Existing application logs are outside
this boundary and require a separate call-site audit before central collection.
"""
import json
import logging
import math
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SIGNALS = {'backup', 'scheduler', 'off_machine', 'groq_budget', 'disk'}
_STATES = {'ok', 'warning', 'critical', 'unknown', 'disabled'}
_NUMBERS = {'age_seconds', 'free_bytes', 'free_percent', 'consecutive_failures'}


class MonitoringFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        observation = getattr(record, 'monitoring', {})
        safe = {}
        if isinstance(observation, dict):
            if isinstance(observation.get('signal'), str) and observation['signal'] in _SIGNALS:
                safe['signal'] = observation['signal']
            if isinstance(observation.get('state'), str) and observation['state'] in _STATES:
                safe['state'] = observation['state']
            for key in _NUMBERS:
                value = observation.get(key)
                if type(value) in (int, float) and 0 <= value <= 2 ** 63 - 1 and math.isfinite(value):
                    safe[key] = value
        # Deliberately omit message, args, exception, stack, paths and unknown fields.
        return json.dumps(safe, allow_nan=False, sort_keys=True)


class SafeRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # logging's default prints the original message and exception to stderr.
        # Failure visibility must never bypass the allowlist.
        try:
            if sys.stderr is not None:
                sys.stderr.write('monitoring_log_write_failed\n')
        except (OSError, ValueError):
            pass


def configure_monitoring_logger(path: str | Path, *, max_bytes: int = 2 * 1024 ** 2,
                                backup_count: int = 3) -> logging.Logger:
    """Explicit runtime opt-in; caller supplies a protected, writable log directory."""
    if max_bytes <= 0 or backup_count < 1:
        raise ValueError('Monitoring rotation requires positive size and retention')
    target = str(Path(path).resolve())
    logger = logging.getLogger('standa_hub.monitoring')
    for handler in logger.handlers:
        if (len(logger.handlers) == 1 and isinstance(handler, SafeRotatingFileHandler) and handler.baseFilename == target
                and handler.maxBytes == max_bytes and handler.backupCount == backup_count):
            handler.setFormatter(MonitoringFormatter())
            logger.setLevel(logging.INFO)
            logger.propagate = False
            return logger
    handler = SafeRotatingFileHandler(target, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
    handler.setFormatter(MonitoringFormatter())
    for previous in logger.handlers[:]:
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
