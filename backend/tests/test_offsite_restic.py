"""MRK-57: off-machine backups (verified local run → restic → B2). No real B2, no network: a fake restic runner,
plus one optional integration test against a temporary LOCAL restic repository when restic is installed."""
import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


import offsite_restic as off
from database import Base
from models import BackupLog, Notification, OffsiteBackupRun

FAKE_KEY_ID = "0041fake-key-id-canary"
FAKE_SECRET = "K004-secret-canary-value"
RUN_ID = "20261016_104655_574312"


# ---------- fixtures ----------

@pytest.fixture
def engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_local_run(root: Path, run_id: str = RUN_ID) -> Path:
    """A schema-v1 local backup run exactly as backup_service writes it (dump + manifest + media archive)."""
    dump = root / f"standa_hub_{run_id}.pgdump.gz"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_bytes(b"synthetic dump " + run_id.encode())
    media = root / "media" / "archive" / "study-materials" / "abc.pdf"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"%PDF synthetic")
    manifest = root / "media" / "manifests" / f"media_{run_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"schema_version": 1, "created_at": "2026-10-16T10:46:56Z", "file_count": 1,
                                    "total_bytes": media.stat().st_size, "files": [{
                                        "relative_path": "study-materials/abc.pdf", "size": media.stat().st_size,
                                        "sha256": sha(media.read_bytes()),
                                        "archive_path": "media/archive/study-materials/abc.pdf",
                                        "archived_at": "2026-10-16T10:46:56Z", "status": "copied"}]}), encoding="utf-8")
    run = root / "runs" / f"backup_{run_id}.json"
    run.parent.mkdir(parents=True, exist_ok=True)
    run.write_text(json.dumps({
        "schema_version": 1, "started_at": "2026-10-16T10:46:55Z", "finished_at": "2026-10-16T10:46:56Z",
        "status": "success", "retention_days": 30,
        "database": {"filename": dump.name, "size": dump.stat().st_size, "sha256": sha(dump.read_bytes())},
        "media": {"manifest": f"media/manifests/{manifest.name}", "manifest_sha256": sha(manifest.read_bytes()),
                  "file_count": 1, "copied": 1, "skipped": 0, "total_bytes": media.stat().st_size},
        "error": None}), encoding="utf-8")
    return dump


@pytest.fixture
def setup(tmp_path, db):
    backup_dir = tmp_path / "backups"
    dump = make_local_run(backup_dir)
    log = BackupLog(started_at=datetime.utcnow() - timedelta(minutes=5), finished_at=datetime.utcnow(),
                    status="success", filename=str(dump), retention_days=30)
    db.add(log)
    db.commit()
    secrets = tmp_path / "secrets" / "b2.env"
    secrets.parent.mkdir()
    secrets.write_text(f"RESTIC_REPOSITORY=s3:https://s3.eu-central-003.backblazeb2.com/bucket-canary/hub\n"
                       f"AWS_ACCESS_KEY_ID={FAKE_KEY_ID}\nAWS_SECRET_ACCESS_KEY={FAKE_SECRET}\n", encoding="utf-8")
    password = tmp_path / "secrets" / "restic-password.txt"
    password.write_text("repository-password-canary", encoding="utf-8")
    env = {"OFFSITE_BACKUP_ENABLED": "true", "OFFSITE_RESTIC_PATH": str(tmp_path / "restic.exe"),
           "OFFSITE_SECRETS_FILE": str(secrets), "OFFSITE_RESTIC_PASSWORD_FILE": str(password),
           "BACKUP_DIR": str(backup_dir)}
    return {"env": env, "config": off.load_config(env), "log": log, "backup_dir": backup_dir, "tmp": tmp_path}


