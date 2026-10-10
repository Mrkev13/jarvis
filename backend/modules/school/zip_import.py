"""Moodle course ZIP import (MRK-56) – fallback when Moodle Web Services are not available to the user.

Input = the official Moodle feature „Stáhnout obsah kurzu" (one ZIP per course); no token, no scraping, no login
automation. One shared core: the export is parsed into the MRK-42 `CourseSnapshot`/`RemoteFile` model and applied by
`service._sync_course` – same tables, identity scheme, storage, extraction, domain events, Search and What Changed.
The UI upload and the folder wrapper (`scripts/import_moodle_zips.py`) both call `import_course_export`.

Identity: the export's own folder numbers under the separate source `moodle_export`. They are NOT Moodle API ids
(verified on a real export: the course id linked from the export index differs from the folder number), so no
reconciliation with Web Services rows is claimed.

Completeness: a course export is not provably complete – Moodle omits files over its download limit and items it
cannot export, and folder activities may come without files. An import therefore only adds/updates materials and
never marks anything `source_missing`.

HTML pages in the export are parsed locally (bounded, no network) for course/activity names and section headings
only; only PDF/PPTX/DOCX/TXT become stored materials. Archives are validated before anything is read: no absolute
paths, drive letters, backslashes, `.`/`..` segments, symlinks, encrypted or duplicate entries, bounded entry count,
declared total size and compression ratio; entries are streamed with hard size caps (zip bombs) and nested archives
are never expanded. Nothing is extracted to disk.
"""
from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote

from env_config import env_int
from modules.school.moodle import MoodleSyncError, max_file_bytes
from modules.school.service import (
    STORABLE, CourseSnapshot, MaterialError, RemoteFile, _identity, _new_stats, _sync_course, _text, material_type_for,
)
from time_utils import utc_now

