"""Měření A5: kolik toolů a odhadovaných tokenů schémat pošle routing pro reprezentativní dotazy.

Offline – nevolá LLM ani DB (engine se jen vytvoří, žádný dotaz). Spuštění z kořene repa:
    python backend/scripts/measure_tool_routing.py
Sloupec „s kontextem" simuluje CURRENT STATE prefetch: pokryté tooly = sekce oblastí dotazu (A3).
"""
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
if not (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")):
    os.environ["GROQ_API_KEY"] = "offline-measurement"  # klient se vytvoří, ale nic nevolá

import ai  # noqa: E402
import context_service as cs  # noqa: E402
from llm_budget import estimate_prompt_tokens, estimate_tool_schema_tokens  # noqa: E402
from tool_router import route_tools  # noqa: E402

CASES = [
    ("school", "co mám zítra"),
    ("finance", "kolik jsem utratil za jídlo"),
    ("finance list", "Ukaž mi posledních 5 finančních transakcí"),
    ("WoT", "kolik mám kreditů ve WoT?"),
    ("greeting", "ahoj"),
    ("generic", "co si myslíš o Praze?"),
    ("finance write", "přidej výdaj 300 Kč za oběd"),
    ("plan week", "co mám dělat tento týden"),
    ("write, unknown area", "zapiš to"),
]


def _simulated_context(message: str) -> tuple[frozenset, frozenset]:
    areas = cs.classify_areas(message)
    covered = {tool for area in areas for tool in cs._COVERED_TOOLS.get(area, ())}
    if cs.is_planner_like(message):
        covered |= set(cs._COVERED_TOOLS[cs.AREA_MEMORY])
    return frozenset(areas), frozenset(covered)


def _tokens(schemas: list[dict]) -> int:
    return estimate_tool_schema_tokens(schemas) if schemas else 0


def main() -> None:
    prompt = estimate_prompt_tokens(ai.build_system_prompt())
    print(f"system prompt ~{prompt} tok; všechny tooly (AI_TOOL_ROUTING=false): {len(ai.TOOLS)} / ~{_tokens(ai.TOOLS)} tok")
    print(f"{'případ':22} {'route':19} {'bez kontextu':>16} {'s kontextem':>16}  tooly (s kontextem)")
    for label, message in CASES:
        bare = route_tools([message])
        areas, covered = _simulated_context(message)
        with_ctx = route_tools([message], context_areas=areas, covered_tools=covered)
        print(
            f"{label:22} {with_ctx.reason:19} "
            f"{len(bare.names):3} / ~{_tokens(bare.schemas):5} tok {len(with_ctx.names):3} / ~{_tokens(with_ctx.schemas):5} tok  "
            f"{', '.join(with_ctx.names) or '-'}"
        )


if __name__ == "__main__":
    main()
