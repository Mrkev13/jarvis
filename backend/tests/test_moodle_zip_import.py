"""MRK-56 Moodle course-ZIP import: synthetic exports only (invented course, generated documents) – no real Moodle
export, file or text, no network, no LLM. The layout mirrors the official „Stáhnout obsah kurzu" export:
`<course folder>.<number>/index.html` + `<activity folder>.<number>/index.html` + `<activity>/content/<file>`."""
import io
import os
import stat
import zipfile
from unittest.mock import patch

import pytest

import models
from modules.school import integrations, service, zip_import
from modules.school.models import StudyCourse, StudyMaterial
from modules.school.service import RemoteFile, CourseSnapshot
from tests.test_study_materials import NOW, LATER, make_docx, make_pdf, make_pptx


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    monkeypatch.setenv('MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setenv('MOODLE_MAX_FILE_MB', '5')
    for key in ('MOODLE_WS_BASE_URL', 'MOODLE_WS_TOKEN', 'MOODLE_COURSE_IDS', 'MOODLE_ZIP_MAX_MB'):
        monkeypatch.delenv(key, raising=False)
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def api(db, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    from module_registry import ModuleAccess
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(main, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
        yield client
    client.close()

COURSE_DIR = 'Kurz_SYN101_SYN202_Synteticky_kurz_..._.900001'
COURSE_TITLE = 'Syntetický kurz – ZS 99/00'


def activity_page(title, links=()):
    items = ''.join(f'<a href="content/{name}">{name}</a>' for name in links)
    return (f'<html><head><title>Moodle – {COURSE_TITLE}</title></head><body><h1>{COURSE_TITLE}</h1>'
            f'<h2>{title}</h2><h3>Soubory a podsložky</h3><div>{items}</div>'
            f'<a href="https://moodle.example.invalid/course/view.php?id=77">kurz</a></body></html>')


def root_page(sections):
    body = ''.join(f'<h3>{name}</h3><ul>' + ''.join(f'<li><a href="./{folder}/index.html">x</a></li>' for folder in folders)
                   + '</ul>' for name, folders in sections)
    return (f'<html><body><h1>{COURSE_TITLE}</h1><a href="https://moodle.example.invalid/course/view.php?id=77">k</a>'
            f'{body}</body></html>')


def default_activities():
    return {
        'Soubor_Prednaska_1_.900011': ('Přednáška 1 – Výroková logika', {'lecture.pdf': make_pdf('Synthetic logic lecture')}),
        'Soubor_Slidy_.900012': ('Slidy – Grafy', {'slides.pptx': make_pptx('Graph theory slide', 'Spanning trees')}),
        'Sloka_Seminar_.900013': ('Seminář', {'notes.docx': make_docx('Seminar notes about relations'),
                                              'reading.txt': 'Synthetic reading list'.encode(),
                                              'photo.png': b'\x89PNG\r\n\x1a\nnot really'}),
        'Test_Zapoctovy_test_.900014': ('Zápočtový test', None),  # quiz: HTML only
        'Frum_Oznameni_.900015': ('Oznámení', None),
    }


SECTIONS = [('Úvod', ['Frum_Oznameni_.900015']),
            ('1. týden', ['Soubor_Prednaska_1_.900011', 'Soubor_Slidy_.900012']),
            ('2. týden', ['Sloka_Seminar_.900013', 'Test_Zapoctovy_test_.900014'])]


def build_export(activities=None, *, sections=SECTIONS, extra=None, root=COURSE_DIR, listed_extra=None):
    activities = default_activities() if activities is None else activities
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'{root}/index.html', root_page(sections))
        archive.writestr(f'{root}/shared/moodle.css', 'body{}')
        for folder, (title, files) in activities.items():
            links = list(files or {}) + list((listed_extra or {}).get(folder, []))
            archive.writestr(f'{root}/{folder}/index.html', activity_page(title, links))
            for name, data in (files or {}).items():
                archive.writestr(f'{root}/{folder}/content/{name}', data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def run_import(db, data, now=NOW):
    return zip_import.import_course_export(db, io.BytesIO(data), now=now)


def materials(db):
    return {m.file_name: m for m in db.query(StudyMaterial).all()}


def facts(db):
    return [e.event_type for e in db.query(models.DomainEvent).order_by(models.DomainEvent.id)]


def media_files(tmp_path):
    folder = tmp_path / 'media' / 'study-materials'
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# ---------- core import ----------

def test_import_reuses_the_mrk42_model_with_local_titles_sections_and_extraction(db):
    stats = run_import(db, build_export())
    course = db.query(StudyCourse).one()
    assert (course.source, course.external_id, course.name, course.short_name) == (
        'moodle_export', '900001', COURSE_TITLE, 'SYN101, SYN202')
    assert course.subject_id is None, 'mapping is never auto-applied'
    rows = materials(db)
    assert set(rows) == {'lecture.pdf', 'slides.pptx', 'notes.docx', 'reading.txt', 'photo.png'}, 'quiz/forum stay HTML'
    assert rows['lecture.pdf'].title == 'Přednáška 1 – Výroková logika', 'full title from the local HTML'
    assert rows['notes.docx'].title == 'Seminář – notes.docx', 'multi-file activity: activity – file'
    assert rows['lecture.pdf'].section_name == '1. týden' and rows['reading.txt'].section_name == '2. týden'
    assert rows['lecture.pdf'].module_external_id == '900011' and rows['lecture.pdf'].external_id == '900011:/lecture.pdf'
    for name in ('lecture.pdf', 'slides.pptx', 'notes.docx', 'reading.txt'):
        assert rows[name].download_status == 'stored' and rows[name].extraction_status in ('ok', 'truncated'), name
    assert 'Synthetic logic lecture' in rows['lecture.pdf'].extracted_text
    assert rows['photo.png'].download_status == 'unsupported' and rows['photo.png'].stored_name is None
    assert all(m.source_missing_at is None for m in rows.values())
    assert stats['created'] == 5 and stats['courses_incomplete'] == 1 and stats['completeness'] == 'unproven'
    assert facts(db).count('school.material.created') == 5
    assert all('html' not in m.file_name for m in rows.values()), 'HTML never becomes a material'


def test_reimport_of_the_same_export_is_noise_free_and_reuses_blobs(db, tmp_path):
    data = build_export()
    run_import(db, data)
    blobs, events = media_files(tmp_path), len(facts(db))
    activity = db.query(models.ActivityLog).count()
    stats = run_import(db, data, now=LATER)
    assert (stats['created'], stats['updated'], stats['unchanged'], stats['downloaded']) == (0, 0, 5, 0)
    assert media_files(tmp_path) == blobs and len(facts(db)) == events and db.query(models.ActivityLog).count() == activity
    assert db.query(StudyCourse).count() == 1 and db.query(StudyMaterial).count() == 5


def test_changed_content_with_the_same_size_is_detected_by_checksum(db):
    run_import(db, build_export())
    old = materials(db)['reading.txt'].checksum
    acts = default_activities()
    acts['Sloka_Seminar_.900013'][1]['reading.txt'] = 'Synthetic READING list'.encode()  # same length
    stats = run_import(db, build_export(acts), now=LATER)
    row = materials(db)['reading.txt']
    assert stats['updated'] == 1 and row.checksum != old and 'READING' in row.extracted_text
    assert facts(db).count('school.material.updated') == 1


def test_a_file_absent_from_a_later_export_is_never_marked_missing(db):
    run_import(db, build_export())
    acts = default_activities()
    del acts['Soubor_Slidy_.900012']
    stats = run_import(db, build_export(acts), now=LATER)
    assert stats['missing'] == 0 and materials(db)['slides.pptx'].source_missing_at is None
    assert 'school.material.source_missing' not in facts(db)


def test_listed_but_absent_file_becomes_metadata_only_and_counts_as_missing_from_zip(db):
    stats = run_import(db, build_export(listed_extra={'Soubor_Prednaska_1_.900011': ['big-scan.pdf']}))
    row = materials(db)['big-scan.pdf']
    assert row.download_status == 'metadata_only' and row.size_bytes is None and row.stored_name is None
    assert stats['files_listed_missing'] == 1
    assert materials(db)['lecture.pdf'].title == 'Přednáška 1 – Výroková logika – lecture.pdf'


def test_export_identities_never_merge_with_web_services_rows(db):
    snap = CourseSnapshot(files=[RemoteFile('900011:/lecture.pdf', '900011', 'WS lecture', None, 'lecture.pdf', 'pdf', None,
                                            None, None, None)])
    stats = service._new_stats()
    service._sync_course(db, '900001', 'WS course', None, snap, client=None, limit=1, now=NOW, stats=stats)
    db.commit()
    run_import(db, build_export())
    assert sorted(c.source for c in db.query(StudyCourse).all()) == ['moodle', 'moodle_export']
    assert db.query(StudyMaterial).filter_by(external_id='900011:/lecture.pdf').count() == 2


def test_too_large_file_is_skipped_and_retried_after_the_limit_rises(db, monkeypatch):
    monkeypatch.setenv('MOODLE_MAX_FILE_MB', '1')
    big = make_pdf('Synthetic big') + b'%' + os.urandom(1_300_000)  # incompressible: no ratio trip
    acts = {'Soubor_Velky_.900021': ('Velký soubor', {'big.pdf': big})}
    sections = [('1. týden', ['Soubor_Velky_.900021'])]
    run_import(db, build_export(acts, sections=sections))
    assert materials(db)['big.pdf'].download_status == 'too_large'
    monkeypatch.setenv('MOODLE_MAX_FILE_MB', '5')
    stats = run_import(db, build_export(acts, sections=sections), now=LATER)
    assert materials(db)['big.pdf'].download_status == 'stored' and stats['updated'] == 1


def test_macro_package_and_disguised_files_are_rejected_not_stored(db):
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<w:document/>')
        archive.writestr('word/vbaProject.bin', b'macro')
    acts = {'Soubor_Makro_.900031': ('Makro', {'evil.docx': macro.getvalue()}),
            'Soubor_Fake_.900032': ('Fake', {'fake.pdf': b'MZ\x90\x00 not a pdf'})}
    run_import(db, build_export(acts, sections=[('S', list(acts))]))
    rows = materials(db)
    assert rows['evil.docx'].download_status == 'rejected' and rows['evil.docx'].stored_name is None
    assert rows['fake.pdf'].download_status == 'rejected'


def test_nested_archives_are_listed_as_unsupported_and_never_opened(db):
    inner = build_export()
    acts = {'Soubor_Archiv_.900041': ('Archiv', {'more.zip': inner})}
    outer = build_export(acts, sections=[('S', list(acts))])
    with patch.object(zipfile.ZipFile, 'open', wraps=zipfile.ZipFile.open, autospec=True) as opened:
        stats = run_import(db, outer)
    assert materials(db)['more.zip'].download_status == 'unsupported' and stats['archives_ignored'] == 1
    assert all(not call.args[1].filename.endswith('more.zip') for call in opened.call_args_list if hasattr(call.args[1], 'filename'))
    assert db.query(StudyCourse).count() == 1, 'the inner course was not imported'


# ---------- archive hardening ----------

def zip_with(entries, *, root=COURSE_DIR):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'{root}/index.html', root_page([]))
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                archive.writestr(entry, b'x')
            else:
                archive.writestr(entry, b'x')
    return buffer.getvalue()


@pytest.mark.parametrize('name', [
    f'{COURSE_DIR}/../evil.pdf', f'../{COURSE_DIR}/x.pdf', '/abs/evil.pdf',
    f'C:/{COURSE_DIR}/evil.pdf', f'{COURSE_DIR}/./x.pdf', f'{COURSE_DIR}//x.pdf', f'{COURSE_DIR}/a\x01b.pdf',
])
def test_unsafe_paths_reject_the_whole_archive(db, name):
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, zip_with([name]))
    assert error.value.category == 'unsafe_path'
    assert db.query(StudyCourse).count() == 0


def test_symlink_encrypted_and_duplicate_entries_are_rejected(db):
    link = zipfile.ZipInfo(f'{COURSE_DIR}/link.pdf')
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    encrypted = set_encrypted_flag(zip_with([f'{COURSE_DIR}/secret.pdf']), f'{COURSE_DIR}/secret.pdf')
    for data, category in ((zip_with([link]), 'symlink_entry'), (encrypted, 'encrypted_entry'),
                           (exact_duplicate_zip(), 'duplicate_entry')):
        with pytest.raises(zip_import.ZipImportError) as error:
            run_import(db, data)
        assert error.value.category == category


def exact_duplicate_zip():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # zipfile warns about the duplicate name it is told to write
        return zip_with([f'{COURSE_DIR}/same.pdf', f'{COURSE_DIR}/same.pdf'])


def test_case_variant_names_are_distinct_files_not_duplicates(db):
    acts = {'Soubor_Case_.900061': ('Case', {'Notes.txt': b'Upper case synthetic', 'notes.txt': b'lower case synthetic'})}
    stats = run_import(db, build_export(acts, sections=[('S', list(acts))]))
    assert stats['created'] == 2 and {m.file_name for m in db.query(StudyMaterial).all()} == {'Notes.txt', 'notes.txt'}


def corrupt_entry(data: bytes, name: str, *, method: int | None = None) -> bytes:
    """Flip one byte of the entry's compressed data, or rewrite its compression method in both headers."""
    import struct
    raw, encoded = bytearray(data), name.encode()
    start = raw.find(b'PK\x03\x04')
    while start != -1:
        name_len, extra_len = struct.unpack_from('<HH', raw, start + 26)
        if raw[start + 30:start + 30 + name_len] == encoded:
            if method is None:
                raw[start + 30 + name_len + extra_len + 2] ^= 0xFF
            else:
                struct.pack_into('<H', raw, start + 8, method)
        start = raw.find(b'PK\x03\x04', start + 4)
    if method is not None:
        start = raw.find(b'PK\x01\x02')
        while start != -1:
            name_len = struct.unpack_from('<H', raw, start + 28)[0]
            if raw[start + 46:start + 46 + name_len] == encoded:
                struct.pack_into('<H', raw, start + 10, method)
            start = raw.find(b'PK\x01\x02', start + 4)
    return bytes(raw)


@pytest.mark.parametrize('method', [None, 9])  # corrupt deflate stream / unsupported Deflate64
def test_one_unreadable_entry_fails_only_that_file(db, method):
    name = f'{COURSE_DIR}/Sloka_Seminar_.900013/content/reading.txt'
    stats = run_import(db, corrupt_entry(build_export(), name, method=method))
    rows = materials(db)
    assert rows['reading.txt'].download_status == 'failed' and rows['reading.txt'].stored_name is None
    assert rows['lecture.pdf'].download_status == 'stored' and stats['created'] == 5


def test_listed_missing_links_and_files_per_import_are_capped(db, monkeypatch):
    links = [f'missing-{i}.pdf' for i in range(zip_import.MAX_LISTED_MISSING + 50)] * 2  # duplicates collapse
    stats = run_import(db, build_export(listed_extra={'Soubor_Prednaska_1_.900011': links}))
    assert stats['files_listed_missing'] == zip_import.MAX_LISTED_MISSING
    assert db.query(StudyMaterial).filter_by(download_status='metadata_only').count() == zip_import.MAX_LISTED_MISSING
    monkeypatch.setattr(zip_import, 'MAX_FILES', 3)
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, build_export(), now=LATER)
    assert error.value.category == 'too_many_entries'


