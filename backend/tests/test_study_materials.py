"""MRK-42 study materials: synthetic Moodle Web Services responses only – no real Moodle, token, network or LLM."""
import copy
import io
import json
import logging
import traceback
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from module_registry import ModuleAccess
from modules.school import extract, integrations, service, storage
from modules.school.models import StudyCourse, StudyMaterial
from modules.school.moodle import MoodleConfig, MoodleSyncError, MoodleWsClient, _NoRedirect
from module_contracts import ContextRequest

NOW = datetime(2026, 10, 9, 8, 0)
LATER = datetime(2026, 10, 10, 8, 0)
TOKEN = 'TOKEN-CANARY-5f1e2d'
SIGNED = 'SIGNED-CANARY-9a8b7c'
BASE = 'https://moodle.example.invalid'
CANARIES = (TOKEN, SIGNED, 'moodle.example.invalid', 'pluginfile.php')


# ---------- synthetic documents ----------

def make_pdf(text='Synthetic PDF lecture about photosynthesis'):
    stream = f'BT /F1 12 Tf 72 712 Td ({text}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
               b'/Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = io.BytesIO(), []
    out.write(b'%PDF-1.4\n')
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for offset in offsets:
        out.write(b'%010d 00000 n \n' % offset)
    out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref))
    return out.getvalue()


