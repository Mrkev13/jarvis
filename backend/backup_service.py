import os
import re
import gzip
import glob
import json
import logging
import shutil
import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import make_url

from database import SessionLocal
from models import BackupLog
from time_utils import local_day_bounds_utc, now_local
from env_config import env_bool, env_int

logger = logging.getLogger("standa_hub.backup")

BACKUP_ENABLED = env_bool("BACKUP_ENABLED", False)
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backups")
BACKUP_HOUR_OF_DAY = env_int("BACKUP_HOUR_OF_DAY", 3)
BACKUP_RETENTION_DAYS = env_int("BACKUP_RETENTION_DAYS", 30, minimum=1)
MEDIA_DIR = os.environ.get("MEDIA_DIR", "./media")

_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+pysqlite:///./standa-hub.db")

class PgDumpNotFound(RuntimeError):
    """pg_dump se nepodařilo najít – zpráva říká, co nastavit (bez přihlašovacích údajů)."""


class MediaBackupError(RuntimeError):
    """Média nelze bezpečně archivovat nebo ověřit."""


def _windows_pg_dump_candidates() -> list[str]:
    """Standardní instalace PostgreSQL na Windows: %ProgramFiles%/PostgreSQL/<verze>/bin/pg_dump.exe.
    Žádná cesta konkrétního stroje v kódu – jen proměnné prostředí Windows. Nejvyšší verze první."""
    found: list[str] = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = os.environ.get(var)
        if root:
            found += glob.glob(os.path.join(root, "PostgreSQL", "*", "bin", "pg_dump.exe"))

    def version(path: str) -> tuple:
        m = re.search(r"PostgreSQL[\\/](\d+)(?:\.(\d+))?", path)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    return sorted(set(found), key=version, reverse=True)


def find_pg_dump() -> str:
    """Cesta k pg_dump: 1) PG_DUMP_PATH, 2) PATH, 3) na Windows standardní instalace PostgreSQL.
    Explicitně nastavená, ale neexistující PG_DUMP_PATH je chyba (žádný tichý přechod na jiný pg_dump)."""
    explicit = (os.environ.get("PG_DUMP_PATH") or "").strip().strip('"')
    if explicit:
        resolved = explicit if os.path.isfile(explicit) else shutil.which(explicit)
        if not resolved:
            raise PgDumpNotFound(f"PG_DUMP_PATH ukazuje na neexistující soubor ({explicit}) – oprav cestu k pg_dump.")
        return resolved
    on_path = shutil.which("pg_dump")
    if on_path:
        return on_path
    if os.name == "nt":
        candidates = _windows_pg_dump_candidates()
        if candidates:
            return candidates[0]
    raise PgDumpNotFound(
        "pg_dump nenalezen: nastav PG_DUMP_PATH na pg_dump(.exe) (např. ve složce bin instalace PostgreSQL) "
        "nebo přidej tu složku do PATH."
    )


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


