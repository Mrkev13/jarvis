"""Study-material contributions (MRK-42) – merged into the School module's ModuleIntegrations by
`school_integrations.py`, so the global aggregators stay module-free (Search, AI context, What Changed, REST)."""
from __future__ import annotations

import re
from datetime import timedelta

from context_format import short
from modules.school.extract import PAGE_MARK_CLOSE, PAGE_MARK_OPEN
from module_contracts import ContextRequest, ContextSection, EntityRef, SearchSource
from modules.school.models import StudyCourse, StudyMaterial
from modules.school.router import router
from time_utils import local_to_utc

SEARCH_LIMIT = 500
_PAGE_LINE = re.compile(rf'{PAGE_MARK_OPEN}\d+{PAGE_MARK_CLOSE}')
SEARCH_TEXT_CHARS = 5000  # bounded excerpt of derived text joins the haystack; full documents never do
MATERIAL_HREF = '/school/materials?material={id}'
TYPE_LABELS = {'pdf': 'PDF', 'pptx': 'Prezentace', 'docx': 'Dokument', 'txt': 'Text', 'other': 'Soubor'}

# merged into the School ChangeSource (one event mapper per module)
CHANGE_HREFS = {'study_material': MATERIAL_HREF, 'study_course': '/school/materials?course={id}'}
CHANGE_TITLES = {'school.material.created': 'Nový studijní materiál', 'school.material.updated': 'Studijní materiál změněn',
                 'school.material.source_missing': 'Materiál zmizel z Moodlu',
                 'school.material.restored': 'Materiál je zpět v Moodlu'}
EVENT_TYPES = frozenset(CHANGE_TITLES)


def _plain(text: str | None) -> str:
    """Bounded excerpt for the haystack, without PDF page-marker lines."""
    return _PAGE_LINE.sub(' ', (text or '')[:SEARCH_TEXT_CHARS])


def search_materials(db, q):
    courses = {c.id: c for c in db.query(StudyCourse).all()}
    rows = (db.query(StudyMaterial).order_by(StudyMaterial.updated_at.desc(), StudyMaterial.id.desc())
            .limit(SEARCH_LIMIT).all())
    for m in rows:
        course = courses.get(m.course_id)
        subtitle = ' · '.join(filter(None, ['Studijní materiál', TYPE_LABELS.get(m.material_type),
                                            course.name if course else None,
                                            'zmizelo z Moodlu' if m.source_missing_at else None]))
        haystack = ' '.join(filter(None, ['material podklady studijni', m.file_name, m.section_name,
                                          course.short_name if course else None, _plain(m.extracted_text)]))
        yield 'study_material', m.id, m.title, subtitle, haystack, 'school', MATERIAL_HREF.format(id=m.id)


def context_materials(req: ContextRequest) -> list[str]:
    """Deterministic overview only (counts, recent titles/types). Never document text."""
    db = req.db
    active = db.query(StudyMaterial).filter(StudyMaterial.source_missing_at.is_(None))
    total = active.count()
    if total == 0:
        return ['Studijní materiály: zatím žádné (Moodle sync materiálů neproběhl nebo nic nenašel).']
    courses = {c.id: c for c in db.query(StudyCourse).all()}
    since = local_to_utc(req.local_now) - timedelta(days=14)  # request clock, not the wall clock (testable, MRK-70)
    recent = active.filter(StudyMaterial.created_at >= since).order_by(StudyMaterial.created_at.desc()).limit(5).all()
    missing = db.query(StudyMaterial).filter(StudyMaterial.source_missing_at.isnot(None)).count()
    by_type: dict[str, int] = {}
    for (kind,) in active.with_entities(StudyMaterial.material_type).all():
        by_type[kind] = by_type.get(kind, 0) + 1
    types = ', '.join(f'{TYPE_LABELS.get(k, k)} {n}' for k, n in sorted(by_type.items()))
    lines = [f'Studijní materiály: {total} aktivních ({types}); {missing} zmizelo z Moodlu.']
    if recent:
        items = '; '.join(f'{short(m.title, 50)} (id {m.id}, {TYPE_LABELS.get(m.material_type)}, '
                          f'{short(courses[m.course_id].name, 30) if m.course_id in courses else "?"})' for m in recent)
        lines.append(f'Nové materiály za 14 dní: {items}')
    return lines


SEARCH = (SearchSource('school_materials', 11, search_materials),)
CONTEXT = (ContextSection('school_materials', ('materia', 'prezentac', 'skripta', 'podklad', 'studijni', 'moodle', 'slajd', 'pdf', 'kapitol', 'ucit'),
                          order=11, build=context_materials),)
ENTITY_REFS = (EntityRef('study_material', MATERIAL_HREF),)
ROUTERS = (router,)
