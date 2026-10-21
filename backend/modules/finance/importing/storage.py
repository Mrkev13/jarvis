"""Raw statement files between preview and commit (MRK-62).

Outside `MEDIA_DIR` and outside backups: `FINANCE_IMPORT_TMP_DIR` (default: system temp / standa-hub-finance-import).
Names carry only the import id, never the original filename. A file lives at most `TTL` and is deleted after commit,
failure, cancellation or expiry; the hourly cleanup also removes leftovers of crashed requests.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from env_config import env_int, env_str

TTL = timedelta(minutes=30)
DEFAULT_MAX_MB = 20
HARD_MAX_MB = 200
_STAGED_PREFIX = "import-"
_UPLOAD_PREFIX = "upload-"
_SUFFIX = ".bin"


def upload_dir() -> Path:
    root = Path(env_str("FINANCE_IMPORT_TMP_DIR", str(Path(tempfile.gettempdir()) / "standa-hub-finance-import")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def max_upload_bytes() -> int:
    return min(env_int("FINANCE_IMPORT_MAX_MB", DEFAULT_MAX_MB, minimum=1), HARD_MAX_MB) * 1024 * 1024


def new_upload_path() -> Path:
    fd, name = tempfile.mkstemp(prefix=_UPLOAD_PREFIX, suffix=_SUFFIX, dir=upload_dir())
    os.close(fd)
    return Path(name)


def staged_path(import_id: int) -> Path:
    return upload_dir() / f"{_STAGED_PREFIX}{int(import_id)}{_SUFFIX}"


def stage(upload: Path, import_id: int) -> Path:
    """Přesune nahraný soubor pod id importu (nahradí starší náhled téhož souboru)."""
    target = staged_path(import_id)
    os.replace(upload, target)
    return target


def discard(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # úklid nesmí shodit request; hodinový úklid to zkusí znovu


def discard_import(import_id: int) -> None:
    discard(staged_path(import_id))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_stale_files() -> int:
    """Smaže soubory importu starší než TTL podle mtime (pády requestů, nedokončené náhledy). Vrací počet."""
    removed = 0
    cutoff = time.time() - TTL.total_seconds()  # epocha souborového systému, ne naive UTC z DB
    for path in upload_dir().glob(f"*{_SUFFIX}"):
        if not path.name.startswith((_STAGED_PREFIX, _UPLOAD_PREFIX)):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed
