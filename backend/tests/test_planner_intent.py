import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import detect_planner_intent  # noqa: E402

DAILY, WEEKLY, GOALS = "daily", "weekly", "goal_review"


def _mode(prompt: str) -> str | None:
    result = detect_planner_intent(prompt)
    return result[0] if result else None


class PlannerIntentRegressionTestCase(unittest.TestCase):
    def test_weekly_question_is_not_routed_as_daily(self):
        self.assertEqual(_mode("co mám dělat tento týden"), WEEKLY)
        self.assertEqual(_mode("co budu dělat tento týden"), WEEKLY)
        # „týdenní plán" obsahuje podřetězec „denní plán"
        self.assertEqual(_mode("týdenní plán"), WEEKLY)

    def test_daily_question_still_daily(self):
        self.assertEqual(_mode("co mám dělat dnes"), DAILY)

    def test_date_questions_fall_through_to_model(self):
        for prompt in (
            "jaké je dnes datum",
            "jaké je dnes datum a co mám zítra",
            "kolikátého je dnes",
            "jaký je dnes den",
            "který den je dnes",
            "kolik je hodin",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(_mode(prompt))

    def test_existing_planner_phrases_unchanged(self):
        # Směrování před opravou (snapshot) – kromě výše opravených frází se nesmí změnit.
        expected = {
            # chipy ve frontend/app/ai/page.tsx
            "Co mám dnes dělat?": DAILY,
            "Jaký mám plán na tento týden?": WEEKLY,
            "Jak si vedu s plněním cílů?": GOALS,
            # denní
            "co mám dělat": DAILY, "co budu dělat": DAILY, "co dnes dělat": DAILY, "dnešní plán": DAILY,
            "denní plán": DAILY, "daily": DAILY, "co je na programu": DAILY, "program na dnes": DAILY,
            "agenda na dnes": DAILY, "priority na dnes": DAILY, "dneska večer co dělat": DAILY, "dnes": DAILY,
            "plán na dnes": DAILY,
            # týdenní
            "weekly plan": WEEKLY, "co tento týden": WEEKLY, "plán na tento týden": WEEKLY,
            "priority tento týden": WEEKLY, "co na tento týden": WEEKLY, "tenhle týden": WEEKLY,
            "tento týden": WEEKLY,
            # cíle
            "jak se mi daří plnit cíle": GOALS, "přehled cílů": GOALS, "stagnují nějaké cíle?": GOALS,
            "jaký je progres cílů": GOALS, "plán cílů": GOALS,
            # mimo planner
            "přidej výdaj 300 Kč za oběd": None, "kolik mám kreditů": None, "ahoj": None,
            "jaká je moje finanční bilance": None, "co mám zítra": None,
            "pamatuj si že po VZ.55 chci CS linii": None,
        }
        for prompt, mode in expected.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(_mode(prompt), mode)


if __name__ == "__main__":
    unittest.main()
