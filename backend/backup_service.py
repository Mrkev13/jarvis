import os
import gzip
import shutil
import hashlib
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import make_url

from database import SessionLocal
from models import BackupLog
from time_utils import local_day_bounds_utc, now_local
from env_config import env_bool, env_int

BACKUP_ENABLED = env_bool("BACKUP_ENABLED", False)
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backups")
BACKUP_HOUR_OF_DAY = env_int("BACKUP_HOUR_OF_DAY", 3)
BACKUP_RETENTION_DAYS = env_int("BACKUP_RETENTION_DAYS", 30, minimum=1)

_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+pysqlite:///./standa-hub.db")

def _backup_dir_path() -> Path:
    p = Path(BACKUP_DIR).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _is_sqlite() -> bool:
    return _DATABASE_URL.startswith("sqlite")

def _sqlite_file_path() -> Optional[Path]:
    if not _is_sqlite():
        return None
    # make_url zvládne relativní (sqlite:///./x.db) i absolutní cestu na Linuxu (sqlite:////tmp/x.db)
    # i Windows (sqlite:///C:\\x.db); dřívější lstrip("/") z absolutní POSIX cesty udělal relativní.
    raw = make_url(_DATABASE_URL).database or ""
    if not raw or raw == ":memory:":
        return None
    p = Path(raw).resolve()
    if p.exists():
        return p
    backend_dir = Path(__file__).resolve().parent
    p2 = (backend_dir / raw).resolve()
    if p2.exists():
        return p2
    return None

def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _backup_sqlite(dst: Path) -> tuple[bool, str]:
    src = _sqlite_file_path()
    if src is None:
        return False, "SQLite file not found"
    try:
        with open(src, "rb") as fin, open(dst.with_suffix(".tmp"), "wb") as fout:
            shutil.copyfileobj(fin, fout)
        with open(dst.with_suffix(".tmp"), "rb") as fin, gzip.open(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        dst.with_suffix(".tmp").unlink(missing_ok=True)
        return True, ""
    except Exception as e:
        try:
            dst.with_suffix(".tmp").unlink(missing_ok=True)
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"sqlite backup failed: {e}"

def _backup_postgres(dst: Path) -> tuple[bool, str]:
    try:
        env = os.environ.copy()
        url = _DATABASE_URL
        stripped = url.split("://", 1)[1]
        userpass, hostpath = stripped.split("@", 1)
        user, password = userpass.split(":", 1) if ":" in userpass else (userpass, "")
        hostport, dbname = hostpath.split("/", 1)
        host, port = hostport.split(":", 1) if ":" in hostport else (hostport, "5432")
        env["PGPASSWORD"] = password
        cmd = [
            "pg_dump",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            dbname,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        with gzip.open(dst, "wb") as gz:
            shutil.copyfileobj(proc.stdout, gz)
        _, stderr_b = proc.communicate(timeout=600)
        if proc.returncode != 0:
            try:
                dst.unlink(missing_ok=True)
            except Exception:
                pass
            err = stderr_b.decode("utf-8", errors="replace") if stderr_b else "unknown"
            return False, f"pg_dump failed ({proc.returncode}): {err[:500]}"
        return True, ""
    except FileNotFoundError as _nf:
        try:
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        return False, "pg_dump not found in PATH"
    except subprocess.TimeoutExpired:
        try:
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        return False, "pg_dump timeout"
    except Exception as e:
        try:
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"postgres backup failed: {e}"

def _verify_backup(dst: Path, expected_size: int, checksum_expected: str) -> bool:
    try:
        if not dst.exists():
            return False
        if dst.stat().st_size != expected_size:
            return False
        return _sha256_of_file(dst) == checksum_expected
    except Exception:
        return False

def run_backup(db_session=None) -> int:
    if not BACKUP_ENABLED:
        return -1
    db = db_session or SessionLocal()
    try:
        started = datetime.utcnow()
        backup_ts = started.strftime("%Y%m%d_%H%M%S")
        ext = "sqlite.gz" if _is_sqlite() else "pgdump.gz"
        filename = f"standa_hub_{backup_ts}.{ext}"
        dst = _backup_dir_path() / filename

        log = BackupLog(
            started_at=started,
            status="running",
            retention_days=BACKUP_RETENTION_DAYS,
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        ok = False
        err = ""
        if _is_sqlite():
            ok, err = _backup_sqlite(dst)
        else:
            ok, err = _backup_postgres(dst)

        finished = datetime.utcnow()
        duration = (finished - started).total_seconds()
        if ok:
            size_bytes = dst.stat().st_size
            checksum = _sha256_of_file(dst)
            verified = _verify_backup(dst, size_bytes, checksum)
            if not verified:
                ok = False
                err = f"verify failed (size={size_bytes}, checksum mismatch)"
                try:
                    dst.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                log.status = "success"
                log.filename = str(dst)
                log.size_bytes = size_bytes
                log.checksum = checksum
                log.duration_seconds = duration
        if not ok:
            log.status = "failed"
            log.error_message = err
            log.finished_at = finished
        log.finished_at = finished
        db.commit()

        _apply_retention(db)
        return log.id or -1
    finally:
        if db_session is None:
            db.close()

def _apply_retention(db) -> int:
    cutoff = datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)
    old_logs = db.query(BackupLog).filter(BackupLog.started_at < cutoff).all()
    deleted = 0
    for log in old_logs:
        if log.filename:
            try:
                Path(log.filename).unlink(missing_ok=True)
            except Exception:
                pass
        db.delete(log)
        deleted += 1
    if deleted:
        db.commit()
    return deleted

def list_backups(db_session=None, limit=20) -> list[dict]:
    db = db_session or SessionLocal()
    try:
        rows = db.query(BackupLog).order_by(BackupLog.started_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "filename": r.filename,
                "size_bytes": r.size_bytes,
                "checksum": r.checksum,
                "duration_seconds": r.duration_seconds,
                "error_message": r.error_message,
                "retention_days": r.retention_days,
            }
            for r in rows
        ]
    finally:
        if db_session is None:
            db.close()

def should_run_backup_daily(hour_of_day: int = BACKUP_HOUR_OF_DAY, now_utc: datetime | None = None) -> bool:
    """hour_of_day (BACKUP_HOUR_OF_DAY) je hodina v Europe/Prague; „dnes" = pražský den."""
    now_utc = now_utc if now_utc is not None else datetime.utcnow()
    local_now = now_local(now_utc)
    if local_now.hour < hour_of_day:
        return False
    today_start_utc, _ = local_day_bounds_utc(local_now.date())
    db = SessionLocal()
    try:
        ran = db.query(BackupLog).filter(
            BackupLog.status == "success",
            BackupLog.started_at >= today_start_utc,
        ).first()
        return ran is None
    finally:
        db.close()