class FakeRestic:
    """Scripted restic: per-subcommand results; records argv/env/cwd and the --files-from-verbatim content."""

    def __init__(self, **results):
        self.results = results
        self.calls = []
        self.listing = None

    def __call__(self, args, env, cwd, timeout):
        command = args[1]
        self.calls.append({"args": args, "env": env, "cwd": cwd})
        if command == "backup" and "--files-from-verbatim" in args:
            self.listing = Path(args[args.index("--files-from-verbatim") + 1]).read_text(encoding="utf-8").split()
        result = self.results.get(command, off.ResticResult(0, "", ""))
        return result(args) if callable(result) else result

    def commands(self):
        return [c["args"][1] for c in self.calls]


SUMMARY = json.dumps({"message_type": "summary", "files_new": 3, "data_added": 1234, "snapshot_id": "abc123" * 6})
NO_SNAPSHOTS = off.ResticResult(0, "[]", "")


def ok_restic(**overrides):
    results = {"snapshots": NO_SNAPSHOTS, "backup": off.ResticResult(0, "status line\n" + SUMMARY + "\n", "")}
    return FakeRestic(**{**results, **overrides})


# ---------- backup ----------

def test_successful_upload_of_the_verified_run_only(setup, db):
    fake = ok_restic()
    assert off.backup_latest(db, setup["config"], fake) == "success"
    row = db.query(OffsiteBackupRun).one()
    assert (row.status, row.outcome, row.source_backup_id, row.source_run) == ("success", "success", setup["log"].id, RUN_ID)
    assert row.snapshot_id.startswith("abc123") and (row.files_new, row.bytes_added) == (3, 1234)
    assert fake.commands() == ["unlock", "snapshots", "backup", "tag", "snapshots"]
    backup = fake.calls[2]
    assert fake.calls[3]["args"][1:] == ["tag", "--add", "complete", "abc123" * 6]   # only after a clean exit
    assert backup["cwd"] == setup["backup_dir"]
    assert sorted(fake.listing) == sorted([f"runs/backup_{RUN_ID}.json", f"standa_hub_{RUN_ID}.pgdump.gz",
                                           f"media/manifests/media_{RUN_ID}.json",
                                           "media/archive/study-materials/abc.pdf"])
    assert ["--host", "standa-hub"] == backup["args"][3:5] and f"run:{RUN_ID}" in backup["args"]
    # Secrets only in the child environment - never in argv; app secrets not inherited.
    argv = " ".join(" ".join(c["args"]) for c in fake.calls)
    assert FAKE_SECRET not in argv and "bucket-canary" not in argv and "password-canary" not in argv
    assert backup["env"]["AWS_SECRET_ACCESS_KEY"] == FAKE_SECRET
    assert backup["env"]["RESTIC_PASSWORD_FILE"].endswith("restic-password.txt")
    assert "DATABASE_URL" not in backup["env"] and "AUTH_PIN_HASH" not in backup["env"]


def test_duplicate_run_is_idempotent(setup, db):
    fake = ok_restic()
    off.backup_latest(db, setup["config"], fake)
    again = ok_restic()
    assert off.backup_latest(db, setup["config"], again) == "already_uploaded"
    assert again.calls == [] and db.query(OffsiteBackupRun).count() == 1


def test_snapshot_uploaded_before_a_crash_is_reused_not_duplicated(setup, db):
    existing = json.dumps([{"id": "feed" * 16, "tags": ["standa-hub", f"run:{RUN_ID}"]}])
    fake = FakeRestic(snapshots=off.ResticResult(0, existing, ""))
    assert off.backup_latest(db, setup["config"], fake) == "already_uploaded"
    assert "backup" not in fake.commands()
    row = db.query(OffsiteBackupRun).one()
    assert row.status == "success" and row.snapshot_id == "feed" * 16


