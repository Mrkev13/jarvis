"""Study-material sync and read model (MRK-42).

Sync = discover Moodle courses (official WS API), then per course: one `core_course_get_contents` call is a complete
snapshot of that course's file resources. Each course is its own transaction (row-locked course, commit or full
rollback): a failed or malformed course never hides anything, a successful one reconciles presence – absent
identities get `source_missing_at` (never deleted), reappearing ones restore the same row.

Idempotence: identity = (course, "<cmid>:<filepath><filename>"). An unchanged file is neither downloaded nor written.
Downloads are allowlisted (PDF, PPTX, DOCX, TXT), size-capped, signature-checked and content-addressed (one copy per
checksum). Facts go through domain events with one Activity projection each; payloads carry ids/states only.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from env_config import env_str
from models import Subject
from modules.school import storage
from modules.school.extract import extract_text
from modules.school.models import StudyCourse, StudyMaterial
from modules.school.moodle import MoodleSyncError, MoodleWsClient, load_config, max_file_bytes
from time_utils import utc_now

FILE_MODULES = ('resource', 'folder')  # Moodle activity types that carry course files
EXTENSIONS = {'pdf': 'pdf', 'pptx': 'pptx', 'docx': 'docx', 'txt': 'txt'}
STORABLE = frozenset(EXTENSIONS.values())
MAX_IDENTITY = 512
AUDIT_FIELDS = ('title', 'file_name', 'material_type', 'size_bytes', 'source_modified_at', 'download_status', 'checksum')
META_FIELDS = ('module_external_id', 'title', 'section_name', 'file_name', 'material_type', 'mime_type', 'size_bytes',
               'source_modified_at')
LIST_LIMIT = 500
EXCERPT_CHARS = 3000


class MaterialError(ValueError):
    def __init__(self, category: str, status: int = 400):
        super().__init__(category)
        self.category, self.status = category, status


# ---------- snapshot parsing (pure) ----------

@dataclass(frozen=True)
class RemoteFile:
    external_id: str
    module_external_id: str
    title: str
    section_name: str | None
    file_name: str
    material_type: str
    mime_type: str | None
    size_bytes: int | None
    source_modified_at: datetime | None
    file_url: str | None  # transient – never stored, logged or returned
    # MRK-56: sha256 of the bytes when the source has them locally (ZIP export); detects content changes that keep
    # size and timestamp (export timestamps are the export time). None for Web Services (no download to compare).
    content_sha256: str | None = None


@dataclass
class CourseSnapshot:
    files: list[RemoteFile] = field(default_factory=list)
    complete: bool = True
    uncertain_modules: set[str] = field(default_factory=set)
    errors: int = 0
    duplicates: int = 0


def _text(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = ''.join(ch for ch in value if ch.isprintable()).strip()
    return clean[:limit] or None


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ts(value) -> datetime | None:
    value = _int(value)
    if value is None or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def material_type_for(file_name: str) -> str:
    ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
    return EXTENSIONS.get(ext, 'other')


def _identity(cmid: str, path: str, name: str) -> str:
    raw = f'{cmid}:{path}{name}'
    return raw if len(raw) <= MAX_IDENTITY else f'{cmid}:sha256:{hashlib.sha256(raw.encode()).hexdigest()}'


def parse_course_contents(sections) -> CourseSnapshot:
    """`core_course_get_contents` → file entries. Anything malformed makes the snapshot (or that module) uncertain,
    so reconciliation never hides what could not be read."""
    snap = CourseSnapshot()
    if not isinstance(sections, list):
        raise MoodleSyncError('response_invalid')
    seen: set[str] = set()
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get('modules', []), list):
            snap.complete, snap.errors = False, snap.errors + 1
            continue
        section_name = _text(section.get('name'), 300)
        for module in section.get('modules', []):
            cmid = _int(module.get('id')) if isinstance(module, dict) else None
            if cmid is None or cmid <= 0:
                snap.complete, snap.errors = False, snap.errors + 1
                continue
            if module.get('modname') not in FILE_MODULES:
                continue
            if module.get('uservisible') is False:
                continue  # not available to the user right now = absent from this snapshot
            contents = module.get('contents')
            if not isinstance(contents, list):
                snap.uncertain_modules.add(str(cmid))
                snap.errors += 1
                continue
            files = [c for c in contents if isinstance(c, dict) and c.get('type') == 'file']
            module_name = _text(module.get('name'), 300)
            for content in files:
                name = _text(content.get('filename'), 255)
                path = content.get('filepath', '/')
                size = content.get('filesize')
                url = content.get('fileurl')
                if (name is None or '/' in name or '\\' in name or not isinstance(path, str)
                        or (size is not None and (_int(size) is None or size < 0))
                        or (url is not None and not isinstance(url, str))):
                    snap.uncertain_modules.add(str(cmid))
                    snap.errors += 1
                    continue
                identity = _identity(str(cmid), path, name)
                if identity in seen:
                    snap.duplicates += 1
                    continue
                seen.add(identity)
                title = module_name if (module_name and len(files) == 1) else (
                    f'{module_name} – {name}' if module_name else name)
                snap.files.append(RemoteFile(
                    external_id=identity, module_external_id=str(cmid), title=title[:300], section_name=section_name,
                    file_name=name, material_type=material_type_for(name),
                    mime_type=_text(content.get('mimetype'), 120), size_bytes=_int(size),
                    source_modified_at=_ts(content.get('timemodified')) or _ts(content.get('timecreated')),
                    file_url=url))
    return snap


# ---------- sync ----------

def _course_filter() -> set[str] | None:
    raw = env_str('MOODLE_COURSE_IDS')
    return {part.strip() for part in raw.split(',') if part.strip()} or None if raw else None


SOURCE_LABELS = {'moodle': 'Moodle kurz nalezen', 'moodle_export': 'Moodle kurz importován ze ZIPu'}


def _course_row(db, external_id: str, name: str, short_name: str | None, now, *, source: str = 'moodle',
                context: str = 'moodle_sync') -> StudyCourse:
    insert = postgres_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    result = db.execute(insert(StudyCourse).values(source=source, external_id=external_id, name=name,
                                                   short_name=short_name, created_at=now, updated_at=now)
                        .on_conflict_do_nothing(index_elements=['source', 'external_id']))
    # row lock: concurrent syncs/imports of one course serialize here until commit
    course = (db.query(StudyCourse).filter_by(source=source, external_id=external_id)
              .populate_existing().with_for_update().one())
    if result.rowcount == 1:
        log_activity(db, 'school', 'create', f'{SOURCE_LABELS[source]}: {name}', entity_type='study_course',
                     entity_id=course.id, user_context=context)
    return course


def _event(db, row, action: str, now, delta: dict, changed: list[str], context: str = 'moodle_sync'):
    labels = {'created': ('create', 'Nový studijní materiál'), 'updated': ('update', 'Studijní materiál změněn'),
              'source_missing': ('source_missing', 'Materiál zmizel z Moodlu'),
              'restored': ('restore', 'Materiál je zpět v Moodlu')}
    activity_action, label = labels[action]
    append_domain_event(
        db, event_type=f'school.material.{action}', aggregate_type='study_material', aggregate_id=row.id, now=now,
        payload={'material_id': row.id, 'course_id': row.course_id, 'material_type': row.material_type,
                 'download_status': row.download_status, 'changed': changed},
        activity=ActivityProjection('school', activity_action, f'{label}: {row.title}', 'study_material', row.id,
                                    delta or None, context))


def _is_error_body(data: bytes) -> bool:
    """Moodle answers some file errors with a JSON body and HTTP 200; never store that as a material."""
    if not data.lstrip()[:1] == b'{':
        return False
    try:
        body = json.loads(data.decode('utf-8'))
    except Exception:  # noqa: BLE001
        return False
    return isinstance(body, dict) and ('errorcode' in body or 'exception' in body or 'error' in body)


def _fetch_binary(client, remote: RemoteFile, limit: int) -> tuple[str, bytes | None]:
    """Download policy → (download_status, data). Metadata-only outcomes return no data."""
    if remote.material_type not in STORABLE:
        return 'unsupported', None
    if remote.size_bytes is not None and remote.size_bytes > limit:
        return 'too_large', None
    if not remote.file_url:
        return 'metadata_only', None
    try:
        data = client.download(remote.file_url, limit)
    except MoodleSyncError as error:
        return {'file_too_large': 'too_large', 'file_url_rejected': 'rejected'}.get(error.category, 'failed'), None
    except Exception:  # noqa: BLE001 - a test double or transport bug must not leak upstream text
        return 'failed', None
    if len(data) > limit:
        return 'too_large', None
    if _is_error_body(data):
        return 'failed', None
    if not storage.sniff(data, remote.material_type):
        return 'rejected', None
    return 'stored', data


def _needs_download(row, remote: RemoteFile, limit: int) -> bool:
    if remote.material_type not in STORABLE:
        return False
    if row is None or row.size_bytes != remote.size_bytes or row.source_modified_at != remote.source_modified_at:
        return True
    if remote.content_sha256 is not None and row.download_status == 'stored' and row.checksum != remote.content_sha256:
        return True  # local bytes differ from the stored copy (same size, no usable timestamp)
    if row.download_status == 'failed' or row.material_type != remote.material_type:
        return True
    if row.download_status == 'too_large' and remote.size_bytes is not None and remote.size_bytes <= limit:
        return True  # MOODLE_MAX_FILE_MB was raised since
    return row.download_status == 'stored' and not storage.exists(row.stored_name)


def _apply_file(db, course: StudyCourse, remote: RemoteFile, client, limit: int, now, stats,
                context: str = 'moodle_sync'):
    row = (db.query(StudyMaterial).filter_by(course_id=course.id, external_id=remote.external_id)
           .populate_existing().one_or_none())
    restoring = row is not None and row.source_missing_at is not None
    values = {name: getattr(remote, name) for name in META_FIELDS}
    cleared = dict(stored_name=None, checksum=None, stored_size=None, extraction_status=None, extracted_text=None,
                   extracted_at=None)
    if _needs_download(row, remote, limit):
        status, data = _fetch_binary(client, remote, limit)
        values['download_status'] = status
        if data is not None:
            stored_name, checksum = storage.store(data, remote.material_type)
            values.update(stored_name=stored_name, checksum=checksum, stored_size=len(data))
            if row is None or row.checksum != checksum or row.extraction_status is None:
                extraction = extract_text(data, remote.material_type)
                values.update(extraction_status=extraction.status, extracted_text=extraction.text, extracted_at=now)
            stats['downloaded'] += 1
        elif status != 'failed':
            # policy outcome for this version: no binary is linked (older content-addressed files stay on disk);
            # a transient 'failed' keeps the previous binary and is retried by the next sync
            values.update(cleared)
        stats[f'file_{status}'] += 1
    elif remote.material_type not in STORABLE:
        values.update(download_status='unsupported', **cleared)
        if row is None or row.download_status != 'unsupported':
            stats['file_unsupported'] += 1

    changed = [name for name, value in values.items() if row is None or getattr(row, name) != value]
    if not changed and not restoring:
        stats['unchanged'] += 1
        return
    created = row is None
    before = {name: _audit(getattr(row, name)) for name in AUDIT_FIELDS} if row is not None else {}
    if created:
        row = StudyMaterial(course_id=course.id, external_id=remote.external_id, created_at=now)
        db.add(row)
    for name, value in values.items():
        setattr(row, name, value)
    row.updated_at = now
    row.source_missing_at = None
    db.flush()
    after = {name: _audit(getattr(row, name)) for name in AUDIT_FIELDS}
    delta = {name: {'old': before.get(name), 'new': after[name]} for name in AUDIT_FIELDS if before.get(name) != after[name]}
    if restoring:
        delta['source'] = {'old': 'missing', 'new': 'present'}
    action = 'created' if created else ('restored' if restoring else 'updated')
    stats[action] += 1
    _event(db, row, action, now, delta, [c for c in changed if c not in ('extracted_text', 'extracted_at')], context)


def _audit(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _reconcile(db, course: StudyCourse, snap: CourseSnapshot, now, stats):
    seen = {f.external_id for f in snap.files}
    rows = (db.query(StudyMaterial)
            .filter(StudyMaterial.course_id == course.id, StudyMaterial.source_missing_at.is_(None))
            .order_by(StudyMaterial.id).all())
    for row in rows:
        if row.external_id in seen or row.module_external_id in snap.uncertain_modules:
            continue
        row.source_missing_at = row.updated_at = now
        db.flush()
        stats['missing'] += 1
        _event(db, row, 'source_missing', now, {'source': {'old': 'present', 'new': 'missing'}}, ['source_missing_at'])


def _new_stats() -> dict:
    keys = ('courses', 'courses_failed', 'courses_incomplete', 'created', 'updated', 'unchanged', 'missing', 'restored',
            'downloaded', 'errors', 'duplicates', 'file_stored', 'file_metadata_only', 'file_too_large',
            'file_unsupported', 'file_rejected', 'file_failed')
    return dict.fromkeys(keys, 0)


def _remote_courses(raw_courses, stats) -> list[tuple[str, str, str | None]]:
    out, seen = [], set()
    allow = _course_filter()
    for raw in raw_courses:
        cid = _int(raw.get('id')) if isinstance(raw, dict) else None
        name = _text(raw.get('fullname'), 300) if isinstance(raw, dict) else None
        if cid is None or cid <= 0 or name is None:
            stats['errors'] += 1
            continue
        external = str(cid)
        if external in seen or (allow is not None and external not in allow):
            continue
        seen.add(external)
        out.append((external, name, _text(raw.get('shortname'), 100)))
    return out


def sync_materials(db, *, client=None, now=None) -> dict:
    """Owns its transactions: commits per course, rolls back a failed course entirely. Raises MoodleSyncError only
    when nothing could be synced (not configured, course discovery failed)."""
    if client is None:
        config = load_config()
        if config is None:
            raise MoodleSyncError('not_configured')
        client, limit = MoodleWsClient(config), config.max_file_bytes
    else:
        limit = max_file_bytes()
    now = now or utc_now()
    stats = _new_stats()
    raw_courses, failure = None, None
    try:
        raw_courses = client.courses()
    except MoodleSyncError as error:
        failure = error.category
    except Exception:  # noqa: BLE001
        failure = 'unavailable'
    if failure is not None:
        raise MoodleSyncError(failure)  # outside the except block: no chained upstream exception
    if not isinstance(raw_courses, list):
        raise MoodleSyncError('response_invalid')
    for external_id, name, short_name in _remote_courses(raw_courses, stats):
        try:
            sections = client.course_contents(external_id)
            snap = parse_course_contents(sections)
        except Exception:  # noqa: BLE001 - failed course: nothing written, nothing hidden
            stats['courses_failed'] += 1
            continue
        try:
            _sync_course(db, external_id, name, short_name, snap, client, limit, now, stats)
            db.commit()
            stats['courses'] += 1
        except Exception:  # noqa: BLE001 - roll the whole course back; the next sync retries it
            db.rollback()
            stats['courses_failed'] += 1
    return stats


def _sync_course(db, external_id, name, short_name, snap, client, limit, now, stats, *, source='moodle',
                 context='moodle_sync'):
    """Shared core for one course snapshot (Web Services sync and ZIP import alike). Reconciles presence only for
    a complete snapshot; an incomplete one adds/updates and never marks anything missing."""
    course = _course_row(db, external_id, name, short_name, now, source=source, context=context)
    if (course.name, course.short_name) != (name, short_name):
        delta = {'name': {'old': course.name, 'new': name}} if course.name != name else {}
        course.name, course.short_name, course.updated_at = name, short_name, now
        db.flush()
        log_activity(db, 'school', 'update', f'Moodle kurz přejmenován: {name}', entity_type='study_course',
                     entity_id=course.id, delta=delta or None, user_context=context)
    stats['errors'] += snap.errors
    stats['duplicates'] += snap.duplicates
    for remote in snap.files:
        _apply_file(db, course, remote, client, limit, now, stats, context)
    if snap.complete:
        _reconcile(db, course, snap, now, stats)
    else:
        stats['courses_incomplete'] += 1
    return course


# ---------- read model & manual mapping ----------

def _fold(value: str | None) -> str:
    decomposed = unicodedata.normalize('NFKD', value or '')
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _alnum(value: str) -> str:
    return re.sub(r'[^0-9a-z]', '', _fold(value))


def suggest_subject_id(course: StudyCourse, subjects) -> int | None:
    """Safe deterministic suggestion only: exactly one subject whose code (≥ 3 chars) equals a whole token of the
    course short/full name. Never by name similarity, never applied automatically."""
    tokens = {_alnum(t) for t in re.split(r'[\s()\[\],;:/|]+', f'{course.short_name or ""} {course.name}')} - {''}
    matches = {s.id for s in subjects
               if s.active is not False and s.code and len(_alnum(s.code)) >= 3 and _alnum(s.code) in tokens}  # MRK-75: not archived
    return next(iter(matches)) if len(matches) == 1 else None


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def has_file(row: StudyMaterial) -> bool:
    return row.download_status == 'stored' and storage.exists(row.stored_name)


def material_dict(row: StudyMaterial, course: StudyCourse | None, subjects: dict) -> dict:
    """Page/API shape: no upstream URL, token, identity internals or extracted text."""
    subject = subjects.get(course.subject_id) if course is not None and course.subject_id else None
    return {
        'id': row.id, 'title': row.title, 'file_name': row.file_name, 'material_type': row.material_type,
        'mime_type': row.mime_type, 'size_bytes': row.size_bytes, 'section_name': row.section_name,
        'source_modified_at': _iso(row.source_modified_at), 'created_at': _iso(row.created_at),
        'updated_at': _iso(row.updated_at), 'source_missing_at': _iso(row.source_missing_at),
        'state': 'source_missing' if row.source_missing_at else 'active',
        'download_status': row.download_status, 'has_file': has_file(row),
        'extraction_status': row.extraction_status,
        'course': {'id': course.id, 'name': course.name} if course is not None else None,
        'subject': {'id': subject.id, 'name': subject.name} if subject is not None else None,
    }


def course_dict(course: StudyCourse, subjects: dict, counts: dict) -> dict:
    subject = subjects.get(course.subject_id) if course.subject_id else None
    suggestion = None if subject is not None else suggest_subject_id(course, subjects.values())
    return {'id': course.id, 'name': course.name, 'short_name': course.short_name,
            'subject': {'id': subject.id, 'name': subject.name} if subject is not None else None,
            'suggested_subject_id': suggestion, 'materials': counts.get(course.id, 0)}


def list_materials(db, *, subject_id=None, course_id=None, material_type=None, state='active') -> dict:
    subjects = {s.id: s for s in db.query(Subject).order_by(Subject.name).all()}
    courses = {c.id: c for c in db.query(StudyCourse).order_by(StudyCourse.name, StudyCourse.id).all()}
    query = db.query(StudyMaterial)
    if state == 'active':
        query = query.filter(StudyMaterial.source_missing_at.is_(None))
    elif state == 'missing':
        query = query.filter(StudyMaterial.source_missing_at.isnot(None))
    if course_id is not None:
        query = query.filter(StudyMaterial.course_id == course_id)
    if subject_id is not None:
        query = query.filter(StudyMaterial.course_id.in_([c.id for c in courses.values() if c.subject_id == subject_id]))
    if material_type is not None:
        query = query.filter(StudyMaterial.material_type == material_type)
    rows = query.order_by(StudyMaterial.source_modified_at.desc().nullslast(), StudyMaterial.id.desc()).limit(LIST_LIMIT + 1).all()
    counts: dict[int, int] = {}
    for cid, in db.query(StudyMaterial.course_id).filter(StudyMaterial.source_missing_at.is_(None)).all():
        counts[cid] = counts.get(cid, 0) + 1
    return {
        'configured': load_config() is not None,
        'materials': [material_dict(r, courses.get(r.course_id), subjects) for r in rows[:LIST_LIMIT]],
        'truncated': len(rows) > LIST_LIMIT,
        'courses': [course_dict(c, subjects, counts) for c in courses.values()],
        'subjects': [{'id': s.id, 'name': s.name, 'active': s.active is not False} for s in subjects.values()],
    }


def get_material(db, material_id: int) -> dict:
    row = db.get(StudyMaterial, material_id)
    if row is None:
        raise MaterialError('not_found', 404)
    subjects = {s.id: s for s in db.query(Subject).all()}
    out = material_dict(row, db.get(StudyCourse, row.course_id), subjects)
    text = row.extracted_text or ''
    out.update(checksum=row.checksum, stored_size=row.stored_size, extracted_at=_iso(row.extracted_at),
               extracted_chars=len(text), text_excerpt=text[:EXCERPT_CHARS] or None)
    return out


def safe_download_name(row: StudyMaterial) -> str:
    """Display name for Content-Disposition: no path, no control characters, extension matches the stored type."""
    base = re.split(r'[\\/]', row.file_name or '')[-1]
    base = ''.join(ch for ch in base if ch.isprintable() and ch not in '"<>:|?*').strip(' .')[:200] or f'material-{row.id}'
    ext = '.' + row.material_type
    return base if base.lower().endswith(ext) else base + ext


def material_file(db, material_id: int):
    """(path, media type, download name) of the stored binary; only server-generated content-addressed names."""
    row = db.get(StudyMaterial, material_id)
    if row is None:
        raise MaterialError('not_found', 404)
    if not has_file(row) or row.material_type not in storage.CONTENT_TYPES:
        raise MaterialError('file_not_stored', 404)
    return storage.path_for(row.stored_name), storage.CONTENT_TYPES[row.material_type], safe_download_name(row)


def set_course_subject(db, course_id: int, subject_id: int | None, *, now=None) -> dict:
    """Manual course → subject mapping (the only way a course gets a subject). Subjects are never modified."""
    course = db.get(StudyCourse, course_id)
    if course is None:
        raise MaterialError('course_not_found', 404)
    subject = None
    if subject_id is not None:
        subject = db.get(Subject, subject_id)
        if subject is None:
            raise MaterialError('subject_not_found', 404)
        if subject.active is False and course.subject_id != subject_id:  # MRK-75: keep an existing mapping, no new ones
            raise MaterialError('subject_archived', 409)
    if course.subject_id != subject_id:
        old = course.subject_id
        course.subject_id, course.updated_at = subject_id, now or utc_now()
        db.flush()
        summary = (f'Moodle kurz {course.name} přiřazen k předmětu {subject.name}' if subject is not None
                   else f'Moodle kurz {course.name} bez předmětu')
        log_activity(db, 'school', 'update', summary, entity_type='study_course', entity_id=course.id,
                     delta={'subject_id': {'old': old, 'new': subject_id}}, user_context='manual')
    subjects = {s.id: s for s in db.query(Subject).all()}
    count = db.query(StudyMaterial).filter_by(course_id=course.id, source_missing_at=None).count()
    return course_dict(course, subjects, {course.id: count})
