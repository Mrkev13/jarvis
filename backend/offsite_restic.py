"""Off-machine backups: verified local backup runs → restic repository on Backblaze B2 (S3 API). MRK-57.

Source of truth stays the local pipeline (backup_service.run_backup). This module only uploads a run that
`offsite_backup._load_source_run` has re-verified (run JSON, dump SHA-256, manifest and every media file), never the
live DB or MEDIA_DIR. The local backup never depends on the network: the scheduler calls `run_scheduled` after the
local step, in its own try/except.

Security: credentials and the repository URL reach restic only through the child-process environment, read from
protected files (ACL SYSTEM + Administrators) at call time. Command lines hold no secrets. Raw restic output is used
only to pick an allowlisted outcome code; it is never logged, stored or returned.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from env_config import env_str

HOST = "standa-hub"            # stable restic host: the future mini PC continues the same snapshot lineage
TAG = "standa-hub"
KEEP = {"daily": 14, "weekly": 8, "monthly": 12}
MAX_AGE_SECONDS = 26 * 3600    # same freshness policy as the local backup (MRK-26)
CHECK_INTERVAL = timedelta(hours=20)       # metadata check ~daily
MAINTENANCE_INTERVAL = timedelta(days=7)   # sampled data check + forget/prune weekly
DATA_SUBSET = "5%"
SECRET_KEYS = {"RESTIC_REPOSITORY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"}

OUTCOMES = {
    "success", "already_uploaded", "no_source", "busy", "not_configured", "misconfigured", "source_invalid",
    "auth_failed", "network_unavailable", "repository_missing", "wrong_password", "locked", "timeout",
    "interrupted", "source_incomplete", "check_failed", "restic_failed",
}

_lock = threading.Lock()   # one off-site operation per process; restic's repository lock guards the rest


class OffsiteConfigError(ValueError):
    """Enabled but unusable configuration. Message is a fixed category, never a value or path."""


@dataclass(frozen=True)
class OffsiteConfig:
    restic_path: Path
    secrets_file: Path
    password_file: Path
    maintenance_secrets_file: Optional[Path]
    backup_dir: Path
    timeout_seconds: int
    allow_local_repository: bool = False   # tests/drills only; production requires s3:https://


def enabled(env=os.environ) -> bool:
    return str(env.get("OFFSITE_BACKUP_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


def load_config(env=os.environ) -> Optional[OffsiteConfig]:
    """None when off-site backup is disabled; OffsiteConfigError when enabled but incomplete."""
    if not enabled(env):
        return None
    paths = {}
    for key in ("OFFSITE_RESTIC_PATH", "OFFSITE_SECRETS_FILE", "OFFSITE_RESTIC_PASSWORD_FILE", "BACKUP_DIR"):
        value = str(env.get(key) or "").strip().strip('"')
        if not value or not Path(value).is_absolute():
            raise OffsiteConfigError(f"{key} must be an absolute path")
        paths[key] = Path(value)
    maintenance = str(env.get("OFFSITE_MAINTENANCE_SECRETS_FILE") or "").strip().strip('"')
    if maintenance and not Path(maintenance).is_absolute():
        raise OffsiteConfigError("OFFSITE_MAINTENANCE_SECRETS_FILE must be an absolute path")
    if paths["OFFSITE_SECRETS_FILE"] == paths["OFFSITE_RESTIC_PASSWORD_FILE"]:
        raise OffsiteConfigError("the restic password must be stored separately from the B2 credentials")
    try:
        timeout = int(env.get("OFFSITE_TIMEOUT_SECONDS") or 3600)
    except ValueError:
        raise OffsiteConfigError("OFFSITE_TIMEOUT_SECONDS must be an integer") from None
    return OffsiteConfig(restic_path=paths["OFFSITE_RESTIC_PATH"], secrets_file=paths["OFFSITE_SECRETS_FILE"],
                         password_file=paths["OFFSITE_RESTIC_PASSWORD_FILE"],
                         maintenance_secrets_file=Path(maintenance) if maintenance else None,
                         backup_dir=paths["BACKUP_DIR"], timeout_seconds=max(60, timeout),
                         allow_local_repository=str(env.get("OFFSITE_ALLOW_LOCAL_REPOSITORY", "")).lower() == "true")


def read_secrets(path: Path, *, allow_local: bool = False) -> dict[str, str]:
    """KEY=VALUE file with an allowlist; values never leave this process except into restic's environment."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, ValueError):   # ValueError covers UnicodeDecodeError (e.g. saved as UTF-16 by an editor)
        raise OffsiteConfigError("secrets file unreadable (expected UTF-8 KEY=VALUE lines)") from None
    values: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in SECRET_KEYS:
            raise OffsiteConfigError("secrets file has an unknown or malformed entry")
        values[key] = value.strip().strip('"')
    repository = values.get("RESTIC_REPOSITORY", "")
    if repository.startswith("s3:https://"):
        if not values.get("AWS_ACCESS_KEY_ID") or not values.get("AWS_SECRET_ACCESS_KEY"):
            raise OffsiteConfigError("secrets file lacks the S3 application key")
    elif not (allow_local and repository and Path(repository).is_absolute()):
        raise OffsiteConfigError("RESTIC_REPOSITORY must be an s3:https:// repository")
    return values