def test_failed_upload_alerts_then_retry_succeeds_and_resolves(setup, db):
    down = ok_restic(backup=off.ResticResult(1, "", "Fatal: dial tcp: lookup s3.eu-central-003.backblazeb2.com: no such host"))
    assert off.backup_latest(db, setup["config"], down) == "network_unavailable"
    failed = db.query(OffsiteBackupRun).one()
    assert (failed.status, failed.outcome) == ("failed", "network_unavailable")
    alert = db.query(Notification).filter_by(dedupe_key="offsite:backup").one()
    assert not alert.resolved and alert.notification_type == "ops_alert" and "network_unavailable" in alert.message
    # Next hourly cycle: same source retried, not skipped as "already uploaded".
    assert off.backup_latest(db, setup["config"], ok_restic()) == "success"
    assert db.query(OffsiteBackupRun).filter_by(status="success").count() == 1
    assert db.query(Notification).filter_by(dedupe_key="offsite:backup").one().resolved


def test_errors_are_sanitized_categories(setup, db, capsys):
    stderr = (f"Fatal: unable to open repository at s3:https://s3.x/bucket-canary: Access Denied "
              f"(AccessDenied) key={FAKE_KEY_ID} secret={FAKE_SECRET}")
    fake = ok_restic(unlock=off.ResticResult(1, "", stderr))
    assert off.backup_latest(db, setup["config"], fake) == "auth_failed"
    stored = json.dumps([{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}
                         for r in db.query(OffsiteBackupRun).all() + db.query(Notification).all()])
    printed = capsys.readouterr().out
    for canary in (FAKE_KEY_ID, FAKE_SECRET, "bucket-canary", "AccessDenied"):
        assert canary not in stored and canary not in printed


@pytest.mark.parametrize("code,stderr,outcome", [
    (10, "", "repository_missing"), (11, "", "locked"), (12, "", "wrong_password"), (130, "", "interrupted"),
    (3, "", "source_incomplete"), (-1, "timeout", "timeout"), (1, "Fatal: unable to open config file: NoSuchBucket", "repository_missing"),
    (1, "SignatureDoesNotMatch", "auth_failed"), (1, "something unexpected", "restic_failed")])
def test_classification(code, stderr, outcome):
    assert off.classify(off.ResticResult(code, "", stderr)) == outcome


def test_source_integrity_failure_never_uploads(setup, db):
    media = setup["backup_dir"] / "media" / "archive" / "study-materials" / "abc.pdf"
    media.write_bytes(b"tampered after the local backup")
    fake = ok_restic()
    assert off.backup_latest(db, setup["config"], fake) == "source_invalid"
    assert fake.calls == []
    assert db.query(OffsiteBackupRun).one().outcome == "source_invalid"


def test_no_successful_local_backup_means_nothing_to_do(setup, db):
    setup["log"].status = "failed"
    db.commit()
    fake = ok_restic()
    assert off.backup_latest(db, setup["config"], fake) == "no_source" and fake.calls == []


# ---------- configuration ----------

def test_disabled_is_a_no_op(setup, db):
    fake = ok_restic()
    assert off.run_scheduled(db, fake, env={**setup["env"], "OFFSITE_BACKUP_ENABLED": "false"}) is None
    assert fake.calls == []


@pytest.mark.parametrize("change", [
    {"OFFSITE_RESTIC_PATH": "restic.exe"}, {"OFFSITE_SECRETS_FILE": ""}, {"BACKUP_DIR": "relative/backups"},
    {"OFFSITE_RESTIC_PASSWORD_FILE": "SAME"}, {"OFFSITE_TIMEOUT_SECONDS": "soon"}])
def test_invalid_config_is_rejected_without_values(setup, change):
    env = dict(setup["env"], **change)
    if change.get("OFFSITE_RESTIC_PASSWORD_FILE") == "SAME":
        env["OFFSITE_RESTIC_PASSWORD_FILE"] = env["OFFSITE_SECRETS_FILE"]
    with pytest.raises(off.OffsiteConfigError) as error:
        off.load_config(env)
    assert str(setup["tmp"]) not in str(error.value)


