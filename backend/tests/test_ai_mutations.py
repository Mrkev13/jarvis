"""Phase B end-to-end (fake LLM): modify_records → pending akce s plánem → potvrzení / zamítnutí přes
stávající pending architekturu (execute_confirm_action, reject_pending, /actions/confirm, /ai/reject)."""
import json
import os
import sys
import types
import unittest
from datetime import date
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
import mutation_service  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Assignment, FinanceTransaction, PendingAction, Subject, WorkSession  # noqa: E402


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _call(name, args, call_id="c1"):
    return types.SimpleNamespace(id=call_id, function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))


def _modify(**args):
    return _message(tool_calls=[_call("modify_records", args)])


class AiMutationFlowTestCase(unittest.TestCase):
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
        # MRK-60: obecný AI mutační tok se ověřuje na práci (Finance už AI entita není).
        db.add_all([
            WorkSession(date=date(2026, 10, 1), hours=3, project="Servind", hourly_rate=300, description="workshop"),
            WorkSession(date=date(2026, 10, 2), hours=3.5, project="Servind", hourly_rate=300,
                        description="workshop s kolegy"),
            WorkSession(date=date(2026, 10, 2), hours=1, project="Ostatní", hourly_rate=0,
                        description="testovací směna"),
            Assignment(title="Esej o ústavě", subject_id=law.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Sada příkladů", subject_id=math.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Projekt", subject_id=math.id, status="todo", due_date=date(2026, 10, 10)),
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
            patch.object(mutation_service, "SessionLocal", self.Session),
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
    def _ask(self, text, script):
        self.script = list(script)
        result = ai.ask_ai([{"role": "user", "content": text}])
        self.assertEqual(self.script, [], "nevyužité odpovědi fake modelu")
        return result

    def _hours(self):
        db = self.Session()
        try:
            return {s.description: s.hours for s in db.query(WorkSession).all()}
        finally:
            db.close()

    def _pending_rows(self):
        db = self.Session()
        try:
            return [(p.id, p.tool, p.status) for p in db.query(PendingAction).all()]
        finally:
            db.close()

    def _last_tool_result(self):
        return json.loads(self.calls[-1]["messages"][-1]["content"])

    def _propose_edit(self):
        result = self._ask("změň poslední práci na Servind na 4,5 hodiny", [
            _modify(entity="work_session", action="update",
                    target={"text": "workshop", "latest": True}, changes={"hours": 4.5}),
            _message(content="Připravil jsem změnu k potvrzení."),
        ])
        self.assertEqual(len(result["pending_actions"]), 1)
        return result["pending_actions"][0]

    # ---- tests ----
    def test_edit_creates_pending_with_preview_and_no_mutation(self):
        pending = self._propose_edit()
        self.assertEqual(pending["tool"], "modify_records")
        preview = pending["preview"]
        self.assertEqual(preview["kind"], "update")
        self.assertEqual(preview["count"], 1)
        self.assertIn("3,5 h", preview["items"][0]["label"])
        self.assertEqual(preview["items"][0]["changes"][0]["old"], "3,5")
        self.assertEqual(preview["items"][0]["changes"][0]["new"], "4,5")
        self.assertIn("plan", pending["arguments"])
        self.assertEqual(self._hours()["workshop s kolegy"], 3.5, "nic se nesmí provést před potvrzením")
        self.assertEqual(self._last_tool_result()["status"], "confirmation_required")
        self.assertIn("modify_records", {t["function"]["name"] for t in self.calls[0]["tools"]})
        self.assertNotIn("add_work_session", {t["function"]["name"] for t in self.calls[0]["tools"]})

    def test_confirm_audit_text_is_human_readable(self):
        """Roadmap 4C: Aktivita ukazuje „Upravená data (AI): …", ne „Potvrzena akce modify_records (plan=…)"."""
        pending = self._propose_edit()
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        db = self.Session()
        try:
            approve = [a.summary for a in db.query(ActivityLog).filter_by(area="ai", action_type="approve").all()]
        finally:
            db.close()
        self.assertEqual(len(approve), 1)
        self.assertTrue(approve[0].startswith("Upravená data (AI): "), approve[0])
        self.assertNotIn("modify_records", approve[0])
        self.assertNotIn("=", approve[0])

    def test_confirm_mutates_exactly_the_target_once(self):
        pending = self._propose_edit()
        first = ai.execute_confirm_action(pending["id"])
        self.assertTrue(first["ok"], first)
        self.assertEqual(self._hours(), {"workshop": 3, "workshop s kolegy": 4.5, "testovací směna": 1})
        second = ai.execute_confirm_action(pending["id"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"], "action_already_processed")
        self.assertEqual(self._pending_rows()[0][2], "executed")

    def test_reject_never_mutates(self):
        pending = self._propose_edit()
        db = self.Session()
        try:
            ai.reject_pending(db, pending["id"])
        finally:
            db.close()
        self.assertEqual(self._hours()["workshop s kolegy"], 3.5)
        self.assertEqual(self._pending_rows()[0][2], "rejected")
        after = ai.execute_confirm_action(pending["id"])
        self.assertFalse(after["ok"])
        self.assertEqual(self._hours()["workshop s kolegy"], 3.5)

    def test_delete_pending_and_confirm(self):
        result = self._ask("smaž poslední testovací směnu v práci", [
            _modify(entity="work_session", action="delete", target={"text": "testovací", "latest": True}),
            _message(content="Připravil jsem smazání k potvrzení."),
        ])
        pending = result["pending_actions"][0]
        self.assertEqual(pending["preview"]["kind"], "delete")
        self.assertIn("Ostatní", pending["preview"]["items"][0]["label"])
        self.assertIn("testovací směna", self._hours())
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        self.assertNotIn("testovací směna", self._hours())

    def test_complete_assignment_by_subject(self):
        result = self._ask("označ úkol z práva jako hotový", [
            _modify(entity="school_assignment", action="complete", target={"text": "právo"}),
            _message(content="Připraveno."),
        ])
        pending = result["pending_actions"][0]
        self.assertEqual(pending["preview"]["kind"], "complete")
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        db = self.Session()
        try:
            statuses = {a.title: a.status for a in db.query(Assignment).all()}
        finally:
            db.close()
        self.assertEqual(statuses, {"Esej o ústavě": "done", "Sada příkladů": "todo", "Projekt": "todo"})

    def test_ambiguous_target_creates_no_pending_action(self):
        result = self._ask("smaž ten záznam práce", [
            _modify(entity="work_session", action="delete", target={"date_from": "2026-09-01"}),
            _message(content="Který záznam myslíš?"),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self._pending_rows(), [])
        tool_result = self._last_tool_result()
        self.assertEqual((tool_result["status"], tool_result["error"]), ("not_prepared", "ambiguous_target"))
        self.assertEqual(len(tool_result["candidates"]), 3)
        self.assertEqual(len(self._hours()), 3)

    def test_finance_entity_from_model_is_refused(self):
        """MRK-60: model, který si Finance entitu vymyslí, nedostane pending akci ani data transakcí."""
        db = self.Session()
        db.add(FinanceTransaction(amount=320, category="Jídlo", description="oběd", transaction_type="expense"))
        db.commit()
        db.close()
        result = self._ask("smaž ten záznam práce", [
            _modify(entity="finance_transaction", action="delete", target={"text": "oběd"}),
            _message(content="To nejde."),
        ])
        self.assertEqual(result["pending_actions"], [])
        tool_result = self._last_tool_result()
        self.assertEqual((tool_result["status"], tool_result["error"]), ("not_prepared", "unsupported_entity"))
        self.assertNotIn("oběd", json.dumps(tool_result, ensure_ascii=False))
        self.assertEqual(self._pending_rows(), [])

    def test_wrong_or_missing_id_creates_no_pending_action(self):
        for target in ({"id": 999}, {"id": "x"}):
            with self.subTest(target=target):
                result = self._ask("smaž ten záznam práce", [
                    _modify(entity="work_session", action="delete", target=target),
                    _message(content="Ten záznam nevidím."),
                ])
                self.assertEqual(result["pending_actions"], [])
                self.assertEqual(self._last_tool_result()["status"], "not_prepared")
        self.assertEqual(self._pending_rows(), [])

    def test_malformed_arguments_create_no_pending_action(self):
        result = self._ask("smaž ten záznam práce", [
            _modify(entity="work_session"),  # chybí action i target
            _message(content="Upřesni prosím."),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self._last_tool_result()["error"], "invalid_arguments")

    def test_stale_target_fails_safely_on_confirm(self):
        pending = self._propose_edit()
        db = self.Session()
        try:
            ws = db.query(WorkSession).filter(WorkSession.description == "workshop s kolegy").one()
            ws.hours = 9
            db.commit()
        finally:
            db.close()
        outcome = ai.execute_confirm_action(pending["id"])
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["error"], "execution_failed")
        self.assertEqual(self._hours()["workshop s kolegy"], 9)
        self.assertEqual(self._pending_rows()[0][2], "failed")

    def test_batch_complete_success_and_reject(self):
        result = self._ask("označ všechny dnešní úkoly jako hotové", [
            _modify(entity="school_assignment", action="complete",
                    target={"date": "2026-10-03", "all_matching": True}),
            _message(content="Připraveno ke potvrzení: 2 úkoly."),
        ])
        pending = result["pending_actions"][0]
        self.assertEqual(pending["preview"]["count"], 2)
        self.assertEqual(len(pending["preview"]["items"]), 2)

        db = self.Session()
        try:
            ai.reject_pending(db, pending["id"])
            self.assertEqual(db.query(Assignment).filter(Assignment.status == "done").count(), 0)
        finally:
            db.close()

        result = self._ask("označ všechny dnešní úkoly jako hotové", [
            _modify(entity="school_assignment", action="complete",
                    target={"date": "2026-10-03", "all_matching": True}),
            _message(content="Připraveno."),
        ])
        self.assertTrue(ai.execute_confirm_action(result["pending_actions"][0]["id"])["ok"])
        db = self.Session()
        try:
            done = sorted(a.title for a in db.query(Assignment).filter(Assignment.status == "done").all())
        finally:
            db.close()
        self.assertEqual(done, ["Esej o ústavě", "Sada příkladů"])

    def test_mutation_tool_not_routed_without_write_intent_is_refused(self):
        result = self._ask("kolik hodin jsem odpracoval?", [
            _modify(entity="work_session", action="delete", target={"text": "workshop", "latest": True}),
            _message(content="Odpracoval jsi 7,5 h."),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self._last_tool_result()["error"], "write_not_available")
        self.assertEqual(self._pending_rows(), [])

    def test_create_behaviour_unchanged(self):
        args = {"date_value": "2026-10-03", "hours": 2, "project": "Contoso", "hourly_rate": 300,
                "description": "nový"}
        result = self._ask("zapiš práci 2 hodiny na Contoso za 300 Kč/h", [
            _message(tool_calls=[_call("add_work_session", args)]),
            _message(content="Připravil jsem změnu k potvrzení."),
        ])
        pending = result["pending_actions"][0]
        self.assertEqual(pending["arguments"], args)  # create akce dál ukládá argumenty modelu
        self.assertNotIn("preview", pending)
        self.assertNotIn("modify_records", {t["function"]["name"] for t in self.calls[0]["tools"]})
        outcome = ai.execute_confirm_action(pending["id"])
        self.assertTrue(outcome["ok"])
        self.assertEqual(self._hours()["nový"], 2)
        db = self.Session()
        try:
            self.assertEqual(db.query(FinanceTransaction).count(), 0, "MRK-60: práce Finance nezapisuje")
        finally:
            db.close()

    def test_audit_log_for_confirmed_mutation(self):
        pending = self._propose_edit()
        ai.execute_confirm_action(pending["id"])
        db = self.Session()
        try:
            logs = db.query(ActivityLog).order_by(ActivityLog.id).all()
        finally:
            db.close()
        item_log = next(lg for lg in logs if lg.area == "work")
        self.assertEqual((item_log.action_type, item_log.user_context), ("update", "ai_confirm"))
        self.assertTrue(item_log.summary.startswith("Upraveno (AI): "), item_log.summary)  # akce z Dnes = „(Dnes)"
        self.assertEqual(json.loads(item_log.delta_json)["hours"], {"old": 3.5, "new": 4.5})
        approve = next(lg for lg in logs if lg.area == "ai")
        self.assertEqual(approve.action_type, "approve")
        self.assertIn("Upravit: pracovní záznam", approve.summary)
        self.assertLessEqual(len(approve.summary), 500)

    # ---- odpověď u návrhu nesmí tvrdit, že se změna už stala (regrese live Phase B C) ----
    _CLAIMS = ("uložen", "označen", "změnil", "smazán", "hotov", "přidal")

    def _assert_waiting_answer(self, result):
        self.assertEqual(len(result["pending_actions"]), 1)
        self.assertEqual(result["answer"], ai.PENDING_CONFIRMATION_ANSWER)
        for claim in self._CLAIMS:
            self.assertNotIn(claim, result["answer"].lower())

    def test_create_proposal_cannot_claim_execution(self):
        args = {"date_value": "2026-10-03", "hours": 2, "project": "Contoso", "hourly_rate": 300,
                "description": "nový"}
        result = self._ask("zapiš práci 2 hodiny na Contoso za 300 Kč/h", [
            _message(tool_calls=[_call("add_work_session", args)]),
            _message(content="Práce 2 h na Contoso byla uložena."),
        ])
        self._assert_waiting_answer(result)
        self.assertNotIn("nový", self._hours())

    def test_edit_proposal_cannot_claim_execution(self):
        result = self._ask("změň práci workshop s kolegy na 4,5 hodiny", [
            _modify(entity="work_session", action="update", target={"text": "workshop s kolegy"},
                    changes={"hours": 4.5}),
            _message(content="Změnil jsem hodiny na 4,5."),
        ])
        self._assert_waiting_answer(result)
        self.assertEqual(self._hours()["workshop s kolegy"], 3.5)

    def test_delete_proposal_cannot_claim_execution(self):
        result = self._ask("smaž testovací směnu v práci", [
            _modify(entity="work_session", action="delete", target={"text": "testovací"}),
            _message(content="Testovací směna byla smazána."),
        ])
        self._assert_waiting_answer(result)
        self.assertIn("testovací směna", self._hours())

    def test_complete_proposal_cannot_claim_execution(self):
        result = self._ask("označ úkol z práva jako hotový", [
            _modify(entity="school_assignment", action="complete", target={"text": "právo"}),
            _message(content="Úkol z práva byl označen jako hotový."),
        ])
        self._assert_waiting_answer(result)
        self.assertEqual(self._assignment_statuses()["Esej o ústavě"], "todo")

    def test_batch_proposal_cannot_claim_execution(self):
        result = self._ask("označ všechny dnešní úkoly jako hotové", [
            _modify(entity="school_assignment", action="update", target={"date": "2026-10-03", "all_matching": True},
                    changes={"status": "done"}),
            _message(content="Oba dnešní úkoly jsou hotové."),
        ])
        self._assert_waiting_answer(result)
        self.assertEqual(result["pending_actions"][0]["preview"]["count"], 2)
        self.assertEqual(set(self._assignment_statuses().values()), {"todo"})

    def test_answer_without_pending_action_is_kept(self):
        # Odmítnutý/nejednoznačný návrh (žádná pending akce) → doptání modelu zůstává beze změny.
        result = self._ask("smaž ten záznam práce", [
            _modify(entity="work_session", action="delete", target={}),
            _message(content="Který záznam myslíš?"),
        ])
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(result["answer"], "Který záznam myslíš?")

    def test_success_is_reported_normally_after_actual_confirmation(self):
        result = self._ask("označ úkol z práva jako hotový", [
            _modify(entity="school_assignment", action="complete", target={"text": "právo"}),
            _message(content="Úkol z práva byl označen jako hotový."),
        ])
        outcome = ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertTrue(outcome["ok"], outcome)  # UI z toho zobrazí „✅ Hotovo"
        self.assertEqual(self._assignment_statuses()["Esej o ústavě"], "done")

    def _assignment_statuses(self):
        db = self.Session()
        try:
            return {a.title: a.status for a in db.query(Assignment).all()}
        finally:
            db.close()

    def test_write_requests_skip_the_planner_fast_path(self):
        self.assertIsNone(main.detect_planner_intent("označ všechny dnešní úkoly jako hotové"))
        self.assertIsNotNone(main.detect_planner_intent("co mám dělat dnes"))
        self.assertIsNotNone(main.detect_planner_intent("co mám dělat tento týden"))


class MutationEndpointAuthTestCase(unittest.TestCase):
    """Confirm/reject endpointy zůstávají za session auth; reject přes HTTP nemutuje data."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = self.Session()
        db.add(WorkSession(date=date(2026, 10, 2), hours=1, project="Ostatní", hourly_rate=0,
                           description="testovací směna"))
        db.commit()
        plan = mutation_service.resolve_mutation(db, "work_session", "delete", {"text": "testovací"})
        self.pending_id = ai._store_pending_action(db, "modify_records", {"plan": plan}, ttl_minutes=30)
        db.close()
        self._patches = [
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(mutation_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH",
                         bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode("utf-8")),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _count(self):
        db = self.Session()
        try:
            return db.query(WorkSession).count()
        finally:
            db.close()

    def test_confirm_and_reject_require_session(self):
        self.assertEqual(self.client.post("/actions/confirm", json={"action_id": self.pending_id}).status_code, 401)
        self.assertEqual(self.client.post(f"/ai/reject/{self.pending_id}").status_code, 401)
        self.assertEqual(self._count(), 1)

    def test_http_reject_then_confirm_does_not_mutate(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
        r = self.client.post(f"/ai/reject/{self.pending_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "rejected")
        confirm = self.client.post("/actions/confirm", json={"action_id": self.pending_id}).json()
        self.assertFalse(confirm["ok"])
        self.assertEqual(self._count(), 1)

    def test_http_confirm_executes_plan(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
        r = self.client.post("/actions/confirm", json={"action_id": self.pending_id}).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["count"], 1)
        self.assertEqual(self._count(), 0)


if __name__ == "__main__":
    unittest.main()
