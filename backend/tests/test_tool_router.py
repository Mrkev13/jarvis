"""Roadmap 3.0 A5: deterministický výběr toolů (tool_router), fallbacky a kill switch."""
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import ai  # noqa: E402
import tool_registry as reg  # noqa: E402
from llm_budget import estimate_fixed_overhead  # noqa: E402
from llm_config import DEFAULT_MAX_FIXED_TOKENS, load_llm_settings  # noqa: E402
from tool_router import (  # noqa: E402
    REASON_DISABLED,
    REASON_FALLBACK,
    REASON_GENERIC,
    REASON_GREETING,
    REASON_WRITE,
    REASON_WRITE_UNKNOWN,
    detect_write_intent,
    route_tools,
    routing_text,
    widen_route,
)

WRITE_NAMES = {s.name for s in reg.WRITE_SPECS}
READ_NAMES = {s.name for s in reg.READ_SPECS}

# Reprezentativní dotazy (A5 měření) – bez kontextu (nejhorší případ: prefetch nic nepokryl).
REPRESENTATIVE = {
    "school": "co mám zítra",
    "finance": "kolik jsem utratil za jídlo",
    "wot": "kolik mám kreditů ve WoT?",
    "greeting": "ahoj",
    "generic": "co si myslíš o Praze?",
    "finance_write": "přidej výdaj 300 Kč za oběd",
    "plan": "co mám dělat tento týden",
    "write_unknown": "zapiš to",
}


def _names(route):
    return set(route.names)