def test_html_budget_falls_back_to_folder_names(db, monkeypatch):
    monkeypatch.setattr(zip_import, 'MAX_HTML_TOTAL', 10)
    stats = run_import(db, build_export())
    course = db.query(StudyCourse).one()
    assert stats['created'] == 5 and course.name == 'SYN101 SYN202 Synteticky kurz ...'
    assert materials(db)['lecture.pdf'].title == 'Prednaska 1' and materials(db)['lecture.pdf'].section_name is None


def test_rejected_files_are_not_reread_on_unchanged_reimport(db):
    acts = {'Soubor_Fake_.900032': ('Fake', {'fake.pdf': b'MZ\x90\x00 not a pdf'})}
    data = build_export(acts, sections=[('S', list(acts))])
    run_import(db, data)
    stats = run_import(db, data, now=LATER)
    assert (stats['downloaded'], stats['file_rejected'], stats['unchanged']) == (0, 0, 1)


def test_folder_wrapper_survives_an_unexpected_failure(db, tmp_path, monkeypatch, capsys):
    import database
    import importlib.util
    folder = tmp_path / 'exports'
    folder.mkdir()
    (folder / 'a.zip').write_bytes(build_export())
    (folder / 'b.zip').write_bytes(build_export())
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    spec = importlib.util.spec_from_file_location('import_moodle_zips', os.path.join(
        os.path.dirname(__file__), '..', 'scripts', 'import_moodle_zips.py'))
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    real = zip_import.import_course_export
    calls = []

    def flaky(session, handle):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('internal C:/secret/entry/name')
        return real(session, handle)
    monkeypatch.setattr(zip_import, 'import_course_export', flaky)
    assert script.main([str(folder)]) == 1
    out = capsys.readouterr().out
    assert 'a.zip: chyba (import_failed)' in out and 'b.zip: nové 5' in out and 'secret' not in out