def _utc_iso(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_relative_file(path: Path, root: Path) -> Path:
    """Vrátí bezpečnou relativní cestu; symlink ven z MEDIA_DIR je chyba."""
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise MediaBackupError(f"Soubor médií opouští MEDIA_DIR: {path.name}") from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise MediaBackupError(f"Neplatná relativní cesta média: {path.name}")
    return relative


def _safe_archive_path(root: Path, relative: Path) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MediaBackupError("Cílová cesta archivu opouští kořen zálohy") from exc
    return candidate


def _copy_verified(source: Path, target: Path, expected_hash: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with open(source, "rb") as source_handle, open(temporary, "xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
        if _sha256_of_file(temporary) != expected_hash:
            raise MediaBackupError(f"SHA-256 ověření kopie selhalo: {source.name}")
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            if target.is_file() and _sha256_of_file(target) == expected_hash:
                return
            raise MediaBackupError(f"Cíl archivu byl souběžně obsazen jiným obsahem: {target.name}") from exc
        except OSError as exc:
            raise MediaBackupError(
                f"Filesystem nepodporuje bezpečný atomický commit archivu: {target.name}"
            ) from exc
    except FileExistsError as exc:
        raise MediaBackupError(f"Dočasný soubor archivu už existuje: {target.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _archive_target(archive_root: Path, relative: Path, checksum: str) -> tuple[Path, bool]:
    """První verze zachová cestu; odlišný obsah jde do neměnné historie téže cesty."""
    primary = _safe_archive_path(archive_root, relative)
    if not primary.exists():
        return primary, True
    if not primary.is_file():
        raise MediaBackupError(f"Cíl archivu není soubor: {relative.as_posix()}")
    if _sha256_of_file(primary) == checksum:
        return primary, False

    version_relative = relative.parent / ".versions" / relative.name / f"{checksum}--{relative.name}"
    version = _safe_archive_path(archive_root, version_relative)
    if not version.exists():
        return version, True
    if not version.is_file() or _sha256_of_file(version) != checksum:
        raise MediaBackupError(f"Konflikt nebo poškozená verze v archivu: {relative.as_posix()}")
    return version, False


def sync_media_archive(backup_root: Path, run_id: str) -> dict:
    """Inkrementálně archivuje MEDIA_DIR a zapíše manifest aktuálního zdrojového stavu."""
    media_root = Path(MEDIA_DIR).resolve()
    if not media_root.is_dir():
        raise MediaBackupError(f"MEDIA_DIR neexistuje nebo není složka: {MEDIA_DIR}")

    backup_root = backup_root.resolve()
    try:
        backup_root.relative_to(media_root)
    except ValueError:
        pass
    else:
        raise MediaBackupError("BACKUP_DIR nesmí ležet uvnitř MEDIA_DIR")

    archive_root = (backup_root / "media" / "archive").resolve()
    manifest_path = (backup_root / "media" / "manifests" / f"media_{run_id}.json").resolve()
    archive_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    copied = 0
    skipped = 0
    total_bytes = 0
    for source in sorted((path for path in media_root.rglob("*") if path.is_file()), key=lambda p: p.as_posix()):
        relative = _safe_relative_file(source, media_root)
        checksum = _sha256_of_file(source)
        size = source.stat().st_size
        target, needs_copy = _archive_target(archive_root, relative, checksum)
        if needs_copy:
            _copy_verified(source, target, checksum)
            copied += 1
            state = "copied"
        else:
            skipped += 1
            state = "unchanged"
        if target.stat().st_size != size or _sha256_of_file(target) != checksum:
            raise MediaBackupError(f"Archivované médium neprošlo ověření: {relative.as_posix()}")
        total_bytes += size
        entries.append({
            "relative_path": relative.as_posix(),
            "size": size,
            "sha256": checksum,
            "archive_path": target.relative_to(backup_root).as_posix(),
            "archived_at": _utc_iso(datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)),
            "status": state,
        })

    payload = {
        "schema_version": 1,
        "created_at": _utc_iso(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
    }
    _write_json_atomic(manifest_path, payload)
    manifest_hash = _sha256_of_file(manifest_path)
    if not _verify_backup(manifest_path, manifest_path.stat().st_size, manifest_hash):
        raise MediaBackupError("Manifest médií neprošel SHA-256 ověření")
    return {
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_hash,
        "file_count": len(entries),
        "copied": copied,
        "skipped": skipped,
        "total_bytes": total_bytes,
    }

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
        url = make_url(_DATABASE_URL)
        # Use the same decoded credentials as SQLAlchemy (passwords may contain
        # reserved URI characters). Never pass the password on the command line.
        user = url.username or ""
        host = url.host or "localhost"
        port = url.port or 5432
        dbname = url.database or ""
        env["PGPASSWORD"] = url.password or ""
        cmd = [
            find_pg_dump(),
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
    except PgDumpNotFound as e:
        return False, str(e)
    except FileNotFoundError:
        try:
            dst.unlink(missing_ok=True)
        except Exception:
            pass
        return False, "pg_dump se nepodařilo spustit – zkontroluj PG_DUMP_PATH / PATH"
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
        backup_ts = started.strftime("%Y%m%d_%H%M%S_%f")
        ext = "sqlite.gz" if _is_sqlite() else "pgdump.gz"
        filename = f"standa_hub_{backup_ts}.{ext}"
        backup_root = _backup_dir_path()
        dst = backup_root / filename
        metadata_path = backup_root / "runs" / f"backup_{backup_ts}.json"

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

        db_info = None
        media_info = None
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
                log.filename = str(dst)
                log.size_bytes = size_bytes
                log.checksum = checksum
                db_info = {
                    "filename": dst.relative_to(backup_root).as_posix(),
                    "size": size_bytes,
                    "sha256": checksum,
                }
        if ok:
            try:
                media_info = sync_media_archive(backup_root, backup_ts)
            except Exception as exc:
                ok = False
                err = f"media backup failed: {exc}"

        finished = datetime.utcnow()
        duration = (finished - started).total_seconds()
        metadata = {
            "schema_version": 1,
            "started_at": _utc_iso(started),
            "finished_at": _utc_iso(finished),
            "status": "success" if ok else "failed",
            "retention_days": BACKUP_RETENTION_DAYS,
            "database": db_info,
            "media": ({
                "manifest": media_info["manifest_path"].relative_to(backup_root).as_posix(),
                "manifest_sha256": media_info["manifest_sha256"],
                "file_count": media_info["file_count"],
                "copied": media_info["copied"],
                "skipped": media_info["skipped"],
                "total_bytes": media_info["total_bytes"],
            } if media_info else None),
            "error": err or None,
        }
        try:
            _write_json_atomic(metadata_path, metadata)
        except Exception as exc:
            ok = False
            err = f"backup metadata failed: {exc}"

        if ok:
            log.status = "success"
            log.duration_seconds = duration
            logger.info(
                "Backup succeeded id=%s db_bytes=%s media_files=%s media_copied=%s duration_seconds=%.3f",
                log.id, log.size_bytes, media_info["file_count"], media_info["copied"], duration,
            )
        if not ok:
            log.status = "failed"
            log.error_message = err
            log.finished_at = finished
            log.duration_seconds = duration
            logger.error("Backup failed id=%s error=%s", log.id, err)
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
            _delete_run_metadata_for_dump(Path(log.filename).name)
        db.delete(log)
        deleted += 1
    if deleted:
        db.commit()
    return deleted


def _delete_run_metadata_for_dump(dump_name: str) -> None:
    """Smaže starý run záznam a jeho manifest; neměnný media archiv ponechá."""
    backup_root = _backup_dir_path()
    runs_root = (backup_root / "runs").resolve()
    manifests_root = (backup_root / "media" / "manifests").resolve()
    if not runs_root.is_dir():
        return
    for metadata_path in runs_root.glob("backup_*.json"):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (payload.get("database") or {}).get("filename") != dump_name:
                continue
            manifest_name = (payload.get("media") or {}).get("manifest")
            if manifest_name:
                manifest_path = (backup_root / manifest_name).resolve()
                try:
                    manifest_path.relative_to(manifests_root)
                except ValueError:
                    pass
                else:
                    manifest_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Could not remove retained backup metadata %s: %s", metadata_path.name, exc)

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