class RouteSelectionTestCase(unittest.TestCase):
    def test_kill_switch_exposes_every_tool(self):
        route = route_tools(["kolik mám kreditů ve WoT?"], enabled=False)
        self.assertFalse(route.routed)
        self.assertEqual(route.reason, REASON_DISABLED)
        self.assertEqual(list(route.names), [s.name for s in reg.TOOL_SPECS])

    def test_env_flag_controls_routing(self):
        self.assertTrue(load_llm_settings({}).tool_routing)
        self.assertFalse(load_llm_settings({"AI_TOOL_ROUTING": "false"}).tool_routing)
        self.assertTrue(load_llm_settings({"AI_TOOL_ROUTING": "true"}).tool_routing)

    def test_greeting_gets_no_tools(self):
        for msg in ("ahoj", "Díky!", "dobrý den"):
            route = route_tools([msg])
            self.assertEqual(route.names, (), msg)
            self.assertEqual(route.reason, REASON_GREETING)

    def test_greeting_with_a_question_is_not_a_greeting(self):
        self.assertIn("get_wot_resources", route_tools(["ahoj, kolik mám kreditů ve WoT?"]).names)

    def test_generic_fallback_exposes_read_tools_only(self):
        route = route_tools([REPRESENTATIVE["generic"]])
        self.assertEqual(route.reason, REASON_GENERIC)
        self.assertEqual(_names(route), READ_NAMES)

    def test_typical_requests_expose_small_sets(self):
        for key in ("school", "finance", "wot", "finance_write"):
            with self.subTest(key):
                self.assertLessEqual(len(route_tools([REPRESENTATIVE[key]]).names), 7)

    def test_area_tools(self):
        self.assertEqual(_names(route_tools(["kolik mám kreditů ve WoT?"])), {"get_wot_resources", "get_wot_grinds"})
        self.assertEqual(_names(route_tools(["kolik mám postav v MFF na T4"])), {"get_mff_summary", "get_mff_characters"})
        self.assertEqual(_names(route_tools(["co se naposledy změnilo"])), {"get_recent_activity"})
        school = _names(route_tools(["jaké mám zkoušky z matiky?"]))
        self.assertEqual(school, {"get_school_subjects", "get_school_assignments", "get_school_exams"})
        self.assertIn("get_finance_transactions", _names(route_tools(["Ukaž mi posledních 5 finančních transakcí"])))

    def test_no_write_tools_without_write_intent(self):
        for msg in ("kolik jsem utratil za jídlo?", "co mám zítra", "jak jsem na tom", "Kolik stál oběd za 300 Kč?",
                    "jaké byly změny tento týden", "co si myslíš o Praze?"):
            with self.subTest(msg):
                self.assertFalse(_names(route_tools([msg])) & WRITE_NAMES)

    def test_write_intent_detection(self):
        for msg in ("přidej výdaj 300 Kč za oběd", "utratil jsem 200 za kafe", "oběd 150 Kč",
                    "zapiš mi 4 hodiny na Servind", "pamatuj si, že chci šetřit", "změň stav cíle na hotovo",
                    "nastav kredity na 2 000 000"):
            with self.subTest(msg):
                self.assertTrue(detect_write_intent(msg))
        for msg in ("kolik jsem utratil za jídlo?", "jaké byly změny", "kolik mám kreditů", "Co jsem dostal za úkol?",
                    "kolik stál oběd za 300 Kč?"):
            with self.subTest(msg):
                self.assertFalse(detect_write_intent(msg))

    def test_finance_write_exposes_only_finance_write_tool(self):
        route = route_tools([REPRESENTATIVE["finance_write"]])
        self.assertEqual(route.reason, REASON_WRITE)
        self.assertEqual(_names(route) & WRITE_NAMES, {"add_finance_transaction"})

    def test_memory_write_exposes_only_save_memory(self):
        route = route_tools(["pamatuj si, že chci šetřit na auto"])
        self.assertEqual(_names(route) & WRITE_NAMES, {"save_memory"})

    def test_write_with_unknown_area_exposes_all_write_tools(self):
        route = route_tools([REPRESENTATIVE["write_unknown"]])
        self.assertEqual(route.reason, REASON_WRITE_UNKNOWN)
        self.assertLessEqual(WRITE_NAMES, _names(route))

    def test_requirements_are_added(self):
        route = route_tools(["přidej mi zkoušku z matiky na 12. 1."])
        self.assertTrue({"add_school_exam", "get_school_subjects"} <= _names(route))
        self.assertIn("get_goals", _names(route_tools(["zapiš to"])))  # upsert_goal → get_goals

    def test_summary_tools_skipped_only_for_implied_areas_covered_by_context(self):
        covered = frozenset({"get_finance_summary", "get_work_summary", "get_goals_summary",
                             "get_notification_summary", "get_memories", "get_goals",
                             "get_school_assignments", "get_school_exams"})
        plan = route_tools(["co mám dělat tento týden"], covered_tools=covered)
        self.assertFalse(_names(plan) & {"get_finance_summary", "get_work_summary", "get_goals_summary",
                                         "get_notification_summary", "get_memories"})
        self.assertLessEqual(len(plan.names), 7)
        # Výslovný dotaz na finance: souhrn zůstává, i když ho kontext pokrývá.
        self.assertIn("get_finance_summary", route_tools(["kolik mám peněz?"], covered_tools=covered).names)

    def test_planner_required_tools_present_when_not_covered(self):
        route = route_tools(["co mám dělat tento týden"])
        self.assertTrue({"get_goals", "get_memories"} <= _names(route))

    def test_short_follow_up_uses_one_previous_user_turn(self):
        route = route_tools(["přidej výdaj 300 Kč za oběd", "a ještě 120 za kávu"])
        self.assertIn("add_finance_transaction", route.names)
        self.assertEqual(_names(route_tools(["kolik mám kreditů ve WoT?", "a gold?"])) & READ_NAMES,
                         {"get_wot_resources", "get_wot_grinds"})

    def test_only_one_previous_turn_and_only_for_short_follow_ups(self):
        # Write záměr dvě zprávy zpátky se nepřenáší.
        route = route_tools(["přidej výdaj 300 Kč za oběd", "kolik mám kreditů ve WoT?", "a gold?"])
        self.assertFalse(_names(route) & WRITE_NAMES)
        long_msg = "teď mi prosím napiš, jaké zkoušky mě čekají v příštích dvou týdnech"
        self.assertEqual(routing_text(["přidej výdaj 300 Kč za oběd", long_msg]), long_msg)

    def test_widen_route(self):
        read_only = widen_route(route_tools(["kolik mám kreditů ve WoT?"]))
        self.assertEqual(read_only.reason, REASON_FALLBACK)
        self.assertEqual(_names(read_only), READ_NAMES)
        with_write = widen_route(route_tools(["přidej výdaj 300 Kč za oběd"]))
        self.assertEqual(_names(with_write), READ_NAMES | WRITE_NAMES)
        disabled = route_tools(["x"], enabled=False)
        self.assertIs(widen_route(disabled), disabled)

    def test_shared_classifier_mff_area_and_word_start_overview(self):
        from context_service import classify_areas, is_planner_like
        self.assertEqual(classify_areas("kolik mám postav v MFF na T4"), {"mff"})  # „postav" není „stav"
        self.assertTrue(is_planner_like("stav mých cílů"))
        self.assertTrue(is_planner_like("jaký je stav financí"))

    def test_routing_is_deterministic(self):
        for msg in REPRESENTATIVE.values():
            self.assertEqual(route_tools([msg]), route_tools([msg]))

    def test_routed_requests_stay_within_fixed_budget(self):
        prompt = ai.build_system_prompt()
        for key, msg in REPRESENTATIVE.items():
            with self.subTest(key):
                total = estimate_fixed_overhead(prompt, route_tools([msg]).schemas).total
                self.assertLessEqual(total, DEFAULT_MAX_FIXED_TOKENS)
        self.assertLess(
            estimate_fixed_overhead(prompt, route_tools([REPRESENTATIVE["finance"]]).schemas).tool_tokens,
            estimate_fixed_overhead(prompt, ai.TOOLS).tool_tokens / 4,
        )


if __name__ == "__main__":
    unittest.main()
