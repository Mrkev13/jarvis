"""MRK-75: edit and archive school subjects. Archive = active false; history stays, new choices do not offer it."""
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import database  # noqa: E402
import main  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Assignment, DomainEvent, Exam, Subject  # noqa: E402
from modules.school import service as materials  # noqa: E402
from modules.school.models import StudyCourse, StudyMaterial  # noqa: E402
from school_integrations import load_subjects, search_school  # noqa: E402

PIN = "4821"


class SchoolSubjectsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._patches = [patch.object(m, "SessionLocal", self.Session) for m in (auth_service, main, tools, database)]
        self._patches += [patch.object(auth_service, "_failed_attempts", {}),
                          patch.object(auth_service, "AUTH_PIN_HASH",
                                       bcrypt.hashpw(PIN.encode(), bcrypt.gensalt(rounds=4)).decode())]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)
        self.assertEqual(self.client.post("/auth/login", json={"pin": PIN}).status_code, 200)
        db = self.Session()
        try:
            law = Subject(name="Právo", code="PRA", semester="ZS 2025/26", credits=5, active=True)
            ait = Subject(name="Angličtina v IT", code="EIT", semester="LS 2026/27", credits=3, active=True)
            db.add_all([law, ait])
            db.flush()
            db.add_all([Assignment(title="Esej", subject_id=law.id, due_date=date(2026, 1, 10), status="done"),
                        Exam(title="Zápočet", subject_id=law.id, exam_date=date(2026, 1, 20), status="passed")])
            course = StudyCourse(source="moodle", external_id="11", name="Právo (PRA)", subject_id=law.id)
            db.add(course)
            db.flush()
            db.add(StudyMaterial(course_id=course.id, external_id="m1", module_external_id="1", title="Přednáška 1",
                                 file_name="p1.pdf", material_type="pdf"))
            db.commit()
            self.law, self.ait, self.course = law.id, ait.id, course.id
        finally:
            db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def patch_subject(self, subject_id, **body):
        return self.client.patch(f"/school/subject/{subject_id}", json=body)

    def facts(self):
        return self.q(lambda db: [e.event_type for e in db.query(DomainEvent).order_by(DomainEvent.id)])

    def test_edit_changes_only_given_fields_with_activity(self):
        r = self.patch_subject(self.ait, name="  English in IT ", credits=4)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"id": self.ait, "name": "English in IT", "code": "EIT", "semester": "LS 2026/27",
                                    "credits": 4, "active": True})
        log = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="Subject", entity_id=self.ait).one())
        self.assertEqual((log.area, log.action_type), ("school", "update"))
        self.assertIn("\"credits\"", log.delta_json)
        self.assertEqual(self.facts(), ["school.subject.updated"])

    def test_no_change_writes_nothing(self):
        self.assertEqual(self.patch_subject(self.ait, name="Angličtina v IT", active=True).status_code, 200)
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="Subject").count()), 0)
        self.assertEqual(self.facts(), [])

    def test_validation_and_missing_subject(self):
        for body in ({"name": "   "}, {"credits": -1}, {"credits": 100}, {"name": None}, {"code": "x" * 51}):
            self.assertEqual(self.patch_subject(self.ait, **body).status_code, 422, body)
        self.assertEqual(self.patch_subject(999, name="X").status_code, 404)
        self.assertEqual(self.q(lambda db: db.get(Subject, self.ait).name), "Angličtina v IT")

    def test_archive_keeps_history_and_hides_from_new_choices(self):
        r = self.patch_subject(self.law, active=False)
        self.assertEqual(r.json()["active"], False)
        self.assertEqual(self.facts(), ["school.subject.archived"])
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="Subject").one().action_type),
                         "archive")

        # nothing that belongs to the subject changed or disappeared
        def related(db):
            return (db.query(Assignment).one().subject_id, db.query(Exam).one().subject_id,
                    db.get(StudyCourse, self.course).subject_id, db.query(StudyMaterial).count())
        self.assertEqual(self.q(related), (self.law, self.law, self.law, 1))

        # not offered: REST default (forms), AI tool, Quick Add
        self.assertEqual([s["id"] for s in self.client.get("/school/subjects").json()], [self.ait])
        self.assertEqual([s["id"] for s in tools.get_school_subjects()], [self.ait])
        self.assertEqual([s["id"] for s in self.q(load_subjects)], [self.ait])
        # still visible on request, in history and in Search (labelled)
        listed = {s["id"]: s["active"] for s in self.client.get("/school/subjects?include_archived=true").json()}
        self.assertEqual(listed, {self.law: False, self.ait: True})
        self.assertEqual(self.client.get("/school/assignments").json()[0]["subject_name"], "Právo")
        hit = self.q(lambda db: next(r for r in search_school(db, "") if r[0] == "subject" and r[1] == self.law))
        self.assertIn("archivovaný", hit[3])

    def test_restore(self):
        self.patch_subject(self.law, active=False)
        self.assertEqual(self.patch_subject(self.law, active=True).json()["active"], True)
        self.assertEqual(self.facts(), ["school.subject.archived", "school.subject.restored"])
        self.assertEqual(len(self.client.get("/school/subjects").json()), 2)

    def test_course_mapping_keeps_archived_subject_but_offers_no_new_one(self):
        self.patch_subject(self.law, active=False)

        def run(fn):
            db = self.Session()
            try:
                return fn(db)
            finally:
                db.rollback()
                db.close()
        payload = run(lambda db: materials.list_materials(db))
        self.assertEqual(payload["courses"][0]["subject"]["id"], self.law, "existing mapping stays")
        self.assertEqual({s["id"]: s["active"] for s in payload["subjects"]}, {self.law: False, self.ait: True})
        # re-saving the current mapping is fine, a new mapping to an archived subject is refused
        run(lambda db: materials.set_course_subject(db, self.course, self.law))
        other = run(lambda db: (db.add(StudyCourse(source="moodle", external_id="12", name="Kurz PRA")), db.commit(),
                                db.query(StudyCourse).filter_by(external_id="12").one().id)[-1])
        with self.assertRaises(materials.MaterialError) as ctx:
            run(lambda db: materials.set_course_subject(db, other, self.law))
        self.assertEqual((ctx.exception.category, ctx.exception.status), ("subject_archived", 409))
        # the code "PRA" matches the course name, but an archived subject is never suggested
        self.assertIsNone(run(lambda db: materials.course_dict(db.get(StudyCourse, other), {
            s.id: s for s in db.query(Subject).all()}, {}))["suggested_subject_id"])

    def test_legacy_null_active_is_treated_as_active(self):
        # older rows may carry active = NULL: listed, offered and serialised as active, archivable like any other
        legacy = self.q(lambda db: (db.add(Subject(name="Starý předmět", code="OLD")), db.flush(),
                                    db.query(Subject).filter_by(code="OLD").one().id, db.commit())[2])
        self.q(lambda db: (db.query(Subject).filter_by(id=legacy).update({"active": None}), db.commit()))
        self.assertIsNone(self.q(lambda db: db.get(Subject, legacy).active))
        for path in ("/school/subjects", "/school/subjects?include_archived=true"):
            row = next(s for s in self.client.get(path).json() if s["id"] == legacy)
            self.assertIs(row["active"], True, path)
        self.assertIn(legacy, [s["id"] for s in self.q(load_subjects)])
        hit = self.q(lambda db: next(r for r in search_school(db, "") if r[0] == "subject" and r[1] == legacy))
        self.assertNotIn("archivovaný", hit[3])
        self.assertIs(self.patch_subject(legacy, active=False).json()["active"], False)
        self.assertEqual(self.facts(), ["school.subject.archived"])

    def test_requires_session(self):
        self.client.cookies.clear()
        self.assertEqual(self.patch_subject(self.ait, name="X").status_code, 401)


if __name__ == "__main__":
    unittest.main()
