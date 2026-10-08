"""Provider-neutral offsite backup packaging, retention, and scratch verification.

This module does not schedule work, touch the application database, or publish
monitoring/health state. Callers supply an already completed local backup run.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Protocol
from zoneinfo import ZoneInfo


DEFAULT_DAILY_RETENTION = 14
DEFAULT_WEEKLY_RETENTION = 8
DEFAULT_MONTHLY_RETENTION = 12
DEFAULT_RETENTION_TIMEZONE = "Europe/Prague"

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CHECKSUM = re.compile(r"[a-f0-9]{64}\Z")


class OffsiteOutcome(str, Enum):
    SUCCESS = "success"
    LOCAL_BACKUP_FAILURE = "local_backup_failure"
    ENCRYPTION_FAILURE = "encryption_failure"
    OFFSITE_TRANSFER_FAILURE = "offsite_transfer_failure"
    VERIFICATION_FAILURE = "verification_failure"
    RETENTION_CLEANUP_FAILURE = "retention_cleanup_failure"


class _SourceError(RuntimeError):
    pass


class _EncryptionError(RuntimeError):
    pass


class _TransferError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _valid_identifier(value: str) -> bool:
    return bool(_SAFE_IDENTIFIER.fullmatch(value)) and value not in {".", ".."}


def _require_identifier(value: str) -> str:
    if not isinstance(value, str) or not _valid_identifier(value):
        raise ValueError("invalid identifier")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_checksum(value: object) -> bool:
    return isinstance(value, str) and bool(_CHECKSUM.fullmatch(value))


@dataclass(frozen=True)
class OperationResult:
    operation: str
    success: bool
    code: OffsiteOutcome
    run_id: str | None
    started_at: datetime
    finished_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "success": self.success,
            "code": self.code.value,
            "run_id": self.run_id,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }


@dataclass(frozen=True)
class OffsiteRunMetadata:
    run_id: str
    run_time: datetime
    source_backup_identifier: str
    encrypted: bool
    transfer_completed: bool
    checksum_result: str
    offsite_target_identifier: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_time": _iso(self.run_time),
            "source_backup_identifier": self.source_backup_identifier,
            "encrypted": self.encrypted,
            "transfer_completed": self.transfer_completed,
            "checksum_result": self.checksum_result,
            "offsite_target_identifier": self.offsite_target_identifier,
        }

    @classmethod
    def from_dict(cls, data: object) -> "OffsiteRunMetadata":
        if not isinstance(data, dict) or set(data) != {
            "run_id", "run_time", "source_backup_identifier", "encrypted",
            "transfer_completed", "checksum_result", "offsite_target_identifier",
        }:
            raise ValueError("invalid offsite metadata")
        run_id = _require_identifier(data["run_id"])
        source_id = _require_identifier(data["source_backup_identifier"])
        target_id = _require_identifier(data["offsite_target_identifier"])
        if type(data["encrypted"]) is not bool or type(data["transfer_completed"]) is not bool:
            raise ValueError("invalid offsite metadata flags")
        if data["checksum_result"] not in {"verified", "failed"}:
            raise ValueError("invalid checksum result")
        return cls(
            run_id=run_id,
            run_time=_parse_time(data["run_time"]),
            source_backup_identifier=source_id,
            encrypted=data["encrypted"],
            transfer_completed=data["transfer_completed"],
            checksum_result=data["checksum_result"],
            offsite_target_identifier=target_id,
        )


@dataclass(frozen=True)
class _SourceFile:
    archive_name: str
    source: Path
    size: int
    checksum: str


@dataclass(frozen=True)
class _SourceRun:
    run_id: str
    run_time: datetime
    source_backup_identifier: str
    files: tuple[_SourceFile, ...]


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("unsafe relative path")
    path = PurePosixPath(value)
    drive, _ = ntpath.splitdrive(value)
    if drive or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe relative path")
    return path


def _contained_file(root: Path, relative: object) -> tuple[Path, str]:
    safe = _safe_relative(relative)
    candidate = (root / Path(*safe.parts)).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _SourceError("source path escapes backup root") from exc
    if not candidate.is_file():
        raise _SourceError("required source file is missing")
    return candidate, safe.as_posix()


def _verified_source_file(root: Path, relative: object, size: object, checksum: object) -> _SourceFile:
    if type(size) is not int or size < 0 or not _is_checksum(checksum):
        raise _SourceError("invalid source file metadata")
    path, archive_name = _contained_file(root, relative)
    if path.stat().st_size != size or _sha256(path) != checksum:
        raise _SourceError("source checksum verification failed")
    return _SourceFile(archive_name, path, size, checksum)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _SourceError("invalid JSON document") from exc


def _load_source_run(backup_root: Path, run_metadata_path: Path) -> _SourceRun:
    root = backup_root.resolve(strict=True)
    run_path = run_metadata_path.resolve(strict=True)
    try:
        run_relative = run_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise _SourceError("run metadata escapes backup root") from exc
    if not run_path.is_file() or not run_path.name.startswith("backup_") or run_path.suffix != ".json":
        raise _SourceError("invalid run metadata path")

    run_id = run_path.stem.removeprefix("backup_")
    _require_identifier(run_id)
    run = _read_json(run_path)
    if not isinstance(run, dict) or run.get("schema_version") != 1 or run.get("status") != "success":
        raise _SourceError("backup run is not a completed schema-v1 run")
    try:
        run_time = _parse_time(run.get("started_at"))
        database = run["database"]
        media = run["media"]
        if not isinstance(database, dict) or not isinstance(media, dict):
            raise TypeError
        database_file = _verified_source_file(
            root, database.get("filename"), database.get("size"), database.get("sha256")
        )
        manifest_path, manifest_relative = _contained_file(root, media.get("manifest"))
        manifest_checksum = media.get("manifest_sha256")
        if not _is_checksum(manifest_checksum) or _sha256(manifest_path) != manifest_checksum:
            raise _SourceError("media manifest checksum verification failed")
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise _SourceError("invalid media manifest")
        entries = manifest.get("files")
        if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
            raise _SourceError("invalid media manifest file count")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, _SourceError):
            raise
        raise _SourceError("invalid backup run metadata") from exc

    files = [
        _SourceFile(run_relative, run_path, run_path.stat().st_size, _sha256(run_path)),
        database_file,
        _SourceFile(manifest_relative, manifest_path, manifest_path.stat().st_size, manifest_checksum),
    ]
    seen = {run_relative, database_file.archive_name, manifest_relative}
    for entry in entries:
        if not isinstance(entry, dict):
            raise _SourceError("invalid media manifest entry")
        try:
            _safe_relative(entry.get("relative_path"))
            media_file = _verified_source_file(
                root, entry.get("archive_path"), entry.get("size"), entry.get("sha256")
            )
        except (TypeError, ValueError) as exc:
            raise _SourceError("invalid media manifest entry") from exc
        if media_file.archive_name in seen:
            raise _SourceError("duplicate backup payload path")
        seen.add(media_file.archive_name)
        files.append(media_file)

    return _SourceRun(
        run_id=run_id,
        run_time=run_time,
        source_backup_identifier=run_path.name,
        files=tuple(sorted(files, key=lambda item: item.archive_name)),
    )


def _create_tar(source: _SourceRun, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination.name)
    with tarfile.open(destination, "x") as archive:
        for item in source.files:
            info = tarfile.TarInfo(item.archive_name)
            info.size = item.size
            info.mode = 0o600
            info.mtime = int(source.run_time.timestamp())
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with item.source.open("rb") as handle:
                archive.addfile(info, handle)


def _safe_archive_member(name: str) -> PurePosixPath:
    try:
        return _safe_relative(name)
    except ValueError as exc:
        raise ValueError("unsafe archive member") from exc


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    """Extract only regular files/directories that remain below a fresh scratch root."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("unsafe archive destination")

    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        checked: list[tuple[tarfile.TarInfo, Path]] = []
        seen: set[str] = set()
        for member in members:
            relative = _safe_archive_member(member.name)
            normalized = relative.as_posix()
            if normalized in seen or not (member.isdir() or member.isreg()):
                raise ValueError("unsafe archive member")
            seen.add(normalized)
            target = (destination / Path(*relative.parts)).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError("unsafe archive member") from exc
            checked.append((member, target))

        try:
            for member, target in checked:
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=False)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("unsafe archive member")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        except (OSError, tarfile.TarError) as exc:
            raise ValueError("unsafe archive member") from exc


