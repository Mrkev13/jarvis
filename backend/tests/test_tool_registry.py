import inspect
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import ai  # noqa: E402
import tool_registry as reg  # noqa: E402


class ToolRegistryTestCase(unittest.TestCase):
    def test_registry_is_the_source_of_ai_tool_lists(self):
        self.assertEqual(ai.TOOLS, [s.schema for s in reg.TOOL_SPECS])
        self.assertEqual(set(ai.READ_TOOL_FUNCTIONS), {s.name for s in reg.READ_SPECS})
        self.assertEqual(ai.WRITE_TOOL_NAMES, {s.name for s in reg.WRITE_SPECS})
        for spec in reg.TOOL_SPECS:
            self.assertIs(ai.TOOL_FUNCTIONS[spec.name], spec.func)

    def test_every_spec_is_complete(self):
        for spec in reg.TOOL_SPECS:
            with self.subTest(spec.name):
                self.assertIn(spec.kind, (reg.READ, reg.WRITE))
                self.assertTrue(spec.areas, "každý tool musí mít aspoň jednu oblast pro routing")
                self.assertLessEqual(set(spec.areas), reg.ALL_AREAS)
                self.assertEqual(spec.schema["function"]["name"], spec.name)
                self.assertTrue(callable(spec.func))
                for req in spec.requires:
                    self.assertFalse(reg.TOOLS_BY_NAME[req].is_write, "requires smí odkazovat jen na read tooly")
                if spec.is_write:
                    self.assertFalse(spec.covered_by_context)
                    self.assertFalse(spec.takes_db)

    def test_schema_params_exist_on_the_callable(self):
        for spec in reg.TOOL_SPECS:
            params = inspect.signature(spec.func).parameters
            for name in spec.schema["function"]["parameters"]["properties"]:
                self.assertIn(name, params, f"{spec.name}: parametr {name} chybí ve funkci")
            if spec.takes_db:
                self.assertEqual(next(iter(params)), "db")

    def test_schemas_keep_registry_order(self):
        names = ["save_memory", "get_wot_resources", "add_finance_transaction"]
        got = [s["function"]["name"] for s in reg.schemas(names)]
        self.assertEqual(got, ["get_wot_resources", "add_finance_transaction", "save_memory"])


if __name__ == "__main__":
    unittest.main()
