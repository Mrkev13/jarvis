"""Content-addressed local storage for study materials (MRK-42).

Files live in MEDIA_DIR/study-materials/<sha256>.<ext>: the name is derived from the content only (never from an
upstream file name or URL), so identical binaries are stored once and a path traversal is impossible by
construction. The type is decided from the bytes (signature), not from a header or extension; nothing is executed,
unpacked to disk or rendered.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from pathlib import Path

FOLDER = 'study-materials'
STORED_NAME_RE = re.compile(r'^[0-9a-f]{64}\.(pdf|pptx|docx|txt)$')
CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'txt': 'text/plain; charset=utf-8',
}
_OOXML_MAIN = {'pptx': 'ppt/presentation.xml', 'docx': 'word/document.xml'}
MAX_ZIP_ENTRIES = 5000


class StorageError(ValueError):
    pass


def media_dir() -> Path:
    return Path(os.environ.get('MEDIA_DIR', './media'))


def _folder() -> Path:
    path = (media_dir() / FOLDER).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_for(stored_name: str) -> Path:
    if not STORED_NAME_RE.fullmatch(stored_name or ''):
        raise StorageError('invalid stored name')
    folder = _folder()
    path = (folder / stored_name).resolve()
    if path.parent != folder:
        raise StorageError('invalid stored name')
    return path


def sniff(data: bytes, expected: str) -> bool:
    """Does the binary really look like the allowlisted type the metadata claims?"""
    if expected == 'pdf':
        return data[:5] == b'%PDF-'
    if expected in _OOXML_MAIN:
        if data[:4] != b'PK\x03\x04':
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                return (len(names) <= MAX_ZIP_ENTRIES and '[Content_Types].xml' in names
                        and _OOXML_MAIN[expected] in names)
        except Exception:  # noqa: BLE001 - a broken archive is simply not this type
            return False
    if expected == 'txt':
        if b'\x00' in data:
            return False
        try:
            data.decode('utf-8')
            return True
        except UnicodeDecodeError:
            return False
    return False


def store(data: bytes, material_type: str) -> tuple[str, str]:
    """Write once (atomic rename); returns (stored_name, sha256). Existing identical content is reused."""
    if material_type not in CONTENT_TYPES:
        raise StorageError('type not storable')
    checksum = hashlib.sha256(data).hexdigest()
    name = f'{checksum}.{material_type}'
    path = path_for(name)
    if not path.exists():
        tmp = path.with_name(f'.{name}.{os.getpid()}.tmp')
        with open(tmp, 'wb') as handle:
            handle.write(data)
        os.replace(tmp, path)
    return name, checksum


def exists(stored_name: str | None) -> bool:
    if not stored_name:
        return False
    try:
        return path_for(stored_name).is_file()
    except StorageError:
        return False


def read(stored_name: str) -> bytes:
    return path_for(stored_name).read_bytes()