class Encryptor(Protocol):
    def available(self) -> bool: ...
    def encrypt(self, source: Path, destination: Path) -> None: ...
    def decrypt(self, source: Path, destination: Path) -> None: ...


class AgeEncryptor:
    """Thin adapter over age. Recipient is public; identity content is never read here."""

    def __init__(
        self,
        *,
        recipient: str,
        identity_file: Path | None = None,
        executable: str = "age",
        timeout_seconds: int = 600,
    ):
        self._recipient = recipient
        self._identity_file = identity_file
        self._requested_executable = executable
        self._executable = (
            str(Path(executable).resolve()) if Path(executable).is_file() else shutil.which(executable)
        )
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"AgeEncryptor(available={self.available()!r})"

    def available(self) -> bool:
        return bool(self._executable and self._recipient)

    def _run(self, command: list[str], destination: Path) -> None:
        if destination.exists():
            raise _EncryptionError("destination already exists")
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            destination.unlink(missing_ok=True)
            raise _EncryptionError("age execution failed") from exc
        if result.returncode != 0 or not destination.is_file():
            destination.unlink(missing_ok=True)
            raise _EncryptionError("age operation failed")

    def encrypt(self, source: Path, destination: Path) -> None:
        if not self.available():
            raise _EncryptionError("age is unavailable")
        self._run([
            self._executable, "--encrypt", "--recipient", self._recipient,
            "--output", str(destination), str(source),
        ], destination)

    def decrypt(self, source: Path, destination: Path) -> None:
        if not self._executable or self._identity_file is None or not self._identity_file.is_file():
            raise _EncryptionError("age decryption is unavailable")
        self._run([
            self._executable, "--decrypt", "--identity", str(self._identity_file),
            "--output", str(destination), str(source),
        ], destination)


