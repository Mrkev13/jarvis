"""Phase B: deterministické vyhledání cíle (resolve_mutation) a atomické provedení (apply_mutation_plan)."""
import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import mutation_service as ms  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    ActivityLog, Assignment, Exam, FinanceTransaction, Goal, Memory, Subject, WorkSession, WotGrind,
)


class MutationTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._patch = patch.object(ms, "SessionLocal", self.Session)
        self._patch.start()
        self.db = self.Session()

    def tearDown(self):
        self._patch.stop()
        self.db.close()
        self.engine.dispose()

    def seed_work(self):
        # MRK-60: obecné chování resolveru/provedení se ověřuje na práci (Finance už AI entita není).
        self.db.add_all([
            WorkSession(date=date(2026, 10, 1), hours=3, project="Servind", hourly_rate=300, description="workshop"),
            WorkSession(date=date(2026, 10, 2), hours=3.5, project="Servind", hourly_rate=300,
                        description="workshop s kolegy"),
            WorkSession(date=date(2026, 10, 2), hours=1, project="Ostatní", hourly_rate=0, description="testovací směna"),
            WorkSession(date=date(2026, 9, 30), hours=8, project="Contoso", hourly_rate=500, description="konzultace"),
        ])
        self.db.commit()

    def seed_school(self):
        law = Subject(name="Právo")
        math = Subject(name="Matematika")
        self.db.add_all([law, math])
        self.db.flush()
        self.db.add_all([
            Assignment(title="Esej o ústavě", subject_id=law.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Sada příkladů", subject_id=math.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Referát", subject_id=math.id, status="done", due_date=date(2026, 10, 3)),
            Assignment(title="Projekt", subject_id=math.id, status="todo", due_date=date(2026, 10, 10)),
        ])
        self.db.commit()

    def fresh(self):
        self.db.close()
        self.db = self.Session()
        return self.db