@pytest.mark.parametrize("content", [
    "RESTIC_REPOSITORY=s3:http://insecure.example/bucket\nAWS_ACCESS_KEY_ID=a\nAWS_SECRET_ACCESS_KEY=b\n",
    "RESTIC_REPOSITORY=b2:bucket:path\nAWS_ACCESS_KEY_ID=a\nAWS_SECRET_ACCESS_KEY=b\n",
    "RESTIC_REPOSITORY=s3:https://s3.example/bucket\nAWS_ACCESS_KEY_ID=a\n",
    "RESTIC_REPOSITORY=s3:https://s3.example/bucket\nAWS_ACCESS_KEY_ID=a\nAWS_SECRET_ACCESS_KEY=b\nDATABASE_URL=x\n",
    "C:\\local\\repo\n"])
def test_invalid_repository_or_secrets_file(setup, db, content):
    Path(setup["env"]["OFFSITE_SECRETS_FILE"]).write_text(content, encoding="utf-8")
    fake = ok_restic()
    assert off.backup_latest(db, setup["config"], fake) == "misconfigured"
    assert fake.calls == []


def test_missing_credentials_files(setup, db):
    Path(setup["env"]["OFFSITE_RESTIC_PASSWORD_FILE"]).unlink()
    assert off.backup_latest(db, setup["config"], ok_restic()) == "misconfigured"
    Path(setup["env"]["OFFSITE_SECRETS_FILE"]).unlink()
    assert off.run_scheduled(db, ok_restic(), env=setup["env"]) == "misconfigured"


# ---------- scheduling / concurrency ----------

def test_only_one_operation_at_a_time(setup, db):
    assert off._lock.acquire(blocking=False)
    try:
        fake = ok_restic()
        assert off.run_scheduled(db, fake, env=setup["env"]) == "busy" and fake.calls == []
    finally:
        off._lock.release()
    db.add(OffsiteBackupRun(operation="backup", status="running", started_at=datetime.utcnow()))
    db.commit()
    assert off.backup_latest(db, setup["config"], ok_restic()) == "busy"


def test_interrupted_running_row_expires_and_upload_retries(setup, db):
    db.add(OffsiteBackupRun(operation="backup", status="running", source_backup_id=setup["log"].id,
                            started_at=datetime.utcnow() - timedelta(hours=5)))
    db.commit()
    assert off.run_scheduled(db, ok_restic(), env=setup["env"]) == "success"
    assert {(r.status, r.outcome) for r in db.query(OffsiteBackupRun).filter_by(operation="backup")} == {
        ("failed", "interrupted"), ("success", "success")}


def test_first_success_runs_sampled_check_then_prune_and_later_only_metadata_checks(setup, db):
    fake = ok_restic()
    assert off.run_scheduled(db, fake, env=setup["env"]) == "success"
    assert fake.commands() == ["unlock", "snapshots", "backup", "tag", "snapshots", "check", "forget"]
    assert fake.calls[5]["args"][2:] == ["--read-data-subset", off.DATA_SUBSET]
    # Next hour: already uploaded, maintenance not due, metadata check not due either.
    nxt = ok_restic()
    assert off.run_scheduled(db, nxt, env=setup["env"]) == "already_uploaded" and nxt.calls == []
    # A day later the lightweight metadata check runs (no data download), no prune.
    for row in db.query(OffsiteBackupRun).filter_by(operation="check"):
        row.started_at -= timedelta(days=1)
    db.commit()
    later = ok_restic()
    off.run_scheduled(db, later, env=setup["env"])
    assert later.commands() == ["check"] and later.calls[0]["args"][2:] == []


def test_failed_check_blocks_prune_and_degrades(setup, db, engine):
    fake = ok_restic(check=off.ResticResult(1, "", "Fatal: repository contains errors"))
    off.run_scheduled(db, fake, env=setup["env"])
    assert "forget" not in fake.commands()
    # Cadence follows the last ATTEMPT: a failing check is not repeated every hour (no hourly 5 % data reads).
    again = ok_restic()
    assert off.run_scheduled(db, again, env=setup["env"]) == "already_uploaded" and again.calls == []
    assert db.query(OffsiteBackupRun).filter_by(operation="check").one().outcome == "check_failed"
    with engine.connect() as conn:
        section = off.health_section(conn, datetime.now(timezone.utc), env=setup["env"])
    assert section["last_check_status"] == "failed" and section["degraded"] and section["status"] == "check_failed"