# ---------- restic process ----------

@dataclass(frozen=True)
class ResticResult:
    code: int
    stdout: str
    stderr: str   # classification only; never logged/stored


Runner = Callable[[list[str], dict, Path, int], ResticResult]


def _subprocess_runner(args: list[str], env: dict, cwd: Path, timeout: int) -> ResticResult:
    try:
        proc = subprocess.run(args, env=env, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ResticResult(-1, "", "timeout")
    except OSError:
        return ResticResult(-2, "", "restic not executable")
    return ResticResult(proc.returncode, proc.stdout, proc.stderr)


def _child_env(config: OffsiteConfig, secrets: dict[str, str]) -> dict[str, str]:
    # Minimal inherited environment: no app secrets (DATABASE_URL, AUTH_PIN_HASH, VAPID…) reach restic.
    env = {k: os.environ[k] for k in ("SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
                                      "USERPROFILE", "HOME", "PATH") if k in os.environ}
    env.update(secrets)
    env["RESTIC_PASSWORD_FILE"] = str(config.password_file)
    env["RESTIC_PROGRESS_FPS"] = "0.0166"
    return env


def classify(result: ResticResult) -> str:
    if result.code == 0:
        return "success"
    if result.code == -1:
        return "timeout"
    if result.code == -2:
        return "misconfigured"
    known = {10: "repository_missing", 11: "locked", 12: "wrong_password", 130: "interrupted", 3: "source_incomplete"}
    if result.code in known:
        return known[result.code]
    err = result.stderr.lower()
    if any(s in err for s in ("accessdenied", "invalidaccesskeyid", "signaturedoesnotmatch", "forbidden",
                              "status code: 403", "status code: 401", "unauthorized")):
        return "auth_failed"
    if any(s in err for s in ("no such host", "dial tcp", "connection refused", "i/o timeout", "tls handshake",
                              "network is unreachable", "connection reset", "context deadline exceeded")):
        return "network_unavailable"
    if "unable to open config file" in err or "repository does not exist" in err or "nosuchbucket" in err:
        return "repository_missing"
    if "wrong password" in err:
        return "wrong_password"
    return "restic_failed"


class Restic:
    """One restic invocation context. `deadline` (time.monotonic) bounds ALL calls of a cycle together, so an
    unreachable B2 can never hold the hourly job longer than OFFSITE_TIMEOUT_SECONDS in total."""

    def __init__(self, config: OffsiteConfig, runner: Runner = _subprocess_runner, *, maintenance: bool = False,
                 deadline: Optional[float] = None):
        source = config.maintenance_secrets_file if (maintenance and config.maintenance_secrets_file) else config.secrets_file
        if not config.password_file.is_file():
            raise OffsiteConfigError("restic password file missing")
        self.config, self.runner = config, runner
        self.deadline = deadline if deadline is not None else time.monotonic() + config.timeout_seconds
        self.env = _child_env(config, read_secrets(source, allow_local=config.allow_local_repository))

    def run(self, *args: str, cwd: Optional[Path] = None) -> ResticResult:
        remaining = int(self.deadline - time.monotonic())
        if remaining <= 0:
            return ResticResult(-1, "", "timeout")
        return self.runner([str(self.config.restic_path), *args], self.env, cwd or self.config.backup_dir,
                           min(remaining, self.config.timeout_seconds))


def forget_args() -> list[str]:
    # Snapshot paths differ per run (dump names), so group by host only and filter by our tag - otherwise every
    # snapshot is its own group and the policy would never remove anything.
    return ["forget", "--tag", TAG, "--group-by", "host", "--keep-daily", str(KEEP["daily"]),
            "--keep-weekly", str(KEEP["weekly"]), "--keep-monthly", str(KEEP["monthly"]), "--prune"]


def _run_tag(run_id: str) -> str:
    return f"run:{run_id}"


COMPLETE_TAG = "complete"   # added only after a clean exit - an exit-3 (partial) snapshot never counts as uploaded


def _existing_snapshot(restic: Restic, run_id: str) -> tuple[str, Optional[str]]:
    result = restic.run("snapshots", "--json", "--tag", f"{TAG},{_run_tag(run_id)},{COMPLETE_TAG}")
    outcome = classify(result)
    if outcome != "success":
        return outcome, None
    try:
        snapshots = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return "restic_failed", None
    return "success", (snapshots[-1].get("id") if snapshots else None)


def _summary(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("message_type") == "summary":
            return message
    return {}


# ---------- local source ----------

def latest_local_run(db, backup_dir: Path):
    """Newest successful BackupLog and the run JSON that belongs to its dump, or (None, None)."""
    from models import BackupLog
    log = (db.query(BackupLog).filter(BackupLog.status == "success", BackupLog.filename.isnot(None))
           .order_by(BackupLog.finished_at.desc(), BackupLog.id.desc()).first())
    if not log:
        return None, None
    dump_name = Path(log.filename).name
    for path in sorted((backup_dir / "runs").glob("backup_*.json"), reverse=True):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (meta.get("database") or {}).get("filename") == dump_name:
            return log, path
    return log, None


# ---------- state / alerts ----------

def _utcnow() -> datetime:
    from time_utils import utc_now   # canonical naive-UTC clock (AGENTS.md)
    return utc_now()


def _record(db, operation: str, **fields):
    from models import OffsiteBackupRun
    row = OffsiteBackupRun(operation=operation, status="running", started_at=_utcnow(), **fields)
    db.add(row)
    db.commit()
    return row


def _finish(db, row, outcome: str, **fields) -> str:
    assert outcome in OUTCOMES
    row.status = "success" if outcome in {"success", "already_uploaded"} else "failed"
    row.outcome, row.finished_at = outcome, _utcnow()
    row.duration_seconds = (row.finished_at - row.started_at).total_seconds()
    for key, value in fields.items():
        setattr(row, key, value)
    _alert(db, row.operation, outcome)
    db.commit()
    _log(row.operation, outcome)
    return outcome


def _alert(db, operation: str, outcome: str) -> None:
    """Bell notification (and Web Push via notification_type 'ops_alert' when MRK-24 delivery is on).
    Success resolves the open alert for that operation. Message is fixed Czech text + outcome code."""
    from models import Notification
    key = f"offsite:{operation}"
    open_alert = db.query(Notification).filter(Notification.dedupe_key == key, Notification.resolved == False).first()  # noqa: E712
    now = _utcnow()
    if outcome in {"success", "already_uploaded"}:
        if open_alert:
            open_alert.resolved = True
        return
    label = {"backup": "Záloha mimo počítač selhala", "check": "Kontrola zálohy mimo počítač selhala",
             "prune": "Údržba zálohy mimo počítač selhala"}[operation]
    message = f"Kategorie: {outcome}. Lokální záloha běží dál; podrobnosti v /health a docs/offsite-backups.md."
    if open_alert:
        open_alert.message, open_alert.last_triggered_at = message, now
        return
    db.add(Notification(area="system", title=label, message=message, severity="warning", read=False, created_at=now,
                        notification_type="ops_alert", source_type="offsite_backup", source_id=None, dedupe_key=key,
                        last_triggered_at=now, resolved=False, action_url=None))


def _log(operation: str, outcome: str) -> None:
    import logging
    state = "ok" if outcome in {"success", "already_uploaded"} else "warning"
    logging.getLogger("standa_hub.monitoring").info(
        "off_machine", extra={"monitoring": {"signal": "off_machine", "state": state}})
    print(f"[offsite] {operation}: {outcome}")   # allowlisted code only


# ---------- operations ----------

def backup_latest(db, config: OffsiteConfig, runner: Runner = _subprocess_runner, *,
                  deadline: Optional[float] = None) -> str:
    """Upload the newest verified local run once. Idempotent: a `run:<id>` snapshot tagged `complete` is reused.
    Every attempt that wrote a `running` record ends with an outcome - unexpected errors become `restic_failed`."""
    from models import OffsiteBackupRun
    log, run_path = latest_local_run(db, config.backup_dir)
    if not log:
        return "no_source"
    if db.query(OffsiteBackupRun).filter_by(operation="backup", status="success", source_backup_id=log.id).first():
        return "already_uploaded"
    if db.query(OffsiteBackupRun).filter_by(operation="backup", status="running").first():
        return "busy"
    run_id = run_path.stem.removeprefix("backup_") if run_path else None
    row = _record(db, "backup", source_backup_id=log.id, source_run=run_id)
    try:
        outcome, fields = _upload(config, runner, run_path, deadline)
    except Exception:
        db.rollback()
        outcome, fields = "restic_failed", {}
    return _finish(db, row, outcome, **fields)


def _upload(config: OffsiteConfig, runner: Runner, run_path: Optional[Path], deadline: Optional[float]):
    from offsite_backup import _SourceError, _load_source_run
    if not run_path:
        return "source_invalid", {}
    try:
        source = _load_source_run(config.backup_dir, run_path)
    except (_SourceError, OSError, ValueError):
        return "source_invalid", {}
    try:
        restic = Restic(config, runner, deadline=deadline)
    except OffsiteConfigError:
        return "misconfigured", {}
    unlock = restic.run("unlock")   # removes only stale locks (e.g. after an interrupted upload)
    if classify(unlock) != "success":
        return classify(unlock), {}
    outcome, snapshot = _existing_snapshot(restic, source.run_id)
    if outcome != "success":
        return outcome, {}
    if snapshot:   # completed before but not recorded (crash/timeout after restic finished)
        return "already_uploaded", {"snapshot_id": snapshot[:64]}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        handle.write("\n".join(f.archive_name for f in source.files) + "\n")
        listing = Path(handle.name)
    try:
        result = restic.run("backup", "--json", "--host", HOST, "--tag", TAG, "--tag", _run_tag(source.run_id),
                            "--files-from-verbatim", str(listing))
    finally:
        listing.unlink(missing_ok=True)
    outcome = classify(result)
    if outcome != "success":
        # Exit 3 leaves a partial snapshot carrying the run tag; without the `complete` tag it is never reused,
        # the next cycle uploads again (deduplicated) and retention removes the partial one with time.
        return outcome, {}
    summary = _summary(result.stdout)
    snapshot_id = str(summary.get("snapshot_id") or "")
    if not snapshot_id:
        return "restic_failed", {}
    marked = classify(restic.run("tag", "--add", COMPLETE_TAG, snapshot_id))
    if marked != "success":
        return marked, {}   # snapshot exists but unmarked: retried next cycle, never counted as uploaded
    # `restic tag` rewrites the snapshot (new id): record the id of the complete snapshot as it now exists.
    _, complete_id = _existing_snapshot(restic, source.run_id)
    return "success", {"snapshot_id": (complete_id or snapshot_id)[:64], "files_new": summary.get("files_new"),
                       "bytes_added": summary.get("data_added")}


def check(db, config: OffsiteConfig, runner: Runner = _subprocess_runner, *, read_data: bool = False,
          deadline: Optional[float] = None) -> str:
    row = _record(db, "check")
    try:
        restic = Restic(config, runner, deadline=deadline)
        args = ["check"] + (["--read-data-subset", DATA_SUBSET] if read_data else [])
        outcome = classify(restic.run(*args))
    except OffsiteConfigError:
        outcome = "misconfigured"
    except Exception:
        db.rollback()
        outcome = "restic_failed"
    return _finish(db, row, "check_failed" if outcome == "restic_failed" else outcome)


def prune(db, config: OffsiteConfig, runner: Runner = _subprocess_runner, *, deadline: Optional[float] = None) -> str:
    """forget + prune with the retention policy, maintenance credentials when configured. Callers run it only after
    a successful check; a failure leaves existing snapshots intact (restic forget/prune never touches kept data)."""
    row = _record(db, "prune")
    try:
        outcome = classify(Restic(config, runner, maintenance=True, deadline=deadline).run(*forget_args()))
    except OffsiteConfigError:
        outcome = "misconfigured"
    except Exception:
        db.rollback()
        outcome = "restic_failed"
    return _finish(db, row, outcome)


def _last(db, operation: str, status: Optional[str] = None):
    from models import OffsiteBackupRun
    q = db.query(OffsiteBackupRun).filter(OffsiteBackupRun.operation == operation)
    if status:
        q = q.filter(OffsiteBackupRun.status == status)
    return q.order_by(OffsiteBackupRun.started_at.desc(), OffsiteBackupRun.id.desc()).first()


def _expire_stale_running(db, config: OffsiteConfig) -> None:
    # A whole cycle is bounded by one deadline (timeout_seconds), so 2x that is safely "dead".
    from models import OffsiteBackupRun
    cutoff = _utcnow() - timedelta(seconds=config.timeout_seconds * 2)
    for row in db.query(OffsiteBackupRun).filter(OffsiteBackupRun.status == "running",
                                                 OffsiteBackupRun.started_at < cutoff).all():
        row.status, row.outcome, row.finished_at = "failed", "interrupted", _utcnow()
    db.commit()


def _due(row, interval: timedelta, now: datetime) -> bool:
    return row is None or now - row.started_at >= interval


def run_scheduled(db, runner: Runner = _subprocess_runner, env=os.environ) -> Optional[str]:
    """Hourly scheduler hook (after the local backup step). Never raises; returns the backup outcome or None.
    One deadline bounds the whole cycle. Failed uploads retry next cycle. Maintenance cadence follows the last
    ATTEMPT (not success), so a failing check/prune backs off to ~daily/weekly instead of repeating hourly."""
    try:
        config = load_config(env)
    except OffsiteConfigError:
        return "misconfigured"
    if config is None or not _lock.acquire(blocking=False):
        return None if config is None else "busy"
    try:
        deadline = time.monotonic() + config.timeout_seconds
        _expire_stale_running(db, config)
        outcome = backup_latest(db, config, runner, deadline=deadline)
        if outcome not in {"success", "already_uploaded"}:
            return outcome
        now = _utcnow()
        if not _due(_last(db, "check"), CHECK_INTERVAL, now):
            return outcome
        if _due(_last(db, "prune"), MAINTENANCE_INTERVAL, now):
            if check(db, config, runner, read_data=True, deadline=deadline) == "success":
                prune(db, config, runner, deadline=deadline)
        else:
            check(db, config, runner, deadline=deadline)
        return outcome
    except Exception:
        db.rollback()
        print("[offsite] scheduled run failed")
        return "restic_failed"
    finally:
        _lock.release()


# ---------- health ----------

def health_section(conn, now: datetime, env=os.environ) -> dict:
    """Non-sensitive /health block. No bucket, account, key, URL, path or raw output."""
    from sqlalchemy import select
    from models import OffsiteBackupRun as R
    section = {"configured": False, "status": "disabled", "degraded": False, "last_attempt_at": None,
               "last_attempt_outcome": None, "last_success_at": None, "source_backup_id": None, "age_seconds": None,
               "max_age_seconds": MAX_AGE_SECONDS, "last_check_at": None, "last_check_status": None,
               "last_prune_at": None, "last_prune_status": None, "retention": dict(KEEP), "encrypted": True}
    if not enabled(env):
        return section
    section["configured"] = True
    try:
        load_config(env)
    except OffsiteConfigError:
        section.update(status="misconfigured", degraded=True)
        return section

    def last(operation, status=None):
        q = select(R.status, R.outcome, R.started_at, R.finished_at, R.source_backup_id).where(R.operation == operation)
        if status:
            q = q.where(R.status == status)
        return conn.execute(q.order_by(R.started_at.desc(), R.id.desc()).limit(1)).first()

    def iso(value):
        return value.isoformat() + "Z" if value else None

    attempt, success = last("backup"), last("backup", "success")
    check_row, prune_row = last("check"), last("prune")
    if attempt:
        section.update(last_attempt_at=iso(attempt.started_at),
                       last_attempt_outcome=attempt.outcome if attempt.outcome in OUTCOMES else None)
    if success and success.finished_at:
        age = (now.replace(tzinfo=None) - success.finished_at).total_seconds()
        section.update(last_success_at=iso(success.finished_at), source_backup_id=success.source_backup_id,
                       age_seconds=round(age) if age >= 0 else None)
    if check_row:
        section.update(last_check_at=iso(check_row.started_at), last_check_status=check_row.status)
    if prune_row:
        section.update(last_prune_at=iso(prune_row.started_at), last_prune_status=prune_row.status)
    age = section["age_seconds"]
    fresh = age is not None and age <= MAX_AGE_SECONDS
    check_failed = bool(check_row and check_row.status == "failed")
    section["status"] = "fresh" if fresh and not check_failed else ("check_failed" if check_failed else "stale")
    section["degraded"] = not fresh or check_failed
    return section


# ---------- operator CLI (elevated, production env) ----------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Standa Hub off-machine backup (restic → B2). Prints codes only.")
    parser.add_argument("--env-file", type=Path, required=True, help="protected production env file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("init", help="create the restic repository once (refuses an existing one)")
    sub.add_parser("backup", help="upload the newest verified local run now")
    sub.add_parser("check").add_argument("--read-data", action="store_true")
    sub.add_parser("prune")
    sub.add_parser("snapshots", help="count and newest snapshot time only")
    restore = sub.add_parser("restore", help="restore a snapshot into an empty scratch directory and verify it")
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--snapshot", default="latest")
    args = parser.parse_args(argv)

    from production import load_production_environment
    load_production_environment(str(args.env_file.resolve()))
    os.chdir(Path(__file__).resolve().parent)
    config = load_config()
    if config is None:
        print("offsite: disabled (OFFSITE_BACKUP_ENABLED=false)")
        return 2
    from database import SessionLocal
    db = SessionLocal()
    try:
        if args.command == "status":
            from health_service import probe_engine
            with probe_engine().connect() as conn:
                print(json.dumps(health_section(conn, _utcnow()), indent=1))
            return 0
        if args.command == "backup":
            outcome = backup_latest(db, config)
        elif args.command == "check":
            outcome = check(db, config, read_data=args.read_data)
        elif args.command == "prune":
            outcome = check(db, config, read_data=True)
            outcome = prune(db, config) if outcome == "success" else outcome
        elif args.command == "init":
            outcome = classify(Restic(config).run("init"))
        elif args.command == "snapshots":
            result = Restic(config).run("snapshots", "--json", "--tag", TAG)
            outcome = classify(result)
            if outcome == "success":
                snaps = json.loads(result.stdout or "[]")
                print(f"snapshots: {len(snaps)} newest: {snaps[-1]['time'][:19] if snaps else '-'}")
        else:
            outcome = _restore(config, args.target, args.snapshot)
        print(f"offsite {args.command}: {outcome}")
        return 0 if outcome in {"success", "already_uploaded"} else 1
    except OffsiteConfigError as exc:
        print(f"offsite {args.command}: misconfigured ({exc})")
        return 1
    finally:
        db.close()


def _restore(config: OffsiteConfig, target: Path, snapshot: str) -> str:
    """Restore into an EMPTY scratch dir outside BACKUP_DIR/MEDIA_DIR, then re-verify the run's checksum contract."""
    from offsite_backup import _SourceError, _load_source_run
    target = target.resolve()
    for protected in (config.backup_dir, Path(env_str("MEDIA_DIR", "") or config.backup_dir)):
        protected = protected.resolve()
        if target == protected or protected in target.parents or target in protected.parents:
            raise OffsiteConfigError("restore target must be outside BACKUP_DIR and MEDIA_DIR")
    if target.exists() and any(target.iterdir()):
        raise OffsiteConfigError("restore target must be empty")
    target.mkdir(parents=True, exist_ok=True)
    # "latest" means the newest COMPLETE snapshot - a partial (exit 3) one is never restored by default.
    selector = ["--tag", f"{TAG},{COMPLETE_TAG}"] if snapshot == "latest" else []
    outcome = classify(Restic(config).run("restore", snapshot, *selector, "--target", str(target)))
    if outcome != "success":
        return outcome
    runs = sorted((target / "runs").glob("backup_*.json"))
    if len(runs) != 1:
        return "source_invalid"
    try:
        verified = _load_source_run(target, runs[0])
    except (_SourceError, OSError, ValueError):
        return "source_invalid"
    print(f"restored run {verified.run_id}: {len(verified.files)} files verified (sha256)")
    return "success"


if __name__ == "__main__":
    sys.exit(main())
