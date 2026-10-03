"""Roadmap 3.5: jeden parser proměnných prostředí – scheduler a služby se nesmí rozcházet."""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import briefing_service  # noqa: E402
import delivery_service  # noqa: E402
import weekly_review_service  # noqa: E402
from env_config import env_bool, env_int, env_str  # noqa: E402


class EnvConfigTestCase(unittest.TestCase):
    def test_bool_values(self):
        for raw, expected in [("1", True), ("true", True), (" TRUE ", True), ("yes", True), ("on", True),
                              ("0", False), ("false", False), ("no", False), ("off", False), ("nonsense", False)]:
            with self.subTest(raw=raw), patch.dict(os.environ, {"X_FLAG": raw}):
                self.assertIs(env_bool("X_FLAG", not expected), expected)

    def test_missing_or_blank_means_default(self):
        with patch.dict(os.environ, {"X_FLAG": "   "}):
            self.assertIs(env_bool("X_FLAG", True), True)
            self.assertEqual(env_str("X_FLAG", "d"), "d")
            self.assertEqual(env_int("X_FLAG", 7), 7)
        os.environ.pop("X_MISSING", None)
        self.assertIs(env_bool("X_MISSING", False), False)

    def test_int_minimum(self):
        with patch.dict(os.environ, {"X_INT": "5"}):
            self.assertEqual(env_int("X_INT", 60, minimum=60), 60)
            self.assertEqual(env_int("X_INT", 60), 5)

    def test_services_and_delivery_use_the_same_rules(self):
        # dřív: scheduler neznal "on" a mezery → job se nespustil, ale API hlásilo „zapnuto"
        with patch.dict(os.environ, {"DAILY_BRIEFING_ENABLED": " on ", "WEEKLY_REVIEW_ENABLED": "on"}):
            self.assertTrue(briefing_service.briefing_enabled())
            self.assertTrue(weekly_review_service.review_enabled())
            self.assertIs(env_bool("DAILY_BRIEFING_ENABLED", False), True)
        with patch.dict(os.environ, {"DAILY_BRIEFING_PUSH": "off", "WEEKLY_REVIEW_PUSH": "0"}):
            self.assertEqual(delivery_service.deliverable_types(), ("reminder",))
        with patch.dict(os.environ, {"DAILY_BRIEFING_PUSH": "", "WEEKLY_REVIEW_PUSH": ""}):
            self.assertEqual(delivery_service.deliverable_types(), ("reminder", "daily_briefing", "weekly_review"))


if __name__ == "__main__":
    unittest.main()
