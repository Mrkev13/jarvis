"""Platform-neutral production launcher: explicit config, one scheduler owner."""
import argparse
import os
from pathlib import Path
import sys

import bcrypt
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


def validate_environment(env):
    if env.get("APP_ENV") != "production":
        raise ValueError("APP_ENV must be production")
    if not env.get("DATABASE_URL"):
        raise ValueError("DATABASE_URL is required; no development DB fallback")
    try:
        url = make_url(env["DATABASE_URL"])
    except Exception:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
    if url.get_backend_name() != "postgresql":
        raise ValueError("production requires PostgreSQL")
    if not env.get("PRODUCTION_DATABASE_NAME") or url.database != env["PRODUCTION_DATABASE_NAME"]:
        raise ValueError("PRODUCTION_DATABASE_NAME must explicitly match DATABASE_URL")
    for name in ("FRONTEND_ORIGINS", "AUTH_PIN_HASH", "MEDIA_DIR", "BACKUP_DIR", "GROQ_API_KEY", "SCHEDULER_ENABLED", "REMINDERS_CHECK_ENABLED", "DAILY_BRIEFING_ENABLED", "WEEKLY_REVIEW_ENABLED", "BACKUP_ENABLED", "RUN_ALEMBIC_UPGRADE_AT_STARTUP"):
        if not env.get(name):
            raise ValueError(f"{name} must be explicitly configured")
    for name in ("SCHEDULER_ENABLED", "REMINDERS_CHECK_ENABLED", "DAILY_BRIEFING_ENABLED", "WEEKLY_REVIEW_ENABLED", "BACKUP_ENABLED", "RUN_ALEMBIC_UPGRADE_AT_STARTUP"):
        if env[name].strip().lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise ValueError(f"{name} must be an explicit boolean")
    for name in ("MEDIA_DIR", "BACKUP_DIR"):
        if not Path(env[name]).is_absolute():
            raise ValueError(f"{name} must be an absolute production path")
    try:
        bcrypt.checkpw(b"validation", env["AUTH_PIN_HASH"].encode())
    except ValueError:
        raise ValueError("AUTH_PIN_HASH must be a valid bcrypt hash") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("production env file does not exist")
        load_dotenv(args.env_file.resolve(), override=False)
    try:
        validate_environment(os.environ)
    except ValueError as exc:
        parser.error(str(exc))
    os.chdir(Path(__file__).resolve().parent)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app", "--host", args.host, "--port", str(args.port), "--workers", "1"])


if __name__ == "__main__":
    main()
