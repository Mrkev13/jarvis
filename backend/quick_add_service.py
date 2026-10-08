"""Rychlé přidání (Roadmap 4E) – deterministický parser krátkých českých vět, bez LLM a bez zápisu.

parse(text) → náhled {kind, confidence, fields, display, warnings, needs_input, errors, ready}
pro čtyři typy: připomínka, finance, práce, škola (zkouška / úkol). Nic se neuhaduje potichu:
chybějící údaj = `needs_input` (otázka), neplatný = `errors`, odhad = `warnings` (viditelně v náhledu).

prepare(db, kind, fields) znovu ověří (upravená) pole a přes ai.prepare_write_action z nich udělá
BĚŽNOU pending akci existujícího WRITE toolu (add_reminder / add_finance_transaction / add_work_session /
add_school_exam / add_school_assignment) se zdrojem „quick_add". Zápis provede až /actions/confirm –
stejná cesta (atomické potvrzení, audit, vypršení) jako u návrhů AI.

Kalendář je pražský (time_utils), nikdy lokální čas serveru.

MRK-20: druhy dodávají moduly (`ModuleIntegrations.quick_add_rules` / `quick_add_kinds` v
<modul>_integrations.py, připomínka v core_integrations.py) nad sdíleným jádrem quick_add_text.py.
Tady zůstává globální politika: pořadí pravidel (číselná priorita, první shoda vyhrává – deterministicky),
gating vypnutých modulů, jistota, tvar odpovědi a ověření před zápisem.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from module_contracts import QuickAddKind, QuickAddRule
from module_registry import ModuleAccess, all_contributions, current_access
from quick_add_text import MAX_TEXT, Draft, Text
from time_utils import now_local, utc_now

__all__ = ["KINDS", "MAX_TEXT", "Draft", "QuickAddInvalid", "Text", "classify", "parse", "to_tool_call"]

# Statická tabulka ze VŠECH registrovaných druhů: klasifikace nezávisí na stavu modulů (text, který odpovídá jen
# vypnutému modulu, je „unknown" – žádné hádání jiného druhu); gating dělá parse/to_tool_call.
_RULES: tuple[QuickAddRule, ...] = tuple(sorted((rule for _owner, rule in all_contributions("quick_add_rules")),
                                               key=lambda rule: rule.priority))
_KINDS: dict[str, QuickAddKind] = {spec.kind: spec for _owner, spec in all_contributions("quick_add_kinds")}
KINDS = tuple(_KINDS)


def classify(t: Text) -> tuple[str, str]:
    """(druh, jistota): první pravidlo podle priority, které text rozpozná (dřív pevný řetězec if – stejné pořadí:
    výslovná připomínka > škola > práce > relativní čas / čas > peníze)."""
    for rule in _RULES:
        confidence = rule.detect(t)
        if confidence:
            return rule.kind, confidence
    return "unknown", "low"


def _context(spec: QuickAddKind | None, db: Session | None, overrides: dict) -> dict:
    ctx = dict(overrides)
    if spec is not None and spec.context is not None:
        for key, value in spec.context(db).items():
            ctx.setdefault(key, value)
    return ctx


def parse(text: str, *, db: Session | None = None, now_utc: datetime | None = None, subjects: list[dict] | None = None,
          access: ModuleAccess | None = None, context: dict | None = None) -> dict:
    """Náhled bez zápisu. `context` = data pro rozbor místo DB (testy); `subjects` = starší zkratka pro školu."""
    now_utc = now_utc or utc_now()
    t = Text(text)
    overrides = dict(context or {})
    if subjects is not None:
        overrides.setdefault("subjects", subjects)
    d = Draft()
    spec: QuickAddKind | None = None
    ctx = overrides
    if len(t.raw) < 2:
        d.kind = "empty"
    else:
        d.kind, d.confidence = classify(t)
        if d.kind in KINDS and not (access or current_access()).allows_quick_add_kind(d.kind):
            # Roadmap 6C: vypnutý modul = jako by druh neexistoval (nic se nepředvyplní ani neuloží).
            d.kind, d.confidence = "unknown", "low"
        spec = _KINDS.get(d.kind)
        if spec is not None:
            ctx = _context(spec, db, overrides)
            spec.parse(t, d, now_utc, ctx)
    if (d.needs_input or d.errors) and d.confidence == "high":
        d.confidence = "medium"
    today = now_local(now_utc).date()
    result = {
        "kind": d.kind,
        "confidence": d.confidence,
        "fields": d.fields,
        "display": spec.display(d.fields, ctx, today) if spec else {"title": "", "subtitle": "", "area": None},
        "warnings": d.warnings,
        "needs_input": d.needs_input,
        "errors": d.errors,
        "ready": d.kind in KINDS and not d.needs_input and not d.errors,
    }
    if spec is not None and spec.output is not None:
        result.update(spec.output(ctx))
    return result


# ---------- příprava zápisu (validace + pending akce) ----------


class QuickAddInvalid(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid")
        self.errors = errors


def to_tool_call(db: Session, kind: str, fields: dict, now_utc: datetime | None = None, *,
                 access: ModuleAccess | None = None) -> tuple[str, dict]:
    """Ověří pole z náhledu (po úpravách) a vrátí (WRITE tool, argumenty). Chyby → QuickAddInvalid."""
    if kind in KINDS and not (access or current_access()).allows_quick_add_kind(kind):
        # frontend se nikdy nebere za pravdu – ani ručně poslaný druh vypnutého modulu nic nevytvoří
        raise QuickAddInvalid([{"field": "kind", "message": "Tento modul je vypnutý."}])
    now_utc = now_utc or utc_now()
    today = now_local(now_utc).date()
    f = fields if isinstance(fields, dict) else {}
    d = Draft()
    spec = _KINDS.get(kind)
    if spec is None:
        d.error("kind", "Neznámý typ záznamu.")
        tool, args = "", {}
    else:
        tool, args = spec.to_tool_call(f, d, today, now_utc, db)
    if d.errors:
        raise QuickAddInvalid(d.errors)
    return tool, args