def test_name_guard_rejects_backslashes_drives_and_dot_segments():
    # zipfile turns '\' into '/' when reading on Windows; the guard still refuses it everywhere else
    for name in ('a\\b.pdf', 'C:/x.pdf', 'a/../b', './a', 'a//b', '/a', '\\a', 'a/\x00b', 'x' * 2000):
        assert zip_import._unsafe_name(name), name
    for name in ('Kurz_A_.1/index.html', 'Kurz_A_.1/Soubor_B_.2/content/sub/c.pdf', 'Kurz_A_.1/dir/'):
        assert not zip_import._unsafe_name(name), name


def set_encrypted_flag(data: bytes, name: str) -> bytes:
    """zipfile clears flag bits on write; set the general-purpose flag (bit 0) in both headers."""
    raw, encoded = bytearray(data), name.encode()
    for signature, flag_offset, name_offset in ((b'PK\x03\x04', 6, 30), (b'PK\x01\x02', 8, 46)):
        start = raw.find(signature)
        while start != -1:
            if raw[start + name_offset:start + name_offset + len(encoded)] == encoded:
                raw[start + flag_offset] |= 0x01
            start = raw.find(signature, start + 4)
    return bytes(raw)


def test_entry_count_declared_total_and_compression_ratio_limits(db, monkeypatch):
    monkeypatch.setattr(zip_import, 'MAX_ENTRIES', 3)
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, zip_with([f'{COURSE_DIR}/{i}.txt' for i in range(5)]))
    assert error.value.category == 'too_many_entries' and error.value.status == 413
    monkeypatch.setattr(zip_import, 'MAX_ENTRIES', 5000)
    monkeypatch.setattr(zip_import, 'MAX_DECLARED_TOTAL', 100)
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, build_export())
    assert error.value.category == 'uncompressed_too_large'
    monkeypatch.setattr(zip_import, 'MAX_DECLARED_TOTAL', 4 * 1024 ** 3)
    bomb = {'Soubor_Bomba_.900051': ('Bomba', {'bomb.txt': b'\0' * (3 * 1024 * 1024)})}
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, build_export(bomb, sections=[('S', list(bomb))]))
    assert error.value.category == 'compression_ratio'


