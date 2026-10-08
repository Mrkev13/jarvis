import hashlib
import io
import json
import shutil
import sys
import tarfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from offsite_backup import (
    AgeEncryptor,
    LocalFilesystemOffsiteTarget,
    OffsiteOutcome,
    OffsiteRunMetadata,
    cleanup_retention,
    copy_completed_run,
    plan_retention,
    safe_extract_tar,
    verify_offsite_run,
)
import offsite_backup


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_backup(
    root: Path,
    *,
    run_id: str = "20261008_120000_000001",
    started_at: str = "2026-10-08T12:00:00Z",
    db: bytes = b"postgres dump\n",
    media: bytes = b"replay bytes",
) -> Path:
    db_name = f"standa_hub_{run_id}.pgdump.gz"
    media_path = "media/archive/wot-replays/replay.wotreplay"
    manifest_path = f"media/manifests/media_{run_id}.json"
    run_path = root / "runs" / f"backup_{run_id}.json"

    (root / db_name).parent.mkdir(parents=True, exist_ok=True)
    (root / db_name).write_bytes(db)
    (root / media_path).parent.mkdir(parents=True, exist_ok=True)
    (root / media_path).write_bytes(media)
    manifest = {
        "schema_version": 1,
        "created_at": started_at,
        "file_count": 1,
        "total_bytes": len(media),
        "files": [{
            "relative_path": "wot-replays/replay.wotreplay",
            "size": len(media),
            "sha256": _sha(media),
            "archive_path": media_path,
            "archived_at": started_at,
            "status": "copied",
        }],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (root / manifest_path).parent.mkdir(parents=True, exist_ok=True)
    (root / manifest_path).write_bytes(manifest_bytes)
    run = {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": started_at,
        "status": "success",
        "retention_days": 30,
        "database": {"filename": db_name, "size": len(db), "sha256": _sha(db)},
        "media": {
            "manifest": manifest_path,
            "manifest_sha256": _sha(manifest_bytes),
            "file_count": 1,
            "copied": 1,
            "skipped": 0,
            "total_bytes": len(media),
        },
        "error": None,
    }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(run, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return run_path


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): _sha(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class FakeEncryptor:
    def __init__(self, secret: str = "super-secret-canary"):
        self.secret = secret

    def can_encrypt(self) -> bool:
        return True

    def can_decrypt(self) -> bool:
        return True

    def encrypt(self, source: Path, destination: Path) -> None:
        destination.write_bytes(b"FAKE" + source.read_bytes()[::-1])

    def decrypt(self, source: Path, destination: Path) -> None:
        data = source.read_bytes()
        if not data.startswith(b"FAKE"):
            raise RuntimeError(self.secret)
        destination.write_bytes(data[4:][::-1])


class UnavailableEncryptor(FakeEncryptor):
    def can_encrypt(self) -> bool:
        return False

    def can_decrypt(self) -> bool:
        return False


class EncryptOnlyEncryptor(FakeEncryptor):
    def can_decrypt(self) -> bool:
        return False


class BrokenRoundTripEncryptor(FakeEncryptor):
    def decrypt(self, source: Path, destination: Path) -> None:
        destination.write_bytes(b"not a tar archive")


def _metadata(run_id: str, when: datetime, **changes) -> OffsiteRunMetadata:
    base = OffsiteRunMetadata(
        run_id=run_id,
        run_time=when,
        source_backup_identifier=f"backup_{run_id}.json",
        encrypted=False,
        transfer_completed=True,
        checksum_result="verified",
        offsite_target_identifier="test-target",
    )
    return replace(base, **changes)


def _replace_payload(target_root: Path, run_id: str, mutate) -> None:
    payload = target_root / run_id / "payload.tar"
    work = target_root / "rewrite"
    with tarfile.open(payload, "r") as archive:
        archive.extractall(work, filter="data")
    mutate(work)
    replacement = target_root / "replacement.tar"
    with tarfile.open(replacement, "w") as archive:
        for item in sorted(work.rglob("*"), key=lambda p: p.as_posix()):
            archive.add(item, arcname=item.relative_to(work).as_posix(), recursive=False)
    replacement.replace(payload)
    shutil.rmtree(work)


def test_filesystem_copy_is_verified_and_source_remains_untouched(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    before = _tree_digest(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite", identifier="usb-a")

    result = copy_completed_run(source, run_path, target)

    assert result.success is True
    assert result.code is OffsiteOutcome.SUCCESS
    assert _tree_digest(source) == before
    runs = target.list_runs()
    assert len(runs) == 1
    assert runs[0].offsite_target_identifier == "usb-a"
    assert set(json.loads((tmp_path / "offsite" / runs[0].run_id / "metadata.json").read_text())) == {
        "run_id", "run_time", "source_backup_identifier", "encrypted",
        "transfer_completed", "checksum_result", "offsite_target_identifier",
    }
    verification = verify_offsite_run(target, runs[0].run_id)
    assert verification.success is True
    assert _tree_digest(source) == before


def test_required_encryption_unavailable_fails_closed(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")

    result = copy_completed_run(
        source, run_path, target,
        encryption_required=True,
        encryptor=UnavailableEncryptor(),
    )

    assert result.success is False
    assert result.code is OffsiteOutcome.ENCRYPTION_FAILURE
    assert target.list_runs() == []


@pytest.mark.parametrize("encryptor", [EncryptOnlyEncryptor(), BrokenRoundTripEncryptor()])
def test_required_encryption_requires_verified_decryption_before_publish(tmp_path: Path, encryptor):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")

    result = copy_completed_run(
        source, run_path, target,
        encryption_required=True,
        encryptor=encryptor,
    )

    assert result.code is OffsiteOutcome.ENCRYPTION_FAILURE
    assert target.list_runs() == []


def test_encrypted_round_trip_and_no_secret_leakage(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    encryptor = FakeEncryptor()

    result = copy_completed_run(
        source, run_path, target,
        encryption_required=True,
        encryptor=encryptor,
    )
    verification = verify_offsite_run(target, result.run_id, encryptor=encryptor)
    serialized = json.dumps({
        "result": result.to_dict(),
        "verification": verification.to_dict(),
        "metadata": json.loads((tmp_path / "offsite" / result.run_id / "metadata.json").read_text()),
    })

    assert result.success and verification.success
    assert encryptor.secret not in serialized
    assert (tmp_path / "offsite" / result.run_id / "payload.age").is_file()


@pytest.mark.parametrize("member_name", ["../escape", "/absolute/path", "C:/absolute/path"])
def test_safe_extract_rejects_traversal_and_absolute_paths(tmp_path: Path, member_name: str):
    archive_path = tmp_path / "bad.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(ValueError, match="unsafe archive"):
        safe_extract_tar(archive_path, tmp_path / "scratch")

    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_safe_extract_rejects_symbolic_and_hard_links(tmp_path: Path, member_type: bytes):
    archive_path = tmp_path / "link.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("safe/link")
        info.type = member_type
        info.linkname = "../../escape"
        archive.addfile(info)

    with pytest.raises(ValueError, match="unsafe archive"):
        safe_extract_tar(archive_path, tmp_path / "scratch")


def test_source_path_escape_and_checksum_corruption_are_local_failures(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    run = json.loads(run_path.read_text())
    run["database"]["filename"] = "../outside.gz"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    assert copy_completed_run(source, run_path, target).code is OffsiteOutcome.LOCAL_BACKUP_FAILURE

    run_path = _write_backup(source)
    (source / run["database"]["filename"]).unlink(missing_ok=True)
    (source / "standa_hub_20261008_120000_000001.pgdump.gz").write_bytes(b"corrupt")
    assert copy_completed_run(source, run_path, target).code is OffsiteOutcome.LOCAL_BACKUP_FAILURE


def test_transfer_failure_is_structured_and_not_published(tmp_path: Path):
    class FailingTarget(LocalFilesystemOffsiteTarget):
        def store_run(self, *args, **kwargs):
            raise OSError("private path and credentials must not escape")

    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = FailingTarget(tmp_path / "offsite")
    result = copy_completed_run(source, run_path, target)

    assert result.code is OffsiteOutcome.OFFSITE_TRANSFER_FAILURE
    assert "private path" not in json.dumps(result.to_dict())
    assert target.list_runs() == []


def test_existing_run_is_never_overwritten(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    first = copy_completed_run(source, run_path, target)
    original = _tree_digest(tmp_path / "offsite" / first.run_id)

    second = copy_completed_run(source, run_path, target)

    assert second.code is OffsiteOutcome.OFFSITE_TRANSFER_FAILURE
    assert _tree_digest(tmp_path / "offsite" / first.run_id) == original


def test_filesystem_provider_verifies_transferred_payload(tmp_path: Path, monkeypatch):
    payload = tmp_path / "payload.tar"
    payload.write_bytes(b"expected payload")
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    metadata = _metadata("run-1", datetime(2026, 10, 8, 12, tzinfo=timezone.utc))
    original_copy = offsite_backup.shutil.copyfileobj

    def corrupt_copy(source, destination, length=0):
        original_copy(source, destination, length=length)
        destination.seek(0)
        destination.write(b"corrupt")
        destination.truncate()

    monkeypatch.setattr(offsite_backup.shutil, "copyfileobj", corrupt_copy)
    with pytest.raises(RuntimeError):
        target.store_run(payload, metadata)
    assert target.list_runs() == []


def test_provider_rejects_symlinked_payload_child(tmp_path: Path):
    source = tmp_path / "source"
    run_path = _write_backup(source)
    target_root = tmp_path / "offsite"
    target = LocalFilesystemOffsiteTarget(target_root)
    result = copy_completed_run(source, run_path, target)
    payload = target_root / result.run_id / "payload.tar"
    outside = tmp_path / "outside.tar"
    outside.write_bytes(payload.read_bytes())
    payload.unlink()
    try:
        payload.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    assert target.list_runs() == []
    with pytest.raises(Exception):
        target.retrieve_run(result.run_id, tmp_path / "retrieved")


def test_verification_detects_corruption_and_missing_db_or_media(tmp_path: Path):
    def setup(name: str):
        source = tmp_path / name / "source"
        run_path = _write_backup(source)
        target_root = tmp_path / name / "offsite"
        target = LocalFilesystemOffsiteTarget(target_root)
        result = copy_completed_run(source, run_path, target)
        assert result.success
        return target, target_root, result.run_id

    target, root, run_id = setup("corrupt")
    _replace_payload(root, run_id, lambda work: (work / f"standa_hub_{run_id}.pgdump.gz").write_bytes(b"changed"))
    assert verify_offsite_run(target, run_id).code is OffsiteOutcome.VERIFICATION_FAILURE

    target, root, run_id = setup("missing-db")
    _replace_payload(root, run_id, lambda work: (work / f"standa_hub_{run_id}.pgdump.gz").unlink())
    assert verify_offsite_run(target, run_id).code is OffsiteOutcome.VERIFICATION_FAILURE

    target, root, run_id = setup("missing-media")
    _replace_payload(root, run_id, lambda work: (work / "media/archive/wot-replays/replay.wotreplay").unlink())
    assert verify_offsite_run(target, run_id).code is OffsiteOutcome.VERIFICATION_FAILURE


def test_retention_keeps_newest_in_each_bucket_and_deduplicates():
    runs = [
        _metadata("newest", datetime(2026, 1, 1, 12, tzinfo=timezone.utc)),
        _metadata("same-bucket-older", datetime(2026, 1, 1, 8, tzinfo=timezone.utc)),
        _metadata("previous", datetime(2025, 12, 31, 12, tzinfo=timezone.utc)),
    ]

    plan = plan_retention(runs, daily=1, weekly=1, monthly=1, timezone_name="Europe/Prague")

    assert plan.keep == ("newest",)
    assert plan.delete == ("same-bucket-older", "previous")
    assert len(plan.keep) == len(set(plan.keep))


def test_retention_timezone_iso_week_month_boundaries_and_newest_preservation():
    runs = [
        _metadata("july-local", datetime(2026, 6, 30, 22, 30, tzinfo=timezone.utc)),
        _metadata("june-local", datetime(2026, 6, 30, 21, 30, tzinfo=timezone.utc)),
        _metadata("iso-2026", datetime(2025, 12, 29, 10, tzinfo=timezone.utc)),
        _metadata("iso-2025", datetime(2025, 12, 28, 10, tzinfo=timezone.utc)),
    ]

    daily = plan_retention(runs[:2], daily=2, weekly=0, monthly=0)
    weekly = plan_retention(runs[2:], daily=0, weekly=2, monthly=0)
    monthly = plan_retention(runs[:2], daily=0, weekly=0, monthly=2)
    newest_only = plan_retention(runs, daily=0, weekly=0, monthly=0)

    assert set(daily.keep) == {"july-local", "june-local"}
    assert set(weekly.keep) == {"iso-2026", "iso-2025"}
    assert set(monthly.keep) == {"july-local", "june-local"}
    assert newest_only.keep == ("july-local",)


def test_retention_defaults_cover_14_daily_8_weekly_12_monthly_buckets():
    daily_runs = [
        _metadata(f"daily-{day}", datetime(2026, 10, day, 12, tzinfo=timezone.utc))
        for day in range(1, 16)
    ]
    weekly_runs = [
        _metadata(f"weekly-{week}", datetime.fromisocalendar(2026, week, 1).replace(tzinfo=timezone.utc))
        for week in range(1, 10)
    ]
    monthly_runs = [
        _metadata(f"monthly-{index}", datetime(2025 + index // 12, index % 12 + 1, 1, tzinfo=timezone.utc))
        for index in range(13)
    ]

    daily = plan_retention(daily_runs, weekly=0, monthly=0)
    weekly = plan_retention(weekly_runs, daily=0, monthly=0)
    monthly = plan_retention(monthly_runs, daily=0, weekly=0)

    assert len(daily.keep) == 14
    assert len(weekly.keep) == 8
    assert len(monthly.keep) == 12
    assert "daily-15" in daily.keep
    assert "weekly-9" in weekly.keep
    assert "monthly-12" in monthly.keep


def test_retention_cleanup_deletes_only_expired_completed_run(tmp_path: Path):
    source = tmp_path / "source"
    old_path = _write_backup(source, run_id="20261007_120000_000001", started_at="2026-10-07T12:00:00Z")
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    assert copy_completed_run(source, old_path, target).success
    new_path = _write_backup(source, run_id="20261008_120000_000001", started_at="2026-10-08T12:00:00Z")
    assert copy_completed_run(source, new_path, target).success
    plan = plan_retention(target.list_runs(), daily=0, weekly=0, monthly=0)

    dry_run = cleanup_retention(target, plan, dry_run=True)
    assert dry_run.would_delete == ("20261007_120000_000001",)
    assert len(target.list_runs()) == 2

    cleanup = cleanup_retention(target, plan, dry_run=False)
    assert cleanup.success
    assert cleanup.deleted == ("20261007_120000_000001",)
    assert [run.run_id for run in target.list_runs()] == ["20261008_120000_000001"]


def test_invalid_runs_are_preserved_and_cleanup_failure_is_structured(tmp_path: Path):
    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    valid = _metadata("valid", now)
    invalid = _metadata("invalid", now.replace(year=2020), transfer_completed=False)
    plan = plan_retention([valid, invalid], daily=0, weekly=0, monthly=0)
    assert plan.keep == ("valid",)
    assert plan.invalid == ("invalid",)
    assert "invalid" not in plan.delete

    class CleanupFailureTarget:
        def delete_run(self, run_id: str) -> None:
            raise OSError("secret cleanup path")

    forced = replace(plan, delete=("expired",))
    dry = cleanup_retention(CleanupFailureTarget(), forced, dry_run=True)
    failed = cleanup_retention(CleanupFailureTarget(), forced, dry_run=False)
    assert dry.success and dry.deleted == () and dry.would_delete == ("expired",)
    assert failed.code is OffsiteOutcome.RETENTION_CLEANUP_FAILURE
    assert "secret cleanup path" not in json.dumps(failed.to_dict())
    assert failed.operation == "retention_cleanup"
    assert failed.started_at.tzinfo is not None
    assert failed.finished_at >= failed.started_at


def test_conflicting_valid_and_invalid_retention_id_is_never_deleted():
    now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    newest = _metadata("newest", now)
    valid = _metadata("conflict", now.replace(year=2025))
    invalid = replace(valid, transfer_completed=False)

    plan = plan_retention([newest, valid, invalid], daily=0, weekly=0, monthly=0)

    assert plan.keep == ("newest",)
    assert plan.delete == ()
    assert plan.invalid == ("conflict",)


@pytest.mark.parametrize("identifier", ["CON", "aux.txt", "trailing."])
def test_provider_rejects_nonportable_windows_identifiers(tmp_path: Path, identifier: str):
    target = LocalFilesystemOffsiteTarget(tmp_path / "offsite")
    with pytest.raises(ValueError):
        target.retrieve_run(identifier, tmp_path / "retrieved")


def test_age_adapter_reports_missing_executable_without_exposing_identity(tmp_path: Path):
    identity = tmp_path / "secret-identity.txt"
    adapter = AgeEncryptor(recipient="age1publicrecipient", identity_file=identity, executable="definitely-missing-age")
    assert adapter.can_encrypt() is False
    assert adapter.can_decrypt() is False
    assert str(identity) not in repr(adapter)


def test_age_adapter_uses_recipient_and_identity_without_key_contents(tmp_path: Path, monkeypatch):
    executable = tmp_path / "age.exe"
    executable.write_bytes(b"")
    identity = tmp_path / "identity.txt"
    identity.write_text("AGE-SECRET-KEY-secret-canary", encoding="utf-8")
    source = tmp_path / "source.tar"
    source.write_bytes(b"payload")
    encrypted = tmp_path / "payload.age"
    decrypted = tmp_path / "decrypted.tar"
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(Path(command[-1]).read_bytes())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(offsite_backup.subprocess, "run", fake_run)
    adapter = AgeEncryptor(
        recipient="age1publicrecipient",
        identity_file=identity,
        executable=str(executable),
    )
    adapter.encrypt(source, encrypted)
    adapter.decrypt(encrypted, decrypted)

    assert decrypted.read_bytes() == b"payload"
    assert "age1publicrecipient" in commands[0]
    assert str(identity) in commands[1]
    assert all("AGE-SECRET-KEY-secret-canary" not in part for command in commands for part in command)