def _zip(parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for name, body in parts.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def make_pptx(*slides):
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    parts = {'ppt/presentation.xml': '<p/>'}
    for i, text in enumerate(slides, 1):
        parts[f'ppt/slides/slide{i}.xml'] = f'<sld {ns}><a:t>{text}</a:t></sld>'
    return _zip(parts)


def make_docx(*paragraphs):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    return _zip({'word/document.xml': f'<w:document {ns}><w:body>{body}</w:body></w:document>'})


def url(name):
    return f'{BASE}/webservice/pluginfile.php/7/mod_resource/content/1/{name}?forcedownload=1&token={SIGNED}'


def file_entry(name, data, modified=1760000000, size=None):
    return {'type': 'file', 'filename': name, 'filepath': '/', 'filesize': len(data) if size is None else size,
            'fileurl': url(name), 'timemodified': modified, 'mimetype': 'application/octet-stream'}


class FakeMoodle:
    """Same surface as MoodleWsClient; `files` keyed by the returned (signed) file URL."""

    def __init__(self):
        self.pdf, self.pptx = make_pdf(), make_pptx('Slide one: cell biology', 'Slide two: mitochondria')
        self.docx, self.txt = make_docx('Seminar notes', 'Enzyme kinetics'), 'Plain synthetic reading list'.encode()
        self.files = {url('lecture.pdf'): self.pdf, url('slides.pptx'): self.pptx, url('notes.docx'): self.docx,
                      url('reading.txt'): self.txt, url('copy.pdf'): self.pdf, url('photo.png'): b'\x89PNG....',
                      url('huge.pdf'): b'%PDF-' + b'0' * 10}
        self.courses_list = [{'id': 101, 'fullname': 'Biology I (BIO101)', 'shortname': 'BIO101'}]
        self.contents = {'101': [
            {'id': 1, 'name': 'Week 1', 'modules': [
                {'id': 11, 'modname': 'resource', 'name': 'Lecture 1', 'contents': [file_entry('lecture.pdf', self.pdf)]},
                {'id': 12, 'modname': 'resource', 'name': 'Slides 1', 'contents': [file_entry('slides.pptx', self.pptx)]},
                {'id': 13, 'modname': 'quiz', 'name': 'Quiz 1'},
                {'id': 14, 'modname': 'forum', 'name': 'News'},
            ]},
            {'id': 2, 'name': 'Week 2', 'modules': [
                {'id': 21, 'modname': 'folder', 'name': 'Seminar', 'contents': [
                    file_entry('notes.docx', self.docx), file_entry('reading.txt', self.txt),
                    file_entry('photo.png', b'\x89PNG....'), file_entry('notes.docx', self.docx)]},  # duplicate entry
                {'id': 22, 'modname': 'resource', 'name': 'Copy of lecture', 'contents': [file_entry('copy.pdf', self.pdf)]},
                {'id': 23, 'modname': 'resource', 'name': 'Huge scan',
                 'contents': [file_entry('huge.pdf', b'', size=50 * 1024 * 1024)]},
            ]},
        ]}
        self.downloads = []
        self.fail_courses, self.fail_contents = False, set()

    def courses(self):
        if self.fail_courses:
            raise MoodleSyncError('unavailable')
        return copy.deepcopy(self.courses_list)

    def course_contents(self, course_id):
        if course_id in self.fail_contents:
            raise RuntimeError(f'boom {TOKEN} {url("x")}')
        return copy.deepcopy(self.contents[course_id])

    def download(self, file_url, max_bytes):
        self.downloads.append(file_url)
        data = self.files[file_url]
        if isinstance(data, Exception):
            raise data
        if len(data) > max_bytes:
            raise MoodleSyncError('file_too_large')
        return data

    def module(self, cmid):
        return next(m for s in self.contents['101'] for m in s['modules'] if m['id'] == cmid)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setenv('MOODLE_MAX_FILE_MB', '5')
    monkeypatch.delenv('MOODLE_WS_BASE_URL', raising=False)
    monkeypatch.delenv('MOODLE_WS_TOKEN', raising=False)
    monkeypatch.delenv('MOODLE_COURSE_IDS', raising=False)
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def moodle():
    return FakeMoodle()


def by_file(db):
    return {m.file_name: m for m in db.query(StudyMaterial).all()}


def facts(db):
    return [e.event_type for e in db.query(models.DomainEvent).order_by(models.DomainEvent.id)]


def assert_no_canary(*texts):
    blob = '\n'.join(str(t) for t in texts)
    for canary in CANARIES:
        assert canary not in blob, canary


def everything_persisted(db):
    rows = []
    for table in ('study_courses', 'study_materials', 'activity_logs', 'domain_events'):
        rows += [tuple(r) for r in db.execute(Base.metadata.tables[table].select()).all()]
    return rows


# ---------- sync ----------

def test_first_sync_discovers_stores_extracts_and_audits(db, moodle, tmp_path):
    stats = service.sync_materials(db, client=moodle, now=NOW)
    files = by_file(db)
    assert set(files) == {'lecture.pdf', 'slides.pptx', 'notes.docx', 'reading.txt', 'photo.png', 'copy.pdf', 'huge.pdf'}
    assert stats['created'] == 7 and stats['duplicates'] == 1 and stats['courses'] == 1 and stats['courses_failed'] == 0
    assert {f.material_type for f in files.values()} == {'pdf', 'pptx', 'docx', 'txt', 'other'}
    lecture = files['lecture.pdf']
    assert lecture.title == 'Lecture 1' and lecture.section_name == 'Week 1' and lecture.download_status == 'stored'
    assert lecture.extraction_status == 'ok' and 'photosynthesis' in lecture.extracted_text
    assert 'mitochondria' in files['slides.pptx'].extracted_text
    assert 'Enzyme kinetics' in files['notes.docx'].extracted_text
    assert files['reading.txt'].extracted_text == 'Plain synthetic reading list'
    assert files['notes.docx'].title == 'Seminar – notes.docx'
    assert files['photo.png'].download_status == 'unsupported' and files['photo.png'].stored_name is None
    assert files['huge.pdf'].download_status == 'too_large' and files['huge.pdf'].stored_name is None
    # quizzes / forums are never touched; the oversized and unsupported files are never downloaded
    assert not any(name in u for u in moodle.downloads for name in ('huge.pdf', 'photo.png'))
    # identical binaries are stored once (content-addressed)
    assert files['copy.pdf'].stored_name == lecture.stored_name
    stored = list((tmp_path / 'media' / 'study-materials').iterdir())
    assert len(stored) == 4 and all(storage.STORED_NAME_RE.fullmatch(p.name) for p in stored)
    assert facts(db).count('school.material.created') == 7
    assert db.query(models.ActivityLog).filter_by(entity_type='study_material').count() == 7
    assert db.query(models.ActivityLog).filter_by(entity_type='study_course', action_type='create').count() == 1
    payloads = [json.dumps(e.payload) for e in db.query(models.DomainEvent)]
    assert not any('photosynthesis' in p or 'Lecture 1' in p for p in payloads), 'payload carries ids/states only'
    assert_no_canary(everything_persisted(db))


def test_resync_unchanged_writes_and_downloads_nothing(db, moodle):
    service.sync_materials(db, client=moodle, now=NOW)
    before = (len(facts(db)), db.query(models.ActivityLog).count(), len(moodle.downloads))
    stamps = {m.id: m.updated_at for m in db.query(StudyMaterial)}
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['unchanged'] == 7 and stats['created'] == stats['updated'] == stats['missing'] == 0
    assert (len(facts(db)), db.query(models.ActivityLog).count(), len(moodle.downloads)) == before
    assert {m.id: m.updated_at for m in db.query(StudyMaterial)} == stamps


def test_updated_file_keeps_identity_and_redownloads(db, moodle):
    service.sync_materials(db, client=moodle, now=NOW)
    old = by_file(db)['lecture.pdf']
    old_id, old_checksum = old.id, old.checksum
    new_pdf = make_pdf('Revised lecture about chloroplasts')
    moodle.files[url('lecture.pdf')] = new_pdf
    moodle.module(11)['contents'] = [file_entry('lecture.pdf', new_pdf, modified=1760100000)]
    moodle.module(11)['name'] = 'Lecture 1 (revised)'
    stats = service.sync_materials(db, client=moodle, now=LATER)
    row = by_file(db)['lecture.pdf']
    assert stats['updated'] == 1 and stats['unchanged'] == 6 and row.id == old_id
    assert row.checksum != old_checksum and 'chloroplasts' in row.extracted_text and row.title == 'Lecture 1 (revised)'
    assert facts(db).count('school.material.updated') == 1
    activity = db.query(models.ActivityLog).filter_by(entity_type='study_material', action_type='update').one()
    assert 'checksum' in activity.delta_json and 'title' in activity.delta_json
    # the other copy of the old content still points at the old binary (history kept, nothing deleted)
    assert storage.exists(by_file(db)['copy.pdf'].stored_name)


def test_missing_from_complete_snapshot_then_restored_same_row(db, moodle):
    service.sync_materials(db, client=moodle, now=NOW)
    slides_id = by_file(db)['slides.pptx'].id
    removed = moodle.contents['101'][0]['modules'].pop(1)
    stats = service.sync_materials(db, client=moodle, now=LATER)
    slides = by_file(db)['slides.pptx']
    assert stats['missing'] == 1 and slides.source_missing_at == LATER and slides.stored_name is not None
    assert db.query(StudyMaterial).count() == 7, 'never deleted'
    assert service.list_materials(db)['materials'] and all(m['id'] != slides_id for m in service.list_materials(db)['materials'])
    assert any(m['id'] == slides_id for m in service.list_materials(db, state='missing')['materials'])
    moodle.contents['101'][0]['modules'].insert(1, removed)
    stats = service.sync_materials(db, client=moodle, now=LATER.replace(hour=9))
    assert stats['restored'] == 1 and by_file(db)['slides.pptx'].id == slides_id
    assert by_file(db)['slides.pptx'].source_missing_at is None
    assert facts(db)[-2:] == ['school.material.source_missing', 'school.material.restored']


def test_failed_or_incomplete_sync_never_mass_hides(db, moodle, caplog):
    service.sync_materials(db, client=moodle, now=NOW)
    events = len(facts(db))
    # 1) course discovery fails → nothing synced, nothing hidden, secret-free category
    moodle.fail_courses = True
    with pytest.raises(MoodleSyncError, match='unavailable'):
        service.sync_materials(db, client=moodle, now=LATER)
    moodle.fail_courses = False
    # 2) one course's contents fail → that course is skipped entirely
    moodle.fail_contents = {'101'}
    with caplog.at_level(logging.DEBUG):
        stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['courses_failed'] == 1 and stats['missing'] == 0
    moodle.fail_contents = set()
    # 3) malformed module id → snapshot incomplete → no reconciliation at all
    moodle.contents['101'][0]['modules'] = [{'id': 'broken', 'modname': 'resource'}]
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['courses_incomplete'] == 1 and stats['missing'] == 0 and stats['errors'] >= 1
    # 4) a module whose contents are malformed keeps its materials (uncertain), others still reconcile
    moodle.contents = FakeMoodle().contents
    moodle.module(12)['contents'] = 'not-a-list'
    moodle.module(22)['contents'] = []  # really emptied → its file is missing
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['missing'] == 1 and by_file(db)['slides.pptx'].source_missing_at is None
    assert by_file(db)['copy.pdf'].source_missing_at == LATER
    assert all(m.source_missing_at is None for n, m in by_file(db).items() if n != 'copy.pdf')
    assert len(facts(db)) == events + 1
    assert_no_canary(caplog.text, everything_persisted(db))


def test_error_inside_a_course_rolls_back_only_that_course(db, moodle):
    moodle.courses_list.append({'id': 202, 'fullname': 'Chemistry', 'shortname': 'CHE'})
    moodle.contents['202'] = [{'id': 3, 'name': 'Intro', 'modules': [
        {'id': 31, 'modname': 'resource', 'name': 'Chem notes', 'contents': [file_entry('reading.txt', moodle.txt)]}]}]
    real = service.append_domain_event

    def flaky(db_, **kwargs):
        if kwargs['payload']['course_id'] == 2:
            raise RuntimeError('intentional failure')
        return real(db_, **kwargs)
    with patch.object(service, 'append_domain_event', side_effect=flaky):
        stats = service.sync_materials(db, client=moodle, now=NOW)
    assert stats['courses'] == 1 and stats['courses_failed'] == 1
    assert db.query(StudyMaterial).filter_by(course_id=2).count() == 0
    assert db.query(StudyCourse).filter_by(external_id='202').count() == 0, 'course row rolled back with it'
    assert db.query(StudyMaterial).filter_by(course_id=1).count() == 7
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['courses'] == 2 and db.query(StudyMaterial).count() == 8


def test_download_policy_rejects_disguised_and_error_bodies(db, moodle):
    moodle.files[url('lecture.pdf')] = b'MZ\x90\x00 executable pretending to be a pdf'
    moodle.files[url('notes.docx')] = b'PK\x03\x04 not really a zip'
    moodle.files[url('reading.txt')] = json.dumps({'error': 'x', 'errorcode': 'nopermission'}).encode()
    moodle.files[url('slides.pptx')] = MoodleSyncError('file_unavailable')
    service.sync_materials(db, client=moodle, now=NOW)
    files = by_file(db)
    assert files['lecture.pdf'].download_status == 'rejected' and files['lecture.pdf'].stored_name is None
    assert files['notes.docx'].download_status == 'rejected'
    assert files['reading.txt'].download_status == 'failed' and files['reading.txt'].stored_name is None
    assert files['slides.pptx'].download_status == 'failed'
    # transient failures are retried; a deterministic rejection of the same version is not
    moodle.files[url('reading.txt')] = moodle.txt
    moodle.files[url('slides.pptx')] = moodle.pptx
    moodle.downloads.clear()
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['updated'] == 2 and by_file(db)['reading.txt'].download_status == 'stored'
    assert not any('lecture.pdf' in u for u in moodle.downloads)


def test_extraction_failure_keeps_binary(db, moodle):
    broken = b'%PDF-1.4\n garbage without objects'
    moodle.files[url('lecture.pdf')] = broken
    moodle.module(11)['contents'] = [file_entry('lecture.pdf', broken)]
    with patch.object(extract, '_pdf', side_effect=RuntimeError('parser crash')):
        service.sync_materials(db, client=moodle, now=NOW)
    row = by_file(db)['lecture.pdf']
    assert row.download_status == 'stored' and row.extraction_status == 'failed' and row.extracted_text is None
    assert storage.read(row.stored_name) == broken


def test_extractors_are_bounded_and_refuse_entities():
    evil = _zip({'word/document.xml': '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document xmlns:w="w">&a;</w:document>'})
    assert extract.extract_text(evil, 'docx').status == 'failed'
    assert extract.extract_text(b'', 'txt').status == 'empty'
    assert extract.extract_text(b'x', 'other').status == 'unsupported'
    big = ('word ' * (extract.MAX_TEXT_CHARS // 4)).encode()
    result = extract.extract_text(big, 'txt')
    assert result.status == 'truncated' and len(result.text) == extract.MAX_TEXT_CHARS


def test_storage_never_leaves_its_folder(db):
    for name in ('../etc/passwd', 'a' * 64 + '.exe', '/abs.pdf', 'a' * 64 + '.pdf/../x'):
        with pytest.raises(storage.StorageError):
            storage.path_for(name)
    assert storage.sniff(make_pdf(), 'pdf') and not storage.sniff(make_pdf(), 'docx')
    assert storage.sniff(make_pptx('x'), 'pptx') and not storage.sniff(make_pptx('x'), 'docx')


def test_course_filter_env(db, moodle, monkeypatch):
    moodle.courses_list.append({'id': 202, 'fullname': 'Chemistry', 'shortname': 'CHE'})
    moodle.courses_list.append({'id': None, 'fullname': 'Malformed'})
    monkeypatch.setenv('MOODLE_COURSE_IDS', '101')
    stats = service.sync_materials(db, client=moodle, now=NOW)
    assert stats['courses'] == 1 and stats['errors'] >= 1
    assert [c.external_id for c in db.query(StudyCourse)] == ['101']


# ---------- mapping ----------

def test_manual_mapping_and_safe_suggestion(db, moodle):
    bio = models.Subject(name='Biologie', code='BIO101')
    other = models.Subject(name='Biology I', code='')  # same name, no code → never matched by name
    db.add_all([bio, other])
    db.commit()
    service.sync_materials(db, client=moodle, now=NOW)
    course = db.query(StudyCourse).one()
    assert course.subject_id is None, 'sync never maps'
    listing = service.list_materials(db)
    assert listing['courses'][0]['suggested_subject_id'] == bio.id and listing['courses'][0]['subject'] is None
    assert service.list_materials(db, subject_id=bio.id)['materials'] == []
    result = service.set_course_subject(db, course.id, bio.id)
    db.commit()
    assert result['subject'] == {'id': bio.id, 'name': 'Biologie'}
    assert len(service.list_materials(db, subject_id=bio.id)['materials']) == 7
    assert db.query(models.ActivityLog).filter_by(entity_type='study_course', action_type='update').count() == 1
    # renamed upstream course keeps the manual mapping; subjects are never modified
    moodle.courses_list[0]['fullname'] = 'Biology I – renamed'
    service.sync_materials(db, client=moodle, now=LATER)
    db.refresh(course)
    assert course.subject_id == bio.id and course.name == 'Biology I – renamed'
    assert (bio.name, bio.code, other.name) == ('Biologie', 'BIO101', 'Biology I')
    with pytest.raises(service.MaterialError):
        service.set_course_subject(db, course.id, 9999)
    # ambiguous code → no suggestion
    db.add(models.Subject(name='Dup', code='BIO101'))
    db.commit()
    service.set_course_subject(db, course.id, None)
    db.commit()
    assert service.list_materials(db)['courses'][0]['suggested_subject_id'] is None


# ---------- contributions ----------

def test_search_context_changes_and_module_gate(db, moodle):
    from change_feed import build
    from context_service import build_current_context
    from search_service import search
    service.sync_materials(db, client=moodle, now=NOW)
    on, off = ModuleAccess({}), ModuleAccess({'school': False})
    hits = search(db, 'mitochondria', access=on)['results']
    assert any(h['type'] == 'study_material' and h['href'].startswith('/school/materials?material=') for h in hits)
    assert not any(h['type'] == 'study_material' for h in search(db, 'mitochondria', access=off)['results'])
    lines = integrations.context_materials(ContextRequest(db, NOW.date(), NOW))
    text = ' '.join(lines)
    assert 'Lecture 1' in text and 'photosynthesis' not in text and 'mitochondria' not in text
    context = build_current_context(db, 'jaké mám studijní materiály z moodlu?', now_utc=NOW, access=on)
    assert 'Studijní materiály' in str(context)
    assert 'Studijní materiály' not in str(build_current_context(db, 'jaké mám studijní materiály?', now_utc=NOW, access=off))
    feed = build(db, on, since=NOW.replace(hour=0), modules=None, limit=100)
    items = [i for i in feed['items'] if i.get('entity_type') == 'study_material']
    assert len(items) == 7 and all(i['href'].startswith('/school/materials?material=') for i in items)
    assert_no_canary(hits, lines, feed)
    for kind in ('search', 'context', 'changes', 'routers'):
        assert not any(owner == 'school' for owner, _ in off.contributions(kind))


# ---------- API ----------

@pytest.fixture
def api(db, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(main, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
        yield client
    client.close()


def test_api_list_detail_file_and_canaries(db, moodle, api, monkeypatch, caplog):
    assert api.post('/school/materials/sync').json() == {'detail': {'category': 'not_configured'}}
    monkeypatch.setenv('MOODLE_WS_BASE_URL', BASE)
    monkeypatch.setenv('MOODLE_WS_TOKEN', TOKEN)
    with patch.object(service, 'MoodleWsClient', return_value=moodle), caplog.at_level(logging.DEBUG):
        synced = api.post('/school/materials/sync')
    assert synced.status_code == 200 and synced.json()['created'] == 7
    listing = api.get('/school/materials')
    body = listing.json()
    assert body['configured'] is True and len(body['materials']) == 7
    assert {m['state'] for m in body['materials']} == {'active'}
    assert [m['file_name'] for m in api.get('/school/materials?type=pptx').json()['materials']] == ['slides.pptx']
    assert api.get('/school/materials?type=exe').status_code == 422
    lecture = next(m for m in body['materials'] if m['file_name'] == 'lecture.pdf')
    assert lecture['has_file'] is True and 'stored_name' not in lecture and 'extracted_text' not in lecture
    detail = api.get(f"/school/materials/{lecture['id']}")
    assert detail.status_code == 200 and 'photosynthesis' in detail.json()['text_excerpt']
    file = api.get(f"/school/materials/{lecture['id']}/file")
    assert file.status_code == 200 and file.content.startswith(b'%PDF-')
    assert file.headers['content-type'] == 'application/pdf' and file.headers['x-content-type-options'] == 'nosniff'
    assert file.headers['content-disposition'].startswith('attachment')
    photo = next(m for m in body['materials'] if m['file_name'] == 'photo.png')
    assert api.get(f"/school/materials/{photo['id']}/file").status_code == 404
    assert api.get('/school/materials/9999').status_code == 404
    # a tampered stored name can never escape the storage folder
    row = db.get(StudyMaterial, lecture['id'])
    row.stored_name = '../../../etc/passwd'
    db.commit()
    assert api.get(f"/school/materials/{lecture['id']}/file").status_code == 404
    course = body['courses'][0]
    assert api.put(f"/school/materials/courses/{course['id']}", json={'subject_id': 4242}).status_code == 404
    # upstream failure text never reaches the client
    failing = FakeMoodle()
    failing.fail_courses = True
    with patch.object(service, 'MoodleWsClient', return_value=failing):
        error = api.post('/school/materials/sync')
    assert error.status_code == 503 and error.json() == {'detail': {'category': 'unavailable'}}
    changes, activity = api.get('/changes?since=2026-10-01T00:00:00Z'), api.get('/activity')
    assert changes.status_code == 200 and 'Nový studijní materiál' in changes.text
    assert activity.status_code == 200
    responses = [listing.text, detail.text, synced.text, error.text, changes.text, activity.text]
    assert_no_canary(*responses, caplog.text, everything_persisted(db))


def test_api_requires_auth_and_enabled_school(db, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    try:
        with patch.object(main, 'auth_enabled', return_value=True), patch.object(main, 'validate_session_token', return_value=None):
            assert client.get('/school/materials').status_code == 401
            assert client.post('/school/materials/sync').status_code == 401
        with patch.object(main, 'auth_enabled', return_value=False), \
                patch.object(main, 'current_access', return_value=ModuleAccess({'school': False})):
            assert client.get('/school/materials').status_code == 404
            assert client.get('/school/materials/1/file').status_code == 404
    finally:
        client.close()


# ---------- WS client (fake transport, no sockets) ----------

class FakeResponse:
    def __init__(self, data):
        self.data = data

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


def config():
    return MoodleConfig(BASE, TOKEN, 1024)


def _rendered(error):
    return str(error) + ''.join(traceback.format_exception(error))


def test_ws_client_keeps_token_in_body_and_errors_secret_free():
    opener = FakeOpener(json.dumps({'userid': 5}).encode(), json.dumps([{'id': 101, 'fullname': 'Bio'}]).encode())
    client = MoodleWsClient(config(), opener=opener)
    assert client.courses() == [{'id': 101, 'fullname': 'Bio'}]
    for request in opener.requests:
        assert TOKEN not in request.full_url and request.get_method() == 'POST'
        assert TOKEN in request.data.decode() and not any(TOKEN in str(v) for v in request.header_items())
    assert 'wsfunction=core_enrol_get_users_courses' in opener.requests[1].data.decode()

    bad = MoodleWsClient(config(), opener=FakeOpener(json.dumps(
        {'exception': 'moodle_exception', 'errorcode': 'invalidtoken', 'message': f'Invalid token {TOKEN}'}).encode()))
    with pytest.raises(MoodleSyncError) as caught:
        bad.course_contents('101')
    assert caught.value.category == 'auth_failed'
    assert_no_canary(_rendered(caught.value))

    transport = MoodleWsClient(config(), opener=FakeOpener(OSError(f'connection to {BASE}?wstoken={TOKEN} failed')))
    with pytest.raises(MoodleSyncError) as caught:
        transport.course_contents('101')
    assert caught.value.category == 'unavailable'
    assert_no_canary(_rendered(caught.value))

    for answer, category in ((b'<html>login</html>', 'response_invalid'), (b'{"a": 1}', 'response_invalid'),
                             (b'[' + b'0,' * 3_000_000 + b'0]', 'response_too_large')):
        with pytest.raises(MoodleSyncError, match=category):
            MoodleWsClient(config(), opener=FakeOpener(answer)).course_contents('101')


def test_ws_client_download_origin_path_and_size():
    opener = FakeOpener(b'%PDF-1.4 ok', b'x' * 2000)
    client = MoodleWsClient(config(), opener=opener)
    assert client.download(url('lecture.pdf'), 1024) == b'%PDF-1.4 ok'
    sent = opener.requests[0]
    assert sent.full_url == f'{BASE}/webservice/pluginfile.php/7/mod_resource/content/1/lecture.pdf'
    assert SIGNED not in sent.full_url and TOKEN in sent.data.decode()
    with pytest.raises(MoodleSyncError, match='file_too_large'):
        client.download(url('big.pdf'), 1024)
    for foreign in ('https://evil.example.invalid/webservice/pluginfile.php/1/a.pdf',
                    'http://moodle.example.invalid/webservice/pluginfile.php/1/a.pdf',
                    f'{BASE}/pluginfile.php/1/a.pdf', f'{BASE}/webservice/pluginfile.php/../../login/index.php',
                    f'https://user:pw@moodle.example.invalid/webservice/pluginfile.php/1/a.pdf', None):
        with pytest.raises(MoodleSyncError, match='file_url_rejected'):
            client.download(foreign, 1024)
    assert len(opener.requests) == 2, 'rejected URLs are never requested'
    with pytest.raises(MoodleSyncError, match='redirect_rejected'):
        _NoRedirect().redirect_request(None, None, 302, 'Found', {}, f'{BASE}/login?token={TOKEN}')
    for base in ('http://moodle.example.invalid', f'{BASE}?token={TOKEN}', 'https://u:p@moodle.example.invalid'):
        with pytest.raises(MoodleSyncError, match='invalid_configuration') as caught:
            MoodleWsClient(MoodleConfig(base, TOKEN, 1024), opener=FakeOpener())
        assert_no_canary(_rendered(caught.value))


def test_parse_contents_rejects_non_list_and_path_like_names():
    with pytest.raises(MoodleSyncError):
        service.parse_course_contents({'not': 'a list'})
    snap = service.parse_course_contents([{'name': 'S', 'modules': [
        {'id': 5, 'modname': 'resource', 'name': 'Bad', 'contents': [
            {'type': 'file', 'filename': '../../evil.pdf', 'filepath': '/', 'filesize': 1, 'fileurl': url('e')}]},
        {'id': 6, 'modname': 'resource', 'name': 'Neg', 'contents': [
            {'type': 'file', 'filename': 'n.pdf', 'filepath': '/', 'filesize': -4, 'fileurl': url('n')}]},
        {'id': 7, 'modname': 'resource', 'name': 'Hidden', 'uservisible': False, 'contents': []},
        {'id': 8, 'modname': 'url', 'name': 'Link', 'contents': [{'type': 'url', 'fileurl': 'https://x.invalid'}]},
    ]}])
    assert snap.files == [] and snap.uncertain_modules == {'5', '6'} and snap.complete


# ---------- finalize review (MRK-42): hardening regressions ----------

def test_errors_carry_no_chained_upstream_exception(db, moodle):
    transport = MoodleWsClient(config(), opener=FakeOpener(OSError(f'{BASE}?wstoken={TOKEN}')))
    with pytest.raises(MoodleSyncError) as caught:
        transport.courses()
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    bad_json = MoodleWsClient(config(), opener=FakeOpener(b'{not json ' + TOKEN.encode()))
    with pytest.raises(MoodleSyncError) as caught:
        bad_json.course_contents('101')
    assert caught.value.__context__ is None

    class Exploding(FakeMoodle):
        def courses(self):
            raise RuntimeError(f'leak {TOKEN}')
    with pytest.raises(MoodleSyncError) as caught:
        service.sync_materials(db, client=Exploding(), now=NOW)
    assert caught.value.__context__ is None and caught.value.category == 'unavailable'
    assert_no_canary(_rendered(caught.value))


def test_download_origin_comparison_is_robust():
    path = '/webservice/pluginfile.php/7/mod_resource/content/1/a.pdf'
    ok = FakeOpener(*[b'%PDF-1.4'] * 3)
    client = MoodleWsClient(config(), opener=ok)
    for allowed in (f'https://MOODLE.Example.INVALID{path}', f'https://moodle.example.invalid:443{path}',
                    f'{BASE}{path}?token={SIGNED}#frag'):
        assert client.download(allowed, 1024) == b'%PDF-1.4'
    assert [r.full_url for r in ok.requests] == [BASE + path] * 3, 'always rebuilt from the configured origin'
    for rejected in (f'https://moodle.example.invalid:8443{path}', f'https://moodle.example.invalid.evil.invalid{path}',
                     f'https://evilmoodle.example.invalid{path}', f'https://evil.invalid\\@moodle.example.invalid{path}',
                     f'https://moodle.example.invalid@evil.invalid{path}', f'HTTP://moodle.example.invalid{path}',
                     f'https://moodle.example.invalid:99999{path}', f'https://localhost{path}', f'https://127.0.0.1{path}',
                     f'{BASE}/webservice/pluginfile.php/%2e%2e/%2E%2E/login/token.php',
                     f'{BASE}/webservice/pluginfile.php/1/a%2fb.pdf', f'{BASE}/webservice/pluginfile.php/1/a b.pdf',
                     f'//moodle.example.invalid{path}', path):
        with pytest.raises(MoodleSyncError, match='file_url_rejected'):
            client.download(rejected, 1024)
    assert len(ok.requests) == 3


def test_moodle_in_a_sub_path():
    opener = FakeOpener(b'{"userid": 3}', b'%PDF-1.4')
    client = MoodleWsClient(MoodleConfig(f'{BASE}/moodle', TOKEN, 1024), opener=opener)
    client.user_id()
    assert opener.requests[0].full_url == f'{BASE}/moodle/webservice/rest/server.php'
    assert client.download(f'{BASE}/moodle/webservice/pluginfile.php/1/x.pdf', 1024) == b'%PDF-1.4'
    with pytest.raises(MoodleSyncError, match='file_url_rejected'):
        client.download(f'{BASE}/webservice/pluginfile.php/1/x.pdf', 1024)


def test_disabled_ws_function_fails_only_that_course(db, moodle):
    service.sync_materials(db, client=moodle, now=NOW)
    ws = MoodleWsClient(config(), opener=FakeOpener(json.dumps(
        {'exception': 'webservice_access_exception', 'errorcode': 'accessexception', 'message': 'Access control exception'}).encode()))
    moodle.course_contents = ws.course_contents
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['courses_failed'] == 1 and stats['missing'] == 0
    assert all(m.source_missing_at is None for m in db.query(StudyMaterial))


def test_unconfigured_connector_leaves_school_untouched(db, api):
    db.add(models.Subject(name='Biologie', code='BIO101'))
    db.commit()
    listing = api.get('/school/materials').json()
    assert listing['configured'] is False and listing['materials'] == [] and listing['subjects'][0]['name'] == 'Biologie'
    assert api.post('/school/materials/sync').status_code == 503
    assert db.query(models.ActivityLog).count() == 0 and db.query(models.DomainEvent).count() == 0


def test_utf16_dtd_and_macro_packages_are_refused():
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = f'<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE d [<!ENTITY a "aaaa">]><w:document {ns}>&a;</w:document>'
    evil = _zip({'word/document.xml': doc.encode('utf-16')})
    assert extract.extract_text(evil, 'docx').status == 'failed'
    macro = _zip({'word/document.xml': '<w:document/>', 'word/vbaProject.bin': b'\x00macro'})
    assert not storage.sniff(macro, 'docx')
    assert storage.sniff(make_docx('ok'), 'docx')


def test_raised_size_limit_retries_previously_too_large(db, moodle, monkeypatch):
    moodle.module(23)['contents'] = [file_entry('huge.pdf', b'', size=7 * 1024 * 1024)]
    moodle.files[url('huge.pdf')] = make_pdf('Big scan')
    service.sync_materials(db, client=moodle, now=NOW)
    assert by_file(db)['huge.pdf'].download_status == 'too_large'
    assert service.sync_materials(db, client=moodle, now=LATER)['unchanged'] == 7
    monkeypatch.setenv('MOODLE_MAX_FILE_MB', '10')
    stats = service.sync_materials(db, client=moodle, now=LATER)
    assert stats['updated'] == 1 and by_file(db)['huge.pdf'].download_status == 'stored'


def test_concurrent_identical_store_never_tears(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv('MEDIA_DIR', str(tmp_path))
    data = make_pdf('same bytes') * 50
    names = []
    threads = [threading.Thread(target=lambda: names.append(storage.store(data, 'pdf')[0])) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(names)) == 1 and storage.read(names[0]) == data
    assert sorted(p.name for p in (tmp_path / 'study-materials').iterdir()) == [names[0]], 'no temp files left'