def test_entry_reads_are_capped_and_corruption_is_a_transient_failure(db):
    from modules.school.moodle import MoodleSyncError
    name = f'{COURSE_DIR}/Sloka_Seminar_.900013/content/reading.txt'
    with zipfile.ZipFile(io.BytesIO(build_export())) as archive:
        client = zip_import._ZipClient(archive, {name: archive.getinfo(name)})
        with pytest.raises(MoodleSyncError) as error:
            client.download(name, 5)  # declared size above the cap: refused before reading
        assert error.value.category == 'file_too_large'
        archive.getinfo(name).file_size = 3  # header lies: zipfile stops there and the CRC check fails
        with pytest.raises(MoodleSyncError) as error:
            client.download(name, 1024)
        assert error.value.category == 'unavailable'
        with pytest.raises(MoodleSyncError) as error:
            client.download('not/in/the/validated/set.pdf', 1024)
        assert error.value.category == 'file_url_rejected'


@pytest.mark.parametrize('payload, category', [
    (b'definitely not a zip', 'archive_invalid'),
    (b'', 'archive_invalid'),
])
def test_invalid_archives(db, payload, category):
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, payload)
    assert error.value.category == category


def test_not_a_course_export(db):
    for data in (zip_with([], root='Not_A_Course'),  # no numeric course folder suffix
                 build_export(extra={'Other_Root_.1/index.html': 'x'})):  # two roots
        with pytest.raises(zip_import.ZipImportError) as error:
            run_import(db, data)
        assert error.value.category == 'not_course_export'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(f'{COURSE_DIR}/Soubor_X_.1/content/a.pdf', make_pdf())  # no course index.html
    with pytest.raises(zip_import.ZipImportError) as error:
        run_import(db, buffer.getvalue())
    assert error.value.category == 'not_course_export'