def test_retention_policy_and_maintenance_credentials(setup, db):
    assert off.forget_args() == ["forget", "--tag", "standa-hub", "--group-by", "host", "--keep-daily", "14",
                                 "--keep-weekly", "8", "--keep-monthly", "12", "--prune"]
    maintenance = setup["tmp"] / "secrets" / "b2-maintenance.env"
    maintenance.write_text("RESTIC_REPOSITORY=s3:https://s3.example/bucket/hub\nAWS_ACCESS_KEY_ID=maint\n"
                           "AWS_SECRET_ACCESS_KEY=maint-secret\n", encoding="utf-8")
    config = off.load_config({**setup["env"], "OFFSITE_MAINTENANCE_SECRETS_FILE": str(maintenance)})
    fake = ok_restic()
    off.backup_latest(db, config, fake)
    off.prune(db, config, fake)
    upload_env, prune_env = fake.calls[2]["env"], fake.calls[-1]["env"]
    assert upload_env["AWS_ACCESS_KEY_ID"] == FAKE_KEY_ID and prune_env["AWS_ACCESS_KEY_ID"] == "maint"


def test_failed_prune_keeps_backup_status(setup, db, engine):
    off.backup_latest(db, setup["config"], ok_restic())
    assert off.prune(db, setup["config"], ok_restic(forget=off.ResticResult(1, "", "unexpected"))) == "restic_failed"
    with engine.connect() as conn:
        section = off.health_section(conn, datetime.now(timezone.utc), env=setup["env"])
    assert section["last_prune_status"] == "failed" and not section["degraded"] and section["status"] == "fresh"


def test_scheduler_exception_never_escapes(setup, db):
    def boom(*_args):
        raise RuntimeError("secret-canary")
    assert off.run_scheduled(db, boom, env=setup["env"]) == "restic_failed"


def test_local_backup_success_does_not_depend_on_offsite(setup, db, engine, monkeypatch):
    import backup_service
    import domain_events
    import scheduler_service
    calls = []

    def local_backup(session):
        calls.append("local")
        log = BackupLog(started_at=datetime.utcnow(), finished_at=datetime.utcnow(), status="success", retention_days=30)
        session.add(log)
        session.commit()
        return log.id

    def offsite_down(session):
        calls.append("offsite")
        raise RuntimeError("B2 unreachable")

    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler_service, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduler_service, "create_all_overdue_and_upcoming_notifications", lambda *a, **k: None)
    monkeypatch.setattr(domain_events, "cleanup_domain_events", lambda session: 0)
    monkeypatch.setattr(backup_service, "should_run_backup_daily", lambda: True)
    monkeypatch.setattr(backup_service, "run_backup", local_backup)
    monkeypatch.setattr(off, "run_scheduled", offsite_down)
    with patch("scheduler_service.tracker.failed") as failed:
        scheduler_service._run_hourly_job()
    assert calls == ["local", "offsite"]
    assert db.query(BackupLog).order_by(BackupLog.id.desc()).first().status == "success"
    assert not any(c.args and c.args[0] == "standa_hub_hourly" for c in failed.call_args_list)


# ---------- health ----------

def _health(engine, env, now=None):
    with engine.connect() as conn:
        return off.health_section(conn, now or datetime.now(timezone.utc), env=env)


def test_health_disabled_is_not_degraded(engine):
    section = _health(engine, {"OFFSITE_BACKUP_ENABLED": "false"})
    assert section["configured"] is False and section["degraded"] is False and section["status"] == "disabled"


