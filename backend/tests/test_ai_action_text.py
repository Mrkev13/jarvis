"""Roadmap 4C: texty AI akcí v Aktivitě – lidské popisky místo interních názvů toolů a „k=v"."""
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from text_utils import AI_TOOL_LABELS_CZ, ai_action_details, ai_action_label, ai_action_summary  # noqa: E402

NB = " "


class AiActionTextTestCase(unittest.TestCase):
    def test_every_write_tool_has_a_label(self):
        os.environ.setdefault("GROQ_API_KEY", "x")
        import tool_registry

        names = {s.name for s in tool_registry.WRITE_SPECS}
        self.assertEqual(names - set(AI_TOOL_LABELS_CZ), set(), "chybí popisek pro nový WRITE tool")
        self.assertEqual(ai_action_label("something_new"), "Akce AI")

    def test_work_session_summary(self):
        s = ai_action_summary("add_work_session", {"date_value": "2026-10-02", "hours": 6.5, "project": "Klient XYZ",
                                                   "hourly_rate": 375})
        self.assertEqual(s, f"Přidán pracovní záznam (AI): 2. 10. 2026 · 6,5{NB}h · Klient XYZ")
        self.assertNotIn("add_work_session", s)
        self.assertNotIn("=", s)

    def test_finance_and_other_tools(self):
        self.assertEqual(ai_action_details("add_finance_transaction",
                                           {"amount": 189.9, "category": "food", "transaction_type": "expense"}),
                         f"Výdaj 189,90{NB}Kč · food")
        self.assertEqual(ai_action_details("add_school_exam", {"title": "Fyzika", "exam_date": "2026-10-15"}),
                         "Fyzika · termín 15. 10. 2026")
        self.assertEqual(ai_action_details("update_wot_resource", {"resource": "free_xp", "amount": 184000}),
                         f"Free XP: 184{NB}000")
        self.assertEqual(ai_action_details("upsert_goal", {"title": "Rezerva", "progress": 40}), "Rezerva · 40 %")
        self.assertEqual(ai_action_details("save_memory", {"content": "Učím se ráno"}), "Učím se ráno")

    def test_plan_preview_tools(self):
        args = {"plan": {"preview": {"title": "Smazat transakce", "count": 3, "items": []}}}
        self.assertEqual(ai_action_summary("modify_records", args),
                         "Upravená data (AI): Smazat transakce (3 záznamy)")
        one = {"plan": {"preview": {"title": "Nová připomínka", "count": 1, "items": [{"label": "Zalít květiny"}]}}}
        self.assertEqual(ai_action_summary("add_reminder", one), "Přidána připomínka (AI): Nová připomínka: Zalít květiny")
        self.assertEqual(ai_action_summary("undo_change", {}), "Vrácená změna (AI)")


if __name__ == "__main__":
    unittest.main()
