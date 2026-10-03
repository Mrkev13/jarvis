"""Phase C: vrácení potvrzené AI změny – data uložená při provedení, undo jako pending akce, nejvýš jednou,
atomicky, stale = nic se nezmění, audit propojený s původní akcí."""
import json
import os
import sys
import types
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import auth_service  # noqa: E402
import main  # noqa: E402
import mutation_service as ms  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    ActivityLog, Assignment, FinanceTransaction, Goal, Memory, PendingAction, Subject, WorkSession,
)


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _call(name, args):
    return types.SimpleNamespace(id="c1", function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))


class UndoTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = self.Session()
        law, math = Subject(name="Právo"), Subject(name="Matematika")
        db.add_all([law, math])
        db.flush()
        db.add_all([
            FinanceTransaction(amount=300, category="Jídlo", description="oběd", transaction_type="expense",
                               created_at=datetime(2026, 10, 1, 10, 0)),
            FinanceTransaction(amount=1, category="Ostatní", description="testovací výdaj",
                               transaction_type="expense", created_at=datetime(2026, 10, 2, 11, 0)),
            Assignment(title="Esej o ústavě", subject_id=law.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Sada příkladů", subject_id=math.id, status="in_progress", due_date=date(2026, 10, 3)),
            Goal(area="personal", title="Přečíst knihu", status="active", progress=40, tracking_type="manual"),
            Memory(area="wot", category="plan", content="Po VZ.55 CS linie", importance=7, active=True),
        ])
        db.commit()
        db.close()
        self.script: list = []
        self.calls: list = []

        def fake_llm(api_messages, **kwargs):
            self.calls.append({"messages": [dict(m) for m in api_messages], **kwargs})
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(ms, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    # ---- helpers ----
    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def execute(self, entity, action, target, changes=None):
        """Phase B návrh + potvrzení přes stávající execute_confirm_action → id provedené akce."""
        def store(db):
            plan = ms.resolve_mutation(db, entity, action, target, changes)
            return ai._store_pending_action(db, "modify_records", {"plan": plan}, ttl_minutes=30)
        pid = self.q(store)
        outcome = ai.execute_confirm_action(pid)
        self.assertTrue(outcome["ok"], outcome)
        return pid, outcome

    def propose_and_confirm_undo(self, original_id):
        proposal = ai.propose_undo_action(original_id)
        self.assertTrue(proposal["ok"], proposal)
        return proposal, ai.execute_confirm_action(proposal["pending_action"]["id"])

    def status_of(self, pid):
        return self.q(lambda db: db.get(PendingAction, int(pid)).status)

    def amounts(self):
        return self.q(lambda db: {t.description: t.amount for t in db.query(FinanceTransaction).all()})

    def assignment_statuses(self):
        return self.q(lambda db: {a.title: a.status for a in db.query(Assignment).all()})


class UndoFlowTestCase(UndoTestBase):
    def test_confirm_reports_undo_available_and_stores_record(self):
        pid, outcome = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.assertTrue(outcome["result"]["undo_available"])
        self.assertNotIn("undo", outcome["result"], "řádková data pro undo se do UI neposílají")
        stored = self.q(lambda db: json.loads(db.get(PendingAction, int(pid)).arguments))
        record = stored["undo"]
        self.assertTrue(record["supported"])
        self.assertEqual(record["items"][0]["before"]["amount"], 300.0)
        self.assertEqual(record["items"][0]["after"]["amount"], 450.0)
        self.assertIn("plan", stored, "původní plán zůstává")

    def test_undo_edit_restores_previous_values(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450, "category": "Restaurace"})
        proposal = ai.propose_undo_action(pid)
        preview = proposal["pending_action"]["preview"]
        self.assertEqual(preview["kind"], "undo")
        self.assertEqual({c["label"]: (c["old"], c["new"]) for c in preview["items"][0]["changes"]},
                         {"Částka": ("450 Kč", "300 Kč"), "Kategorie": ("Restaurace", "Jídlo")})
        self.assertEqual(self.amounts()["oběd"], 450, "návrh undo nic nemění")
        outcome = ai.execute_confirm_action(proposal["pending_action"]["id"])
        self.assertTrue(outcome["ok"], outcome)
        self.assertFalse(outcome["result"].get("undo_available", False))
        tx = self.q(lambda db: db.query(FinanceTransaction).filter_by(description="oběd").one())
        self.assertEqual((tx.amount, tx.category), (300, "Jídlo"))
        self.assertEqual(self.status_of(pid), "undone")

    def test_undo_complete_restores_status_and_goal_progress(self):
        pid, _ = self.execute("goal", "complete", {"text": "knihu"})
        self.propose_and_confirm_undo(pid)
        goal = self.q(lambda db: db.query(Goal).one())
        self.assertEqual((goal.status, goal.progress), ("active", 40))

    def test_undo_batch_complete_restores_each_previous_status(self):
        pid, _ = self.execute("school_assignment", "complete", {"date": "2026-10-03", "all_matching": True})
        self.assertEqual(set(self.assignment_statuses().values()), {"done"})
        proposal, outcome = self.propose_and_confirm_undo(pid)
        self.assertEqual(proposal["pending_action"]["preview"]["count"], 2)
        self.assertTrue(outcome["ok"])
        self.assertEqual(self.assignment_statuses(), {"Esej o ústavě": "todo", "Sada příkladů": "in_progress"})

    def test_undo_delete_restores_row_with_original_id_and_links(self):
        db = self.Session()
        tx = FinanceTransaction(amount=1000, category="work", description="Work: X", transaction_type="income",
                                created_at=datetime(2026, 10, 1, 8, 0))
        db.add(tx)
        db.flush()
        db.add(WorkSession(date=date(2026, 10, 1), hours=4, project="X", hourly_rate=250, finance_transaction_id=tx.id))
        db.commit()
        tx_id = tx.id
        db.close()
        pid, _ = self.execute("finance_transaction", "delete", {"id": tx_id})
        self.assertIsNone(self.q(lambda db: db.get(FinanceTransaction, tx_id)))
        self.propose_and_confirm_undo(pid)
        restored = self.q(lambda db: db.get(FinanceTransaction, tx_id))
        self.assertEqual((restored.amount, restored.description, restored.created_at),
                         (1000, "Work: X", datetime(2026, 10, 1, 8, 0)))
        self.assertEqual(self.q(lambda db: db.query(WorkSession).one().finance_transaction_id), tx_id)

    def test_undo_soft_delete_of_memory(self):
        pid, _ = self.execute("memory", "delete", {"text": "VZ.55"})
        self.propose_and_confirm_undo(pid)
        self.assertTrue(self.q(lambda db: db.query(Memory).one().active))

    def test_undo_work_edit_restores_linked_income(self):
        db = self.Session()
        tx = FinanceTransaction(amount=1000, category="work", description="Work: Servind", transaction_type="income")
        db.add(tx)
        db.flush()
        db.add(WorkSession(date=date(2026, 10, 1), hours=4, project="Servind", hourly_rate=250,
                           finance_transaction_id=tx.id))
        db.commit()
        tx_id = tx.id
        db.close()
        pid, _ = self.execute("work_session", "update", {"text": "servind"}, {"hours": 6})
        self.assertEqual(self.q(lambda db: db.get(FinanceTransaction, tx_id).amount), 1500)
        self.propose_and_confirm_undo(pid)
        self.assertEqual(self.q(lambda db: db.query(WorkSession).one().hours), 4)
        self.assertEqual(self.q(lambda db: db.get(FinanceTransaction, tx_id).amount), 1000)

    def test_second_undo_is_refused(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.propose_and_confirm_undo(pid)
        again = ai.propose_undo_action(pid)
        self.assertEqual((again["ok"], again["error"]), (False, "already_undone"))

    def test_two_open_undo_proposals_execute_at_most_once(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        first = ai.propose_undo_action(pid)["pending_action"]["id"]
        second = ai.propose_undo_action(pid)["pending_action"]["id"]
        self.assertTrue(ai.execute_confirm_action(first)["ok"])
        self.amounts()  # stav po prvním undo
        db = self.Session()
        tx = db.query(FinanceTransaction).filter_by(description="oběd").one()
        tx.amount = 450  # i kdyby se stav náhodou shodoval se snímkem PO, druhé undo nesmí proběhnout
        db.commit()
        db.close()
        outcome = ai.execute_confirm_action(second)
        self.assertFalse(outcome["ok"])
        self.assertEqual(self.amounts()["oběd"], 450)
        self.assertEqual(self.status_of(second), "failed")

    def test_stale_target_refused_at_proposal_and_at_confirm(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        proposal = ai.propose_undo_action(pid)  # návrh ještě platný
        db = self.Session()
        db.query(FinanceTransaction).filter_by(description="oběd").one().amount = 500  # ruční změna po AI změně
        db.commit()
        db.close()
        outcome = ai.execute_confirm_action(proposal["pending_action"]["id"])
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error"], "execution_failed")
        self.assertEqual(self.amounts()["oběd"], 500)
        self.assertEqual(self.status_of(pid), "executed", "nepovedené undo nepřepne původní akci")
        refused = ai.propose_undo_action(pid)
        self.assertEqual((refused["ok"], refused["error"]), (False, "stale_target"))

    def test_rejected_undo_causes_no_mutation(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        proposal = ai.propose_undo_action(pid)
        db = self.Session()
        try:
            ai.reject_pending(db, proposal["pending_action"]["id"])
        finally:
            db.close()
        self.assertEqual(self.amounts()["oběd"], 450)
        self.assertEqual(self.status_of(pid), "executed")
        self.assertFalse(ai.execute_confirm_action(proposal["pending_action"]["id"])["ok"])
        self.assertEqual(self.amounts()["oběd"], 450)

    def test_wrong_missing_or_unsuitable_original_ids(self):
        rejected_pid = self.q(lambda db: ai._store_pending_action(db, "modify_records", {"plan": {}}, ttl_minutes=30))
        self.q(lambda db: ai.reject_pending(db, rejected_pid))
        create_pid = self.q(lambda db: ai._store_pending_action(
            db, "add_finance_transaction", {"amount": 5, "category": "x", "transaction_type": "expense"}, ttl_minutes=30))
        ai.execute_confirm_action(create_pid)
        cases = [("999", "target_not_found"), ("abc", "invalid_target"), (rejected_pid, "not_executed"),
                 (create_pid, "target_not_found")]
        for action_id, code in cases:
            with self.subTest(action_id=action_id):
                out = ai.propose_undo_action(action_id)
                self.assertEqual((out["ok"], out["error"]), (False, code))
        self.assertEqual(self.q(lambda db: db.query(PendingAction).filter_by(tool="undo_change").count()), 0)

    def test_goal_delete_is_executed_but_not_undoable(self):
        pid, outcome = self.execute("goal", "delete", {"text": "knihu"})
        self.assertFalse(outcome["result"]["undo_available"])
        out = ai.propose_undo_action(pid)
        self.assertEqual(out["error"], "unsupported")

    def test_undo_window(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        later = ms.utc_now() + timedelta(hours=ms.UNDO_WINDOW_HOURS + 1)
        with patch.object(ms, "utc_now", lambda: later):
            self.assertEqual(ai.propose_undo_action(pid)["error"], "expired")

    def test_restore_is_atomic_when_one_item_fails(self):
        pid, _ = self.execute("school_assignment", "complete", {"date": "2026-10-03", "all_matching": True})
        proposal = ai.propose_undo_action(pid)
        calls = []
        original = ms._undo_item

        def flaky(db, ent, action, item, *, apply):
            if apply:
                calls.append(item["id"])
                if len(calls) == 2:
                    raise RuntimeError("DB výpadek")
            return original(db, ent, action, item, apply=apply)

        with patch.object(ms, "_undo_item", flaky):
            outcome = ai.execute_confirm_action(proposal["pending_action"]["id"])
        self.assertFalse(outcome["ok"])
        self.assertEqual(set(self.assignment_statuses().values()), {"done"}, "nic se nevrátilo")
        self.assertEqual(self.status_of(pid), "executed")
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="undo").count()), 0)

    def test_audit_links_undo_to_original_action(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.propose_and_confirm_undo(pid)
        logs = self.q(lambda db: db.query(ActivityLog).filter_by(action_type="undo").order_by(ActivityLog.id).all())
        item_log, summary_log = logs
        self.assertEqual((item_log.area, item_log.entity_type, item_log.user_context),
                         ("finance", "FinanceTransaction", "ai_confirm"))
        self.assertEqual(json.loads(item_log.delta_json)["undo_of_action"], int(pid))
        self.assertEqual((summary_log.area, summary_log.entity_type, summary_log.entity_id),
                         ("ai", "PendingAction", int(pid)))
        stored = self.q(lambda db: json.loads(db.get(PendingAction, int(pid)).arguments))
        self.assertIn("undone_at", stored["undo"])

    def test_unknown_or_tampered_undo_plans_fail_before_mutation(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        bad = [{}, {"version": 1, "kind": "undo"}, {"version": 1, "kind": "undo", "original_action_id": "x"},
               {"version": 1, "kind": "undo", "original_action_id": int(pid), "entity": "goal", "action": "update"}]
        for plan in bad:
            with self.subTest(plan=plan), self.assertRaises((ValueError, ms.StaleTarget)):
                ms.apply_undo_plan(plan)
        self.assertEqual(self.amounts()["oběd"], 450)
        self.assertEqual(self.status_of(pid), "executed")


class UndoViaAiTestCase(UndoTestBase):
    def _ask(self, text, script):
        self.script = list(script)
        result = ai.ask_ai([{"role": "user", "content": text}])
        self.assertEqual(self.script, [])
        return result

    def test_vrat_posledni_zmenu_creates_undo_pending(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        result = self._ask("vrať poslední změnu", [
            _message(tool_calls=[_call("undo_change", {"latest": True})]),
            _message(content="Připraveno."),
        ])
        self.assertEqual({t["function"]["name"] for t in self.calls[0]["tools"]} & {"undo_change", "modify_records",
                                                                                   "add_finance_transaction"},
                         {"undo_change"})
        pending = result["pending_actions"][0]
        self.assertEqual((pending["tool"], pending["preview"]["kind"]), ("undo_change", "undo"))
        self.assertEqual(pending["arguments"]["plan"]["original_action_id"], int(pid))
        self.assertEqual(self.amounts()["oběd"], 450)
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        self.assertEqual(self.amounts()["oběd"], 300)

    def test_ambiguous_undo_without_latest_asks(self):
        self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.execute("school_assignment", "complete", {"text": "právo"})
        result = self._ask("vrať tu změnu", [
            _message(tool_calls=[_call("undo_change", {})]),
            _message(content="Kterou změnu mám vrátit?"),
        ])
        self.assertEqual(result["pending_actions"], [])
        tool_result = json.loads(self.calls[-1]["messages"][-1]["content"])
        self.assertEqual((tool_result["status"], tool_result["error"]), ("not_prepared", "ambiguous_target"))
        self.assertEqual(len(tool_result["candidates"]), 2)

    def test_area_filter_picks_the_finance_change(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.execute("school_assignment", "complete", {"text": "právo"})
        result = self._ask("vrať poslední změnu ve financích", [
            _message(tool_calls=[_call("undo_change", {"area": "finance"})]),
            _message(content="Připraveno."),
        ])
        self.assertEqual(result["pending_actions"][0]["arguments"]["plan"]["original_action_id"], int(pid))

    def test_nothing_to_undo(self):
        result = self._ask("undo", [
            _message(tool_calls=[_call("undo_change", {"latest": True})]),
            _message(content="Není co vracet."),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(json.loads(self.calls[-1]["messages"][-1]["content"])["error"], "target_not_found")

    def test_undo_tool_not_exposed_without_undo_intent(self):
        result = self._ask("kolik jsem utratil za oběd?", [
            _message(tool_calls=[_call("undo_change", {"latest": True})]),
            _message(content="300 Kč."),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(json.loads(self.calls[-1]["messages"][-1]["content"])["error"], "write_not_available")


class UndoEndpointAuthTestCase(UndoTestBase):
    def setUp(self):
        super().setUp()
        extra = [
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH",
                         bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode("utf-8")),
        ]
        for p in extra:
            p.start()
        self._patches.extend(extra)
        self.client = TestClient(main.app)

    def test_undo_endpoint_requires_session_and_then_proposes_only(self):
        pid, _ = self.execute("finance_transaction", "update", {"text": "oběd"}, {"amount": 450})
        self.assertEqual(self.client.post("/actions/undo", json={"action_id": pid}).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
        body = self.client.post("/actions/undo", json={"action_id": pid}).json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["pending_action"]["preview"]["kind"], "undo")
        self.assertEqual(self.amounts()["oběd"], 450, "endpoint jen navrhuje, nevrací")
        confirm = self.client.post("/actions/confirm", json={"action_id": body["pending_action"]["id"]}).json()
        self.assertTrue(confirm["ok"])
        self.assertEqual(self.amounts()["oběd"], 300)


if __name__ == "__main__":
    unittest.main()
