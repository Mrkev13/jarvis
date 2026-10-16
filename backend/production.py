"""Native production launch: explicit config, foreground Uvicorn, one scheduler owner."""
import argparse
import os
from pathlib import Path
import sys
import subprocess
import re

import bcrypt
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

_BOOL_KEYS = ('SCHEDULER_ENABLED', 'REMINDERS_CHECK_ENABLED', 'DAILY_BRIEFING_ENABLED',
              'WEEKLY_REVIEW_ENABLED', 'EXTERNAL_DELIVERY_ENABLED', 'BACKUP_ENABLED', 'RUN_ALEMBIC_UPGRADE_AT_STARTUP')
_TRUE = {'true', '1', 'yes', 'on'}
_FALSE = {'false', '0', 'no', 'off'}
_REQUIRED = ('APP_ENV', 'DATABASE_URL', 'PRODUCTION_DATABASE_NAME', 'FRONTEND_ORIGINS',
             'AUTH_PIN_HASH', 'MEDIA_DIR', 'BACKUP_DIR', *_BOOL_KEYS)


def validate_environment(env):
    if env.get('APP_ENV') != 'production':
        raise ValueError('APP_ENV must be production')
    for name in _REQUIRED:
        if not env.get(name):
            raise ValueError(f'{name} must be explicitly configured')
    if not (env.get('GROQ_API_KEY') or env.get('OPENAI_API_KEY')):
        raise ValueError('GROQ_API_KEY or OPENAI_API_KEY is required for client initialization')
    try:
        url = make_url(env['DATABASE_URL'])
        if url.get_backend_name() != 'postgresql' or not url.host or not url.database:
            raise ValueError()
    except Exception:
        raise ValueError('DATABASE_URL must be an explicit PostgreSQL URL') from None
    if url.database != env['PRODUCTION_DATABASE_NAME']:
        raise ValueError('PRODUCTION_DATABASE_NAME must match the selected database')
    for name in _BOOL_KEYS:
        if env[name].strip().lower() not in _TRUE | _FALSE:
            raise ValueError(f'{name} must be an explicit boolean')
    if env['RUN_ALEMBIC_UPGRADE_AT_STARTUP'].lower() not in _FALSE:
        raise ValueError('Production migrations must be applied explicitly before start')
    if env['BACKUP_ENABLED'].lower() in _TRUE and env['SCHEDULER_ENABLED'].lower() not in _TRUE:
        raise ValueError('BACKUP_ENABLED requires the hourly scheduler owner')
    for name in ('MEDIA_DIR', 'BACKUP_DIR'):
        if not Path(env[name]).is_absolute():
            raise ValueError(f'{name} must be an absolute production path')
    _validate_cookie_security(env)
    try:
        bcrypt.checkpw(b'validation', env['AUTH_PIN_HASH'].encode())
    except (ValueError, TypeError):
        raise ValueError('AUTH_PIN_HASH must be a valid bcrypt hash') from None


def _validate_cookie_security(env):
    """MRK-24: an HTTPS (Tailscale Serve) frontend needs a Secure session cookie, and a Secure cookie needs at least one
    HTTPS frontend – either mismatch is caught here instead of as a silent login failure. Messages never echo origins."""
    raw = (env.get('AUTH_COOKIE_SECURE') or 'false').strip().lower()
    if raw not in _TRUE | _FALSE:
        raise ValueError('AUTH_COOKIE_SECURE must be an explicit boolean')
    origins = [o.strip().lower() for o in env['FRONTEND_ORIGINS'].split(',') if o.strip()]
    has_https = any(o.startswith('https://') for o in origins)
    if has_https and raw not in _TRUE:
        raise ValueError('An https FRONTEND_ORIGINS entry requires AUTH_COOKIE_SECURE=true')
    if raw in _TRUE and not has_https:
        raise ValueError('AUTH_COOKIE_SECURE=true requires an https FRONTEND_ORIGINS entry')


def load_production_environment(path):
    if not Path(path).is_file():
        raise ValueError('Production env file does not exist')
    # No interpolation of passwords/hash characters; validate FILE values rather than
    # allowing an inherited development DATABASE_URL to satisfy missing configuration.
    values = dotenv_values(path, interpolate=False)
    validate_environment(values)
    os.environ.update({key: value for key, value in values.items() if value is not None})
    os.environ['PYTHON_DOTENV_DISABLED'] = 'true'


def guard_production_environment():
    """Also protect the documented direct `python -m uvicorn main:app` launch."""
    if os.environ.get('APP_ENV') == 'production':
        os.environ['PYTHON_DOTENV_DISABLED'] = 'true'
        validate_environment(os.environ)
        if os.environ.get('MONITORING_LOG_PATH'):
            from monitoring_logging import configure_monitoring_logger
            try:
                configure_monitoring_logger(os.environ['MONITORING_LOG_PATH'])
            except (ValueError, OSError):
                raise ValueError('Monitoring log configuration unavailable') from None


def resolve_commit():
    try:
        result = subprocess.run(['git', '-C', str(Path(__file__).resolve().parent), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, timeout=3, check=False)
        value = result.stdout.strip()
        return value if result.returncode == 0 and re.fullmatch(r'[a-fA-F0-9]{40}', value) else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def run_server(command):
    # Windows exec does not preserve the supervised PID. Keep this launcher alive
    # until Uvicorn exits so PowerShell/Task Scheduler can observe a worker failure.
    if os.name == 'nt':
        try:
            return subprocess.run(command, check=False).returncode
        except KeyboardInterrupt:
            return 130
    os.execv(sys.executable, command)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--check', action='store_true', help='Validate production configuration without starting services')
    args = parser.parse_args(argv)
    try:
        load_production_environment(args.env_file.resolve())
    except (ValueError, OSError):
        # The parser emits a fixed message, never a value/path from a damaged file.
        parser.error('Invalid production configuration; verify required keys in the production template')
    if args.check:
        print('Production configuration valid')
        return
    if not os.environ.get('APP_COMMIT'):
        os.environ['APP_COMMIT'] = resolve_commit()
    log_path = os.environ.get('MONITORING_LOG_PATH')
    if log_path:
        from monitoring_logging import configure_monitoring_logger
        try:
            configure_monitoring_logger(log_path)
        except (ValueError, OSError):
            parser.error('Monitoring log configuration unavailable')
    os.chdir(Path(__file__).resolve().parent)
    return run_server([sys.executable, '-m', 'uvicorn', 'main:app', '--host', args.host,
                             '--port', str(args.port), '--workers', '1'])


if __name__ == '__main__':
    raise SystemExit(main())