def test_failed_import_rolls_back_everything(db):
    with patch.object(zip_import, '_sync_course', side_effect=RuntimeError('boom /secret/path')):
        with pytest.raises(zip_import.ZipImportError) as error:
            run_import(db, build_export())
    assert error.value.category == 'import_failed' and 'secret' not in str(error.value)
    assert db.query(StudyCourse).count() == 0 and db.query(StudyMaterial).count() == 0


# ---------- integrations, API, folder wrapper ----------

def test_imported_materials_flow_into_search_and_what_changed(db):
    run_import(db, build_export())
    hits = list(integrations.search_materials(db, 'Výroková'))
    assert any('Přednáška 1' in hit[2] for hit in hits)
    from change_feed import build
    from module_registry import ModuleAccess
    from datetime import timedelta
    items = build(db, ModuleAccess({}), since=(NOW - timedelta(hours=1)).replace(tzinfo=__import__('datetime').timezone.utc),
                  modules=frozenset({'school'}), limit=100)['items']
    ids = [i['id'] for i in items]
    assert len(ids) == len(set(ids)) and sum(i['kind'] == 'created' for i in items) >= 5


def test_api_upload_counts_and_allowlisted_errors(db, api, monkeypatch):
    ok = api.post('/school/materials/import-zip', content=build_export(), headers={'Content-Type': 'application/zip'})
    assert ok.status_code == 200 and ok.json()['created'] == 5 and ok.json()['completeness'] == 'unproven'
    again = api.post('/school/materials/import-zip', content=build_export(), headers={'Content-Type': 'application/zip'})
    assert again.json()['created'] == 0 and again.json()['unchanged'] == 5
    listing = api.get('/school/materials').json()
    assert len(listing['materials']) == 5 and listing['courses'][0]['short_name'] == 'SYN101, SYN202'
    wrong = api.post('/school/materials/import-zip', content=b'x', headers={'Content-Type': 'text/plain'})
    assert wrong.status_code == 415 and wrong.json() == {'detail': {'category': 'unsupported_media_type'}}
    bad = api.post('/school/materials/import-zip', content=b'not a zip', headers={'Content-Type': 'application/zip'})
    assert bad.status_code == 400 and bad.json() == {'detail': {'category': 'archive_invalid'}}
    empty = api.post('/school/materials/import-zip', content=b'', headers={'Content-Type': 'application/zip'})
    assert empty.status_code == 400
    slip = api.post('/school/materials/import-zip', content=zip_with([f'{COURSE_DIR}/../x.pdf']),
                    headers={'Content-Type': 'application/zip'})
    assert slip.status_code == 400 and slip.json() == {'detail': {'category': 'unsafe_path'}}
    monkeypatch.setenv('MOODLE_ZIP_MAX_MB', '1')
    huge = api.post('/school/materials/import-zip', content=b'0' * (1024 * 1024 + 1), headers={'Content-Type': 'application/zip'})
    assert huge.status_code == 413 and huge.json() == {'detail': {'category': 'archive_too_large'}}