class ResolveTestCase(MutationTestBase):
    def test_edit_latest_matching_session(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "update", {"text": "workshop", "latest": True}, {"hours": 4})
        self.assertEqual(len(plan["targets"]), 1)
        target = self.db.get(WorkSession, plan["targets"][0]["id"])
        self.assertEqual(target.description, "workshop s kolegy")
        change = plan["preview"]["items"][0]["changes"][0]
        self.assertEqual((change["label"], change["old"], change["new"]), ("Hodiny", "3,5", "4"))
        self.assertEqual(plan["preview"]["kind"], "update")
        json.dumps(plan)  # plán musí jít uložit do PendingAction.arguments

    def test_text_match_ignores_diacritics(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "delete", {"text": "testovaci"})
        self.assertEqual(plan["preview"]["items"][0]["label"], "2. 10. 2026 · 1 h · Ostatní · 0 Kč/h")

    def test_ambiguous_target_is_refused_with_candidates(self):
        self.seed_work()
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "delete", {"text": "workshop"})
        self.assertEqual(ctx.exception.code, "ambiguous_target")
        self.assertEqual(len(ctx.exception.candidates), 2)
        self.assertEqual(ctx.exception.as_tool_result()["status"], "not_prepared")

    def test_undescribed_target_is_refused(self):
        self.seed_work()
        for target in ({}, {"latest": True}, {"all_matching": True}):
            with self.subTest(target=target), self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(self.db, "work_session", "delete", target)
            self.assertEqual(ctx.exception.code, "ambiguous_target")

    def test_unknown_or_invalid_ids(self):
        self.seed_work()
        cases = [
            ({"id": 999}, "target_not_found"),
            ({"id": "abc"}, "invalid_target"),
            ({"id": 1, "text": "konzultace"}, "id_mismatch"),  # id existuje, ale popis sedí na jiný záznam
        ]
        for target, code in cases:
            with self.subTest(target=target), self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(self.db, "work_session", "delete", target)
            self.assertEqual(ctx.exception.code, code)

    def test_not_found(self):
        self.seed_work()
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "delete", {"text": "benzín"})
        self.assertEqual(ctx.exception.code, "target_not_found")

    def test_invalid_changes(self):
        self.seed_work()
        cases = [
            ({}, "invalid_changes"),
            ({"hours": -5}, "invalid_changes"),
            ({"id": 3}, "invalid_changes"),  # neznámé pole – id se měnit nedá
            ({"hours": 30}, "invalid_changes"),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(self.db, "work_session", "update", {"id": 1}, changes)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "update", {"id": 1}, {"hours": 3})
        self.assertEqual(ctx.exception.code, "no_change")
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "delete", {"id": 1}, {"hours": 5})
        self.assertEqual(ctx.exception.code, "invalid_changes")

    def test_unsupported_entity_and_action(self):
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "notification", "delete", {"id": 1})
        self.assertEqual(ctx.exception.code, "unsupported_entity")
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "complete", {"id": 1})
        self.assertEqual(ctx.exception.code, "unsupported_action")

    def test_finance_transaction_is_not_an_ai_entity(self):
        """MRK-60: AI Finance transakce nenajde ani nezmění – ani přes id, ani textem."""
        self.db.add(FinanceTransaction(amount=320, category="Jídlo", description="oběd", transaction_type="expense"))
        self.db.commit()
        self.assertNotIn("finance_transaction", ms.ENTITIES)
        self.assertNotIn("finance", ms.UNDO_AREAS)
        for target in ({"id": 1}, {"text": "oběd"}):
            with self.subTest(target=target), self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(self.db, "finance_transaction", "update", target, {"amount": 1})
            self.assertEqual(ctx.exception.code, "unsupported_entity")
            self.assertNotIn("oběd", ctx.exception.detail)

    def test_goal_computed_from_finance_is_not_a_target(self):
        """MRK-60: automatický cíl z Finance (bilance) AI nenajde ani podle id."""
        self.db.add(Goal(area="finance", title="Spořit", status="active", tracking_type="automatic",
                         source="finance_balance", target_value=1000))
        self.db.commit()
        for target in ({"id": 1}, {"text": "spořit"}):
            with self.subTest(target=target), self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(self.db, "goal", "update", target, {"priority": "low"})
            self.assertEqual(ctx.exception.code, "target_not_found")

    def test_complete_assignment_by_subject_name(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "complete", {"text": "pravo"})
        self.assertEqual(plan["preview"]["count"], 1)
        self.assertIn("Esej o ústavě", plan["preview"]["items"][0]["label"])
        self.assertEqual(plan["changes"], {"status": "done"})

    def test_batch_complete_lists_exact_set_and_skips_done(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "complete",
                                   {"date": "2026-10-03", "all_matching": True})
        titles = sorted(i["label"].split(" (")[0] for i in plan["preview"]["items"])
        self.assertEqual(titles, ["Esej o ústavě", "Sada příkladů"])  # hotový Referát není v dávce
        self.assertEqual(plan["preview"]["count"], 2)
        self.assertEqual(len(plan["targets"]), 2)

    def test_update_to_done_status_is_treated_as_complete_batch(self):
        # Regrese (live Phase B E): „označ všechny dnešní úkoly jako hotové" → model poslal
        # update + {status: done} + all_matching → batch_not_supported a žádná pending akce.
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "update",
                                   {"date": "2026-10-03", "all_matching": True}, {"status": "done"})
        self.assertEqual(plan["action"], "complete")
        self.assertEqual(plan["preview"]["kind"], "complete")
        self.assertEqual(plan["preview"]["count"], 2)  # hotový Referát se přeskočí jako u complete
        self.assertEqual(plan["changes"], {"status": "done"})

    def test_single_update_to_done_status_is_labelled_complete(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "update", {"text": "ústavě"}, {"status": "done"})
        self.assertEqual(plan["action"], "complete")
        self.assertEqual([t["id"] for t in plan["targets"]], [plan["preview"]["items"][0]["id"]])

    def test_update_with_other_changes_stays_update(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "update", {"text": "ústavě"},
                                   {"status": "done", "priority": "low"})
        self.assertEqual(plan["action"], "update")

    def test_goal_status_completed_update_is_not_converted(self):
        # Dokončení cíle navíc nastaví progres na 100 % → není to stejná změna jako update stavu.
        self.db.add(Goal(area="personal", title="Přečíst knihu", status="active", progress=40, tracking_type="manual"))
        self.db.commit()
        plan = ms.resolve_mutation(self.db, "goal", "update", {"text": "knihu"}, {"status": "completed"})
        self.assertEqual(plan["action"], "update")

    def test_batch_without_all_matching_is_ambiguous(self):
        self.seed_school()
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "school_assignment", "complete", {"date": "2026-10-03"})
        self.assertEqual(ctx.exception.code, "ambiguous_target")

    def test_batch_only_where_supported(self):
        self.seed_work()
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "work_session", "delete", {"text": "workshop", "all_matching": True})
        self.assertEqual(ctx.exception.code, "batch_not_supported")

    def test_batch_cap(self):
        s = Subject(name="Fyzika")
        self.db.add(s)
        self.db.flush()
        self.db.add_all([Assignment(title=f"Úkol {i}", subject_id=s.id, status="todo") for i in range(ms.MAX_BATCH + 1)])
        self.db.commit()
        with self.assertRaises(ms.MutationRefused) as ctx:
            ms.resolve_mutation(self.db, "school_assignment", "complete", {"text": "úkol", "all_matching": True})
        self.assertEqual(ctx.exception.code, "too_many_targets")

    def test_resolution_does_not_mutate(self):
        self.seed_work()
        ms.resolve_mutation(self.db, "work_session", "delete", {"text": "testovací"})
        self.assertEqual(self.fresh().query(WorkSession).count(), 4)

    def test_automatic_goal_progress_cannot_be_set(self):
        self.db.add(Goal(area="work", title="Odpracovat", status="active", tracking_type="automatic",
                         source="work_month_hours", target_value=100))
        self.db.commit()
        with self.assertRaises(ms.MutationRefused):
            ms.resolve_mutation(self.db, "goal", "update", {"text": "odpracovat"}, {"progress": 50})