class OffsiteTarget(Protocol):
    identifier: str
    def store_run(self, payload: Path, metadata: OffsiteRunMetadata) -> None: ...
    def list_runs(self) -> list[OffsiteRunMetadata]: ...
    def retrieve_run(self, run_id: str, destination: Path) -> Path: ...
    def delete_run(self, run_id: str) -> None: ...


class LocalFilesystemOffsiteTarget:
    """Filesystem provider. A completion marker is the publication boundary."""

    def __init__(self, root: Path, *, identifier: str = "local-filesystem"):
        self.root = Path(root).resolve()
        self.identifier = _require_identifier(identifier)

    def _run_dir(self, run_id: str) -> Path:
        run_id = _require_identifier(run_id)
        candidate = (self.root / run_id).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("invalid run location") from exc
        return candidate

    @staticmethod
    def _payload_name(encrypted: bool) -> str:
        return "payload.age" if encrypted else "payload.tar"

    def store_run(self, payload: Path, metadata: OffsiteRunMetadata) -> None:
        if metadata.offsite_target_identifier != self.identifier or not metadata.transfer_completed:
            raise _TransferError("invalid publication metadata")
        self.root.mkdir(parents=True, exist_ok=True)
        final = self._run_dir(metadata.run_id)
        reserved = False
        try:
            final.mkdir(exist_ok=False)
            reserved = True
            payload_target = final / self._payload_name(metadata.encrypted)
            with payload.open("rb") as source, payload_target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            with (final / "metadata.json").open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(metadata.to_dict(), handle, ensure_ascii=True, sort_keys=True, indent=2)
                handle.write("\n")
            with (final / "complete").open("xb"):
                pass
        except Exception as exc:
            if reserved:
                shutil.rmtree(final, ignore_errors=True)
            raise _TransferError("offsite publication failed") from exc

    def _read_completed(self, run_dir: Path) -> OffsiteRunMetadata:
        if run_dir.is_symlink() or not run_dir.is_dir() or not (run_dir / "complete").is_file():
            raise ValueError("incomplete run")
        metadata = OffsiteRunMetadata.from_dict(json.loads((run_dir / "metadata.json").read_text("utf-8")))
        if metadata.run_id != run_dir.name or metadata.offsite_target_identifier != self.identifier:
            raise ValueError("mismatched run metadata")
        payload = run_dir / self._payload_name(metadata.encrypted)
        if not metadata.transfer_completed or metadata.checksum_result != "verified" or not payload.is_file():
            raise ValueError("incomplete run")
        return metadata

    def list_runs(self) -> list[OffsiteRunMetadata]:
        if not self.root.is_dir():
            return []
        runs: list[OffsiteRunMetadata] = []
        for entry in sorted(self.root.iterdir(), key=lambda item: item.name):
            try:
                _require_identifier(entry.name)
                runs.append(self._read_completed(entry))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
        return sorted(runs, key=lambda item: (item.run_time, item.run_id), reverse=True)

    def retrieve_run(self, run_id: str, destination: Path) -> Path:
        metadata = self._read_completed(self._run_dir(run_id))
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / self._payload_name(metadata.encrypted)
        try:
            with (self._run_dir(run_id) / output.name).open("rb") as source, output.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise _TransferError("offsite retrieval failed") from exc
        return output

    def delete_run(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        self._read_completed(run_dir)
        if run_dir.is_symlink():
            raise _TransferError("unsafe offsite run")
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            raise _TransferError("offsite deletion failed") from exc


def _result(operation: str, success: bool, code: OffsiteOutcome, run_id: str | None, started: datetime) -> OperationResult:
    return OperationResult(operation, success, code, run_id, started, _now())


def copy_completed_run(
    backup_root: Path,
    run_metadata_path: Path,
    target: OffsiteTarget,
    *,
    encryption_required: bool = False,
    encryptor: Encryptor | None = None,
    scratch_root: Path | None = None,
) -> OperationResult:
    started = _now()
    run_id: str | None = None
    try:
        source = _load_source_run(Path(backup_root), Path(run_metadata_path))
        run_id = source.run_id
    except Exception:
        return _result("copy", False, OffsiteOutcome.LOCAL_BACKUP_FAILURE, run_id, started)

    if encryption_required and (encryptor is None or not encryptor.available()):
        return _result("copy", False, OffsiteOutcome.ENCRYPTION_FAILURE, run_id, started)

    try:
        with tempfile.TemporaryDirectory(dir=scratch_root) as temporary:
            scratch = Path(temporary)
            tar_path = scratch / "payload.tar"
            _create_tar(source, tar_path)
            verification_root = scratch / "package-verification"
            safe_extract_tar(tar_path, verification_root)
            verified = _load_source_run(
                verification_root,
                verification_root / "runs" / source.source_backup_identifier,
            )
            if verified.run_id != source.run_id:
                raise _SourceError("packaged run mismatch")

            payload = tar_path
            encrypted = False
            if encryption_required:
                encrypted_path = scratch / "payload.age"
                try:
                    encryptor.encrypt(tar_path, encrypted_path)
                except Exception:
                    return _result("copy", False, OffsiteOutcome.ENCRYPTION_FAILURE, run_id, started)
                if not encrypted_path.is_file():
                    return _result("copy", False, OffsiteOutcome.ENCRYPTION_FAILURE, run_id, started)
                payload = encrypted_path
                encrypted = True

            metadata = OffsiteRunMetadata(
                run_id=source.run_id,
                run_time=source.run_time,
                source_backup_identifier=source.source_backup_identifier,
                encrypted=encrypted,
                transfer_completed=True,
                checksum_result="verified",
                offsite_target_identifier=target.identifier,
            )
            try:
                target.store_run(payload, metadata)
            except Exception:
                return _result("copy", False, OffsiteOutcome.OFFSITE_TRANSFER_FAILURE, run_id, started)
    except Exception:
        return _result("copy", False, OffsiteOutcome.LOCAL_BACKUP_FAILURE, run_id, started)
    return _result("copy", True, OffsiteOutcome.SUCCESS, run_id, started)


def verify_offsite_run(
    target: OffsiteTarget,
    run_id: str,
    *,
    encryptor: Encryptor | None = None,
    scratch_root: Path | None = None,
) -> OperationResult:
    started = _now()
    try:
        _require_identifier(run_id)
        metadata = next(item for item in target.list_runs() if item.run_id == run_id)
    except Exception:
        return _result("verify", False, OffsiteOutcome.VERIFICATION_FAILURE, run_id, started)

    if metadata.encrypted and (encryptor is None or not encryptor.available()):
        return _result("verify", False, OffsiteOutcome.ENCRYPTION_FAILURE, run_id, started)

    try:
        with tempfile.TemporaryDirectory(dir=scratch_root) as temporary:
            scratch = Path(temporary)
            retrieved = target.retrieve_run(run_id, scratch / "retrieved")
            payload = retrieved
            if metadata.encrypted:
                payload = scratch / "payload.tar"
                try:
                    encryptor.decrypt(retrieved, payload)
                except Exception:
                    return _result("verify", False, OffsiteOutcome.ENCRYPTION_FAILURE, run_id, started)
            extracted = scratch / "extracted"
            safe_extract_tar(payload, extracted)
            source = _load_source_run(
                extracted,
                extracted / "runs" / metadata.source_backup_identifier,
            )
            if source.run_id != metadata.run_id or source.run_time != metadata.run_time:
                raise _SourceError("retrieved run mismatch")
    except Exception:
        return _result("verify", False, OffsiteOutcome.VERIFICATION_FAILURE, run_id, started)
    return _result("verify", True, OffsiteOutcome.SUCCESS, run_id, started)


@dataclass(frozen=True)
class RetentionPlan:
    keep: tuple[str, ...]
    delete: tuple[str, ...]
    invalid: tuple[str, ...]


def plan_retention(
    runs: list[OffsiteRunMetadata],
    *,
    daily: int = DEFAULT_DAILY_RETENTION,
    weekly: int = DEFAULT_WEEKLY_RETENTION,
    monthly: int = DEFAULT_MONTHLY_RETENTION,
    timezone_name: str = DEFAULT_RETENTION_TIMEZONE,
) -> RetentionPlan:
    if min(daily, weekly, monthly) < 0:
        raise ValueError("retention counts must be nonnegative")
    local_zone = ZoneInfo(timezone_name)
    valid: dict[str, OffsiteRunMetadata] = {}
    invalid: set[str] = set()
    for run in runs:
        is_valid = (
            _valid_identifier(run.run_id)
            and run.run_time.tzinfo is not None
            and run.run_time.utcoffset() is not None
            and run.transfer_completed
            and run.checksum_result == "verified"
        )
        if not is_valid:
            invalid.add(run.run_id)
            continue
        previous = valid.get(run.run_id)
        if previous is None or run.run_time > previous.run_time:
            valid[run.run_id] = run

    ordered = sorted(valid.values(), key=lambda item: (item.run_time, item.run_id), reverse=True)
    keep: set[str] = set()
    if ordered:
        keep.add(ordered[0].run_id)

    def select(limit: int, bucket) -> None:
        seen = set()
        for run in ordered:
            key = bucket(run.run_time.astimezone(local_zone))
            if key in seen:
                continue
            if len(seen) >= limit:
                break
            seen.add(key)
            keep.add(run.run_id)

    select(daily, lambda value: value.date())
    select(weekly, lambda value: value.isocalendar()[:2])
    select(monthly, lambda value: (value.year, value.month))
    keep_ordered = tuple(run.run_id for run in ordered if run.run_id in keep)
    delete_ordered = tuple(run.run_id for run in ordered if run.run_id not in keep)
    return RetentionPlan(keep_ordered, delete_ordered, tuple(sorted(invalid)))


@dataclass(frozen=True)
class CleanupResult:
    success: bool
    code: OffsiteOutcome
    deleted: tuple[str, ...] = field(default_factory=tuple)
    would_delete: tuple[str, ...] = field(default_factory=tuple)
    failed: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "code": self.code.value,
            "deleted": list(self.deleted),
            "would_delete": list(self.would_delete),
            "failed": list(self.failed),
        }


def cleanup_retention(target: OffsiteTarget, plan: RetentionPlan, *, dry_run: bool) -> CleanupResult:
    if dry_run:
        return CleanupResult(True, OffsiteOutcome.SUCCESS, would_delete=plan.delete)
    deleted: list[str] = []
    failed: list[str] = []
    for run_id in plan.delete:
        try:
            target.delete_run(run_id)
            deleted.append(run_id)
        except Exception:
            failed.append(run_id)
    return CleanupResult(
        not failed,
        OffsiteOutcome.RETENTION_CLEANUP_FAILURE if failed else OffsiteOutcome.SUCCESS,
        deleted=tuple(deleted),
        failed=tuple(failed),
    )