def test_folder_wrapper_uses_the_same_core(db, tmp_path, monkeypatch, capsys):
    import database
    import importlib.util
    folder = tmp_path / 'exports'
    folder.mkdir()
    (folder / 'course-a.zip').write_bytes(build_export())
    (folder / 'broken.zip').write_bytes(b'nope')
    (folder / 'notes.txt').write_text('ignored')
    sub = folder / 'nested'
    sub.mkdir()
    (sub / 'deep.zip').write_bytes(build_export(root='Kurz_DEEP_.900099'))  # not recursive
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    spec = importlib.util.spec_from_file_location('import_moodle_zips', os.path.join(
        os.path.dirname(__file__), '..', 'scripts', 'import_moodle_zips.py'))
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main([str(folder)]) == 1, 'one broken archive → non-zero exit'
    out = capsys.readouterr().out
    assert 'course-a.zip: nové 5' in out and 'broken.zip: chyba (archive_invalid)' in out and 'deep.zip' not in out
    assert db.query(StudyCourse).count() == 1


def test_control_characters_never_reach_extracted_text(db, monkeypatch):
    """PostgreSQL rejects NUL in text columns (SQLite does not): one PDF whose text layer yields NUL used to abort the
    whole import. Simulate the PostgreSQL rule on flush and feed an extraction with NUL/control characters."""
    from sqlalchemy import event
    from modules.school import extract

    def postgres_like(session, *_):
        for obj in list(session.new) + list(session.dirty):
            if isinstance(obj, StudyMaterial) and obj.extracted_text and '\x00' in obj.extracted_text:
                raise ValueError('A string literal cannot contain NUL (0x00) characters.')
    event.listen(db, 'before_flush', postgres_like)
    try:
        assert extract._finish(['Úvod\x00 do\x07 logiky\x1b', '\x7fstrana ⟦2⟧']).text == 'Úvod do logiky\nstrana ⟦2⟧'
        real = extract.extract_text
        monkeypatch.setattr(service, 'extract_text', lambda data, kind: extract._finish(['Synthetic\x00 text\x01 with NUL']) if kind == 'pdf' else real(data, kind))
        stats = run_import(db, build_export())
        row = materials(db)['lecture.pdf']
        assert stats['created'] == 5 and row.extracted_text == 'Synthetic text with NUL'
    finally:
        event.remove(db, 'before_flush', postgres_like)