def test_health_states_and_no_sensitive_fields(setup, db, engine):
    section = _health(engine, setup["env"])
    assert section["configured"] and section["degraded"] and section["status"] == "stale"  # configured, nothing yet
    off.backup_latest(db, setup["config"], ok_restic())
    section = _health(engine, setup["env"])
    assert not section["degraded"] and section["status"] == "fresh" and section["source_backup_id"] == setup["log"].id
    assert 0 <= section["age_seconds"] < 60
    late = _health(engine, setup["env"], datetime.now(timezone.utc) + timedelta(hours=27))
    assert late["degraded"] and late["status"] == "stale"
    text = json.dumps(section)
    for canary in (FAKE_KEY_ID, FAKE_SECRET, "bucket-canary", "backblazeb2", "password", str(setup["tmp"])):
        assert canary not in text


def test_health_misconfigured_is_degraded(engine, setup):
    section = _health(engine, {**setup["env"], "OFFSITE_RESTIC_PATH": "relative"})
    assert section["status"] == "misconfigured" and section["degraded"]


def test_collect_health_degrades_overall_status_when_offsite_is_stale(setup, engine):
    from health_service import collect_health
    scheduler = {"status": "running", "backup_job_enabled": True, "jobs": []}
    # The in-memory schema has no alembic_version: report "no heads" so only the off-site policy decides.
    with patch("health_service.code_revisions", return_value=([], set())):
        with patch.dict(os.environ, setup["env"]):
            result = collect_health(engine, scheduler, offsite=True)
        assert result["offsite"]["degraded"] and result["status"] == "degraded"
        with patch.dict(os.environ, {"OFFSITE_BACKUP_ENABLED": "false"}):
            assert collect_health(engine, scheduler, offsite=True)["status"] == "healthy"


# ---------- production validation ----------

def test_production_validation(setup, tmp_path):
    import bcrypt
    from production import validate_environment
    base = dict(APP_ENV="production", DATABASE_URL="postgresql+psycopg2://user:placeholder@localhost/standa_test",
                PRODUCTION_DATABASE_NAME="standa_test", AUTH_PIN_HASH=bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4)).decode(),
                FRONTEND_ORIGINS="http://localhost:3000", MEDIA_DIR=str(tmp_path / "m"), BACKUP_DIR=setup["env"]["BACKUP_DIR"],
                GROQ_API_KEY="dummy", SCHEDULER_ENABLED="true", REMINDERS_CHECK_ENABLED="true",
                DAILY_BRIEFING_ENABLED="false", WEEKLY_REVIEW_ENABLED="false", EXTERNAL_DELIVERY_ENABLED="false",
                BACKUP_ENABLED="true", RUN_ALEMBIC_UPGRADE_AT_STARTUP="false")
    validate_environment(base)                                   # off-site off: unchanged behaviour
    validate_environment({**base, **setup["env"]})               # off-site on, valid
    for bad in ({"BACKUP_ENABLED": "false"}, {"OFFSITE_ALLOW_LOCAL_REPOSITORY": "true"}, {"OFFSITE_RESTIC_PATH": "x"}):
        with pytest.raises(ValueError):
            validate_environment({**base, **setup["env"], **bad})


# ---------- optional real restic integration (local repository, no network) ----------

RESTIC = shutil.which("restic") or next(iter(Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                                              .glob("WinGet/Packages/restic.restic_*/restic_*.exe")), None)