class ApplyTestCase(MutationTestBase):
    def _logs(self):
        return self.fresh().query(ActivityLog).order_by(ActivityLog.id).all()

    def test_confirmed_edit_changes_exactly_the_target(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "update", {"text": "workshop", "latest": True}, {"hours": 4})
        target_id = plan["targets"][0]["id"]
        result = ms.apply_mutation_plan(json.loads(json.dumps(plan)), user_context="ai_confirm")
        self.assertEqual(result["ids"], [target_id])
        db = self.fresh()
        hours = {s.id: s.hours for s in db.query(WorkSession).all()}
        self.assertEqual(hours[target_id], 4)
        self.assertEqual(sorted(v for k, v in hours.items() if k != target_id), [1, 3, 8])
        log = self._logs()[-1]
        self.assertEqual((log.area, log.action_type, log.entity_id, log.user_context),
                         ("work", "update", target_id, "ai_confirm"))
        self.assertEqual(json.loads(log.delta_json)["hours"], {"old": 3.5, "new": 4.0})

    def test_confirmed_delete_and_audit(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "delete", {"text": "testovací"})
        ms.apply_mutation_plan(plan, user_context="ai_confirm")
        db = self.fresh()
        self.assertEqual(db.query(WorkSession).count(), 3)
        self.assertIsNone(db.get(WorkSession, plan["targets"][0]["id"]))
        self.assertEqual(self._logs()[-1].action_type, "delete")

    def test_finance_plan_is_rejected_before_touching_db(self):
        """MRK-60: plán s entitou Finance (např. pending akce z doby před MRK-60) se neprovede."""
        tx = FinanceTransaction(amount=1000, category="work", description="Work: X", transaction_type="income")
        self.db.add(tx)
        self.db.flush()
        self.db.add(WorkSession(date=date(2026, 10, 1), hours=4, project="X", hourly_rate=250,
                                finance_transaction_id=tx.id))
        self.db.commit()
        plan = {"version": 1, "entity": "finance_transaction", "action": "delete",
                "targets": [{"id": tx.id, "snapshot": {}}], "changes": {}}
        with self.assertRaises(ValueError):
            ms.apply_mutation_plan(plan)
        db = self.fresh()
        self.assertEqual(db.query(FinanceTransaction).count(), 1)
        self.assertEqual(db.query(WorkSession).one().finance_transaction_id, tx.id)

    def test_stale_target_fails_without_mutation(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "update", {"text": "testovací"}, {"hours": 2})
        ws = self.db.get(WorkSession, plan["targets"][0]["id"])
        ws.hours = 1.5  # někdo záznam mezitím změnil
        self.db.commit()
        ws_id = ws.id
        with self.assertRaises(ms.StaleTarget):
            ms.apply_mutation_plan(plan)
        self.assertEqual(self.fresh().get(WorkSession, ws_id).hours, 1.5)

    def test_deleted_target_fails_safely(self):
        self.seed_work()
        plan = ms.resolve_mutation(self.db, "work_session", "delete", {"text": "testovací"})
        self.db.delete(self.db.get(WorkSession, plan["targets"][0]["id"]))
        self.db.commit()
        with self.assertRaises(ms.StaleTarget):
            ms.apply_mutation_plan(plan)
        self.assertEqual(self.fresh().query(WorkSession).count(), 3)

    def test_batch_complete_success(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "complete",
                                   {"date": "2026-10-03", "all_matching": True})
        ms.apply_mutation_plan(plan, user_context="ai_confirm")
        statuses = {a.title: a.status for a in self.fresh().query(Assignment).all()}
        self.assertEqual(statuses, {"Esej o ústavě": "done", "Sada příkladů": "done", "Referát": "done",
                                    "Projekt": "todo"})
        self.assertEqual([lg.action_type for lg in self._logs()], ["complete", "complete"])

    def test_batch_is_atomic_when_one_target_is_stale(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "complete",
                                   {"date": "2026-10-03", "all_matching": True})
        second = self.db.get(Assignment, plan["targets"][1]["id"])
        second.title = "Přejmenováno"
        self.db.commit()
        with self.assertRaises(ms.StaleTarget):
            ms.apply_mutation_plan(plan)
        db = self.fresh()
        self.assertEqual(db.query(Assignment).filter(Assignment.status == "done").count(), 1)  # jen původní Referát
        self.assertEqual(db.query(ActivityLog).count(), 0)

    def test_batch_is_atomic_when_execution_fails_midway(self):
        self.seed_school()
        plan = ms.resolve_mutation(self.db, "school_assignment", "complete",
                                   {"date": "2026-10-03", "all_matching": True})
        calls = []
        original = ms._apply_one

        def flaky(db, ent, action, obj, changes, user_context):
            calls.append(obj.id)
            if len(calls) == 2:
                raise RuntimeError("DB výpadek")
            return original(db, ent, action, obj, changes, user_context)

        with patch.object(ms, "_apply_one", flaky), self.assertRaises(RuntimeError):
            ms.apply_mutation_plan(plan)
        self.assertEqual(self.fresh().query(Assignment).filter(Assignment.status == "done").count(), 1)

    def test_work_session_edit_keeps_historical_linked_income(self):
        """MRK-60: úprava hodin už nepřepisuje navázaný historický příjem; vazba zůstává."""
        tx = FinanceTransaction(amount=1000, category="work", description="Work: X", transaction_type="income")
        self.db.add(tx)
        self.db.flush()
        self.db.add(WorkSession(date=date(2026, 10, 1), hours=4, project="Servind", hourly_rate=250,
                                finance_transaction_id=tx.id))
        self.db.commit()
        tx_id = tx.id
        plan = ms.resolve_mutation(self.db, "work_session", "update", {"text": "servind"}, {"hours": 6})
        self.assertEqual(plan["preview"]["warnings"], ["Navázaný příjem ve financích se nezmění."])
        self.assertNotIn("1 000", json.dumps(plan, ensure_ascii=False))
        result = ms.apply_mutation_plan(plan)
        db = self.fresh()
        ws = db.query(WorkSession).one()
        self.assertEqual((ws.hours, ws.finance_transaction_id), (6, tx_id))
        self.assertEqual(db.get(FinanceTransaction, tx_id).amount, 1000)
        self.assertFalse(any(lg.area == "finance" for lg in db.query(ActivityLog).all()))
        self.assertNotIn("linked_income", json.dumps(result["undo"]))

    def test_goal_complete_sets_progress_for_manual_goal(self):
        self.db.add(Goal(area="personal", title="Přečíst knihu", status="active", progress=40, tracking_type="manual"))
        self.db.commit()
        plan = ms.resolve_mutation(self.db, "goal", "complete", {"text": "knihu"})
        self.assertIn("100 %", plan["preview"]["warnings"][0])
        ms.apply_mutation_plan(plan)
        g = self.fresh().query(Goal).one()
        self.assertEqual((g.status, g.progress), ("completed", 100))

    def test_memory_delete_is_soft(self):
        self.db.add(Memory(area="wot", category="plan", content="Po VZ.55 CS linie", importance=7, active=True))
        self.db.commit()
        plan = ms.resolve_mutation(self.db, "memory", "delete", {"text": "VZ.55"})
        ms.apply_mutation_plan(plan)
        m = self.fresh().query(Memory).one()
        self.assertFalse(m.active)
        with self.assertRaises(ms.MutationRefused):  # neaktivní paměť už není cíl
            ms.resolve_mutation(self.fresh(), "memory", "delete", {"text": "VZ.55"})

    def test_exam_and_grind_edit(self):
        s = Subject(name="Fyzika")
        self.db.add(s)
        self.db.flush()
        self.db.add_all([Exam(title="Zkouška", subject_id=s.id, status="upcoming", exam_date=date(2027, 1, 10)),
                         WotGrind(tank="VZ.55", xp_remaining=40000, priority="high", status="active")])
        self.db.commit()
        ms.apply_mutation_plan(ms.resolve_mutation(self.db, "school_exam", "update", {"text": "fyzika"},
                                                   {"exam_date": "2027-01-17"}))
        ms.apply_mutation_plan(ms.resolve_mutation(self.fresh(), "wot_grind", "update", {"text": "vz.55"},
                                                   {"xp_remaining": 12000}))
        db = self.fresh()
        self.assertEqual(db.query(Exam).one().exam_date, date(2027, 1, 17))
        self.assertEqual(db.query(WotGrind).one().xp_remaining, 12000)

    def test_invalid_plans_are_rejected_before_touching_db(self):
        self.seed_work()
        bad = [
            {}, {"version": 2},
            {"version": 1, "entity": "work_session", "action": "complete", "targets": [{"id": 1}]},
            {"version": 1, "entity": "work_session", "action": "update", "targets": [],
             "changes": {"hours": 1}},
            {"version": 1, "entity": "work_session", "action": "update",
             "targets": [{"id": 1, "snapshot": {}}], "changes": {"evil": 1}},
        ]
        for plan in bad:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                ms.apply_mutation_plan(plan)
        self.assertEqual(sorted(s.hours for s in self.fresh().query(WorkSession).all()), [1, 3, 3.5, 8])


if __name__ == "__main__":
    unittest.main()
