"""MRK-81: každý statický návrh otázky (frontend/lib/aiSuggestions.ts) routing pošle do své oblasti – bez LLM.

Test čte frontendový seznam (jediný zdroj pravdy návrhů) a pro každý `prompt` ověří, že
`context_service.classify_areas` vybere deklarovanou `area`. Finance nikdy (MRK-60).
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

import context_service as cs  # noqa: E402

SOURCE = (BACKEND_DIR.parent / "frontend" / "lib" / "aiSuggestions.ts").read_text(encoding="utf-8")
ENTRY = re.compile(r'\{\s*prompt:\s*"([^"]+)",\s*module:\s*(null|"[a-z_]+"),\s*area:\s*"([a-z_]+)"')
SUGGESTIONS = [(p, None if m == "null" else m.strip('"'), a) for p, m, a in ENTRY.findall(SOURCE)]


def test_list_is_parsed():
    assert len(SUGGESTIONS) >= 8, "regex nečte aiSuggestions.ts – změnil se tvar?"
    assert SOURCE.count("{ prompt:") == len(SUGGESTIONS)


@pytest.mark.parametrize("prompt,module,area", SUGGESTIONS, ids=[p for p, _m, _a in SUGGESTIONS])
def test_suggestion_routes_to_its_area(prompt, module, area):
    assert area in cs.classify_areas(prompt), f"{prompt!r} → {sorted(cs.classify_areas(prompt))}"
    assert "finance" not in cs.classify_areas(prompt, implied=False)
    assert module != "finance"