@pytest.mark.skipif(not RESTIC, reason="restic binary not installed")
def test_real_restic_backup_idempotency_and_verified_restore(setup, db, tmp_path):
    repo = tmp_path / "repo"
    Path(setup["env"]["OFFSITE_SECRETS_FILE"]).write_text(f"RESTIC_REPOSITORY={repo}\n", encoding="utf-8")
    env = {**setup["env"], "OFFSITE_RESTIC_PATH": str(RESTIC), "OFFSITE_ALLOW_LOCAL_REPOSITORY": "true"}
    config = off.load_config(env)
    assert off.classify(off.Restic(config).run("init")) == "success"
    assert off.backup_latest(db, config) == "success"
    assert off.backup_latest(db, config) == "already_uploaded"
    db.query(OffsiteBackupRun).delete()   # lose the record → the tagged snapshot is found, not re-uploaded
    db.commit()
    assert off.backup_latest(db, config) == "already_uploaded"
    snaps = json.loads(off.Restic(config).run("snapshots", "--json", "--tag", off.TAG).stdout)
    assert len(snaps) == 1 and "complete" in snaps[0]["tags"] and f"run:{RUN_ID}" in snaps[0]["tags"]
    assert db.query(OffsiteBackupRun).filter_by(status="success").first().snapshot_id == snaps[0]["id"]
    assert off.check(db, config, read_data=True) == "success"
    assert off.prune(db, config) == "success"
    with patch.dict(os.environ, {"MEDIA_DIR": str(tmp_path / "media-live")}):
        assert off._restore(config, tmp_path / "restore", "latest") == "success"
    restored = tmp_path / "restore" / "media" / "archive" / "study-materials" / "abc.pdf"
    assert restored.read_bytes() == b"%PDF synthetic"
    with pytest.raises(off.OffsiteConfigError):
        off._restore(config, setup["backup_dir"] / "inside", "latest")   # never into BACKUP_DIR


# ---------- review regressions (MRK-57 review H1/M3/M4) ----------

def test_partial_snapshot_is_never_counted_as_uploaded(setup, db):
    # restic exit 3 = snapshot created but some files unreadable (e.g. a locked file). It carries the run tag.
    partial = ok_restic(backup=off.ResticResult(3, SUMMARY + "\n", "error: open media: Access is denied"))
    assert off.backup_latest(db, setup["config"], partial) == "source_incomplete"
    assert "tag" not in partial.commands(), "partial snapshot is not marked complete"
    # Next cycle: the lookup filters on the `complete` tag, so it uploads again instead of reusing the partial one.
    retry = ok_restic()
    assert off.backup_latest(db, setup["config"], retry) == "success"
    lookup = next(c for c in retry.calls if c["args"][1] == "snapshots")["args"]
    assert lookup[-1] == f"standa-hub,run:{RUN_ID},complete" and "backup" in retry.commands()


def test_snapshot_without_complete_mark_is_retried(setup, db):
    fake = ok_restic(tag=off.ResticResult(1, "", "connection reset by peer"))
    assert off.backup_latest(db, setup["config"], fake) == "network_unavailable"
    assert db.query(OffsiteBackupRun).one().status == "failed"


def test_utf16_secrets_file_is_misconfigured_not_a_silent_running_row(setup, db):
    Path(setup["env"]["OFFSITE_SECRETS_FILE"]).write_text("RESTIC_REPOSITORY=s3:https://x/y\n", encoding="utf-16")
    assert off.backup_latest(db, setup["config"], ok_restic()) == "misconfigured"
    assert db.query(OffsiteBackupRun).filter_by(status="running").count() == 0


def test_unexpected_error_still_finishes_the_attempt(setup, db):
    def explode(args, env, cwd, timeout):
        raise RuntimeError("unexpected")
    assert off.backup_latest(db, setup["config"], explode) == "restic_failed"
    row = db.query(OffsiteBackupRun).one()
    assert (row.status, row.outcome) == ("failed", "restic_failed") and row.finished_at is not None
    assert db.query(Notification).filter_by(dedupe_key="offsite:backup", resolved=False).count() == 1


def test_one_deadline_bounds_the_whole_cycle(setup, db):
    import time
    fake = ok_restic()
    assert off.backup_latest(db, setup["config"], fake, deadline=time.monotonic() - 1) == "timeout"
    assert fake.calls == [], "no restic call once the cycle deadline has passed"
    seen = []
    off.backup_latest(db, setup["config"], lambda a, e, c, t: seen.append(t) or off.ResticResult(0, "[]", ""),
                      deadline=time.monotonic() + 120)
    assert seen and max(seen) <= 120, "each call gets only the remaining cycle time"