SOURCE = 'moodle_export'
CONTEXT = 'moodle_zip_import'
DEFAULT_MAX_ARCHIVE_MB = 512
MAX_ENTRIES = 5000
MAX_DECLARED_TOTAL = 4 * 1024 ** 3  # sum of declared uncompressed sizes (bomb guard; we never read most entries)
MAX_RATIO = 200  # per entry, for entries above RATIO_MIN_BYTES
RATIO_MIN_BYTES = 1024 * 1024
MAX_HTML_BYTES = 1_000_000
MAX_NAME = 1024
CHUNK = 64 * 1024
NESTED_ARCHIVES = ('.zip', '.rar', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.zst')
_ID_SUFFIX = re.compile(r'\.(\d{1,20})$')
_COURSE_CODE = re.compile(r'(?<![A-Za-z0-9])[A-Z]{2,5}\d{1,4}[A-Z]?(?![A-Za-z0-9])')


class ZipImportError(MaterialError):
    CATEGORIES = frozenset({'archive_invalid', 'archive_too_large', 'not_course_export', 'unsafe_path', 'symlink_entry',
                            'encrypted_entry', 'duplicate_entry', 'too_many_entries', 'uncompressed_too_large',
                            'compression_ratio', 'import_failed'})

    def __init__(self, category: str, status: int = 400):
        super().__init__(category if category in self.CATEGORIES else 'archive_invalid', status)


class _TooLarge(Exception):
    pass


def max_archive_bytes() -> int:
    return max(1, min(env_int('MOODLE_ZIP_MAX_MB', DEFAULT_MAX_ARCHIVE_MB), 4096)) * 1024 * 1024


# ---------- archive validation & bounded reads ----------

def _unsafe_name(name: str) -> bool:
    if not name or len(name) > MAX_NAME or name.startswith(('/', '\\')) or '\\' in name or ':' in name:
        return True
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return True
    parts = (name[:-1] if name.endswith('/') else name).split('/')
    return any(part in ('', '.', '..') for part in parts)


def _validated(zf: zipfile.ZipFile) -> tuple[str, str, dict[str, zipfile.ZipInfo]]:
    infos = zf.infolist()
    if not infos:
        raise ZipImportError('not_course_export')
    if len(infos) > MAX_ENTRIES:
        raise ZipImportError('too_many_entries', 413)
    seen: set[str] = set()
    declared = 0
    for info in infos:
        if _unsafe_name(info.filename):
            raise ZipImportError('unsafe_path')
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ZipImportError('symlink_entry')
        if info.flag_bits & 0x1:
            raise ZipImportError('encrypted_entry')
        key = info.filename.rstrip('/').casefold()
        if key in seen:
            raise ZipImportError('duplicate_entry')
        seen.add(key)
        declared += info.file_size
        if declared > MAX_DECLARED_TOTAL:
            raise ZipImportError('uncompressed_too_large', 413)
        if info.file_size > RATIO_MIN_BYTES and info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise ZipImportError('compression_ratio')
    files = {i.filename: i for i in infos if not i.is_dir()}
    roots = {i.filename.split('/', 1)[0] for i in infos}
    if len(roots) != 1:
        raise ZipImportError('not_course_export')
    root = roots.pop()
    match = _ID_SUFFIX.search(root)
    if match is None or f'{root}/index.html' not in files:
        raise ZipImportError('not_course_export')
    return root, match.group(1), files


def _stream(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int, sink) -> int:
    """Feed the entry to `sink` in chunks; abort past `cap` actual bytes whatever the header claims."""
    if info.file_size > cap:
        raise _TooLarge
    total = 0
    with zf.open(info) as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                return total
            total += len(chunk)
            if total > cap:
                raise _TooLarge
            sink(chunk)


def _read(zf, info, cap: int) -> bytes:
    buffer = bytearray()
    _stream(zf, info, cap, buffer.extend)
    return bytes(buffer)


def _sha256(zf, info, cap: int) -> str | None:
    digest = hashlib.sha256()
    try:
        _stream(zf, info, cap, digest.update)
    except _TooLarge:
        return None
    return digest.hexdigest()


class _ZipClient:
    """The MRK-42 download seam over the archive: `file_url` is a validated entry name (transient, never stored)."""

    def __init__(self, zf: zipfile.ZipFile, files: dict[str, zipfile.ZipInfo]):
        self._zf, self._files = zf, files

    def download(self, file_url: str, max_bytes: int) -> bytes:
        info = self._files.get(file_url)
        if info is None:
            raise MoodleSyncError('file_url_rejected')
        try:
            return _read(self._zf, info, max_bytes)
        except _TooLarge:
            category = 'file_too_large'
        except Exception:  # noqa: BLE001 - CRC/corruption: a transient failure for this file only
            category = 'unavailable'
        raise MoodleSyncError(category)


# ---------- local HTML metadata (names/sections only) ----------

class _Outline(HTMLParser):
    """Ordered headings (h1–h4 text) and link targets; scripts/styles are never executed or kept."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self._heading: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self._heading, self._text = tag, []
        elif tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.events.append(('a', href))

    def handle_data(self, data):
        if self._heading:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == self._heading:
            self.events.append((tag, ' '.join(''.join(self._text).split())))
            self._heading = None


def _outline(zf, info) -> list[tuple[str, str]]:
    if info is None:
        return []
    try:
        data = _read(zf, info, MAX_HTML_BYTES)
    except Exception:  # noqa: BLE001 - oversized/corrupt page: no metadata, never a failure
        return []
    parser = _Outline()
    try:
        parser.feed(data.decode('utf-8', 'replace'))
        parser.close()
    except Exception:  # noqa: BLE001
        return []
    return parser.events


def _relative(href: str) -> str | None:
    """Local link target relative to the page (`./x/index.html` → `x/index.html`); external/unsafe → None."""
    href = unquote(href.split('#', 1)[0].split('?', 1)[0]).strip()
    if not href or '://' in href or href.startswith(('/', '{')) or '\\' in href:
        return None
    parts = [p for p in href.split('/') if p not in ('', '.')]
    return None if not parts or '..' in parts else '/'.join(parts)


def _fallback_name(folder: str) -> str:
    base = _ID_SUFFIX.sub('', folder).rstrip('_')
    base = base.split('_', 1)[1] if '_' in base else base
    return ' '.join(base.replace('_', ' ').split()) or folder


# ---------- export → snapshot ----------

@dataclass
class CourseExport:
    external_id: str
    name: str
    short_name: str | None
    snapshot: CourseSnapshot
    files: dict[str, zipfile.ZipInfo]
    activities: int = 0
    listed_missing: int = 0
    archives_ignored: int = 0


def parse_export(zf: zipfile.ZipFile, limit: int) -> CourseExport:
    root, export_id, files = _validated(zf)
    root_events = _outline(zf, files.get(f'{root}/index.html'))
    course_name = next((text for tag, text in root_events if tag == 'h1' and text), None)
    sections: dict[str, str | None] = {}
    current: str | None = None
    for tag, value in root_events:
        if tag == 'h3':
            current = value or None
        elif tag == 'a':
            target = _relative(value)
            if target and target.endswith('/index.html') and target.count('/') == 1:
                sections.setdefault(target.split('/', 1)[0], current)

    contents: dict[str, list[zipfile.ZipInfo]] = {}
    pages: dict[str, zipfile.ZipInfo] = {}
    archives_ignored = 0
    for name, info in files.items():
        if name.lower().endswith(NESTED_ARCHIVES):
            archives_ignored += 1  # never opened; listed as an unsupported file if it sits in an activity
        parts = name.split('/')
        if len(parts) >= 4 and parts[2] == 'content':
            contents.setdefault(parts[1], []).append(info)
        elif len(parts) == 3 and parts[2] == 'index.html':
            pages[parts[1]] = info

    snap = CourseSnapshot(complete=False)  # never provably complete – see module docstring
    seen: set[str] = set()
    listed_missing = activities = 0
    for folder in sorted(set(contents) | set(pages)):
        match = _ID_SUFFIX.search(folder)
        if match is None:
            if folder in contents:
                snap.errors += 1
            continue
        activity_id = match.group(1)
        events = _outline(zf, pages.get(folder))
        headings = [text for tag, text in events if tag in ('h1', 'h2', 'h3', 'h4') and text and text != course_name]
        title = (_text(headings[0], 300) if headings else None) or _fallback_name(folder)
        present = {'/'.join(i.filename.split('/')[3:]): i for i in contents.get(folder, [])}
        listed = []
        for tag, value in events:
            target = _relative(value) if tag == 'a' else None
            if target and target.startswith('content/') and target[len('content/'):] not in listed:
                listed.append(target[len('content/'):])
        missing = [rel for rel in listed if rel not in present]
        entries = [(rel, present[rel]) for rel in sorted(present)] + [(rel, None) for rel in missing]
        if not entries:
            continue  # page/quiz/forum etc.: HTML only, never a material
        activities += 1
        listed_missing += len(missing)
        for rel, info in entries:
            segments = rel.split('/')
            file_name = _text(segments[-1], 255)
            if file_name is None or any(not s or s in ('.', '..') for s in segments):
                snap.errors += 1
                continue
            path = '/' + '/'.join(segments[:-1]) + '/' if len(segments) > 1 else '/'
            identity = _identity(activity_id, path, file_name)
            if identity in seen:
                snap.duplicates += 1
                continue
            seen.add(identity)
            material_type = material_type_for(file_name)
            digest = None
            if info is not None and material_type in STORABLE and info.file_size <= limit:
                digest = _sha256(zf, info, limit)
            label = title if len(entries) == 1 else f'{title} – {file_name}'
            snap.files.append(RemoteFile(
                external_id=identity, module_external_id=activity_id, title=label[:300],
                section_name=_text(sections.get(folder), 300), file_name=file_name, material_type=material_type,
                mime_type=None, size_bytes=info.file_size if info is not None else None, source_modified_at=None,
                file_url=info.filename if info is not None else None, content_sha256=digest))

    codes = list(dict.fromkeys(_COURSE_CODE.findall(root)))
    return CourseExport(
        external_id=export_id, name=_text(course_name, 300) or _fallback_name(root),
        short_name=_text(', '.join(codes), 100) if codes else None, snapshot=snap, files=files,
        activities=activities, listed_missing=listed_missing, archives_ignored=archives_ignored)


def import_course_export(db, fileobj, *, now=None) -> dict:
    """Validate + import one course ZIP in a single transaction (commit, or full rollback on failure)."""
    try:
        zf = zipfile.ZipFile(fileobj)
    except Exception:  # noqa: BLE001 - not a readable ZIP (BadZipFile, truncated, …)
        zf = None
    if zf is None:
        raise ZipImportError('archive_invalid')
    with zf:
        limit = max_file_bytes()
        export = parse_export(zf, limit)
        now = now or utc_now()
        stats = _new_stats()
        failed = False
        try:
            course = _sync_course(db, export.external_id, export.name, export.short_name, export.snapshot,
                                  _ZipClient(zf, export.files), limit, now, stats, source=SOURCE, context=CONTEXT)
            db.commit()
        except Exception:  # noqa: BLE001 - nothing half-imported; no upstream text leaks to the client
            db.rollback()
            failed = True
        if failed:
            raise ZipImportError('import_failed', 500)
    stats.update(courses=1, course_id=course.id, export_course_id=export.external_id, completeness='unproven',
                 activities=export.activities, files_listed_missing=export.listed_missing,
                 archives_ignored=export.archives_ignored)
    return stats
