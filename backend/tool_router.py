"""Deterministický routing AI toolů (Roadmap 3.0 A5).

Před prvním LLM voláním vybere z tool_registry malou sadu toolů podle dotazu – bez LLM, jen klíčová slova
(sdílené classify_areas z context_service + pár intentů). Sada platí pro všechna kola jednoho requestu.

Pravidla:
- Text pro klasifikaci = aktuální zpráva uživatele; u krátkého follow-upu („a zítra?", „ano") navíc nejvýš
  jedna předchozí zpráva uživatele. Shrnutí konverzace ani odpovědi asistenta se nepoužívají.
- READ tooly: podle oblastí dotazu (vč. implikovaných, stejně jako CURRENT STATE prefetch). Souhrnný tool
  (covered_by_context) se nepošle, když jeho oblast pokryl CURRENT STATE a uživatel se na ni výslovně neptá.
  Detailní tooly (explicit_only: předměty, historie cíle) jen při výslovně zmíněné oblasti.
- WRITE tooly: jen při deterministickém write záměru (sloveso typu „přidej/ulož/zapiš", oznamovací věta
  „utratil jsem…", částka v Kč nebo číslo v konkrétní oblasti mimo otázku / žádost o výpis). „Pamatuj si…" → jen save_memory. Oblast write záměru neznámá
  → všechny write tooly (bezpečný fallback – zápis stejně vyžaduje potvrzení v UI).
- Pozdrav bez dalšího obsahu → žádné tooly. Neznámý dotaz bez oblasti → všechny READ tooly.
- requires (např. add_school_exam → get_school_subjects) se doplní vždy.
- AI_TOOL_ROUTING=false → všechny tooly (dřívější chování).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from context_service import classify_areas, fold_text, is_planner_like
from module_registry import current_access
from planner_guard import PLANNER_REQUIRED_TOOLS
from tool_registry import (
    AREA_ACTIVITY,
    AREA_MEMORY,
    AREA_REMINDERS,
    READ_SPECS,
    TOOL_SPECS,
    TOOLS_BY_NAME,
    WRITE_SPECS,
    schemas,
)

REASON_DISABLED = "disabled"
REASON_GREETING = "greeting"
REASON_GENERIC = "generic"
REASON_AREAS = "areas"
REASON_WRITE = "areas+write"
REASON_WRITE_UNKNOWN = "write_unknown_area"
REASON_FALLBACK = "fallback"

SHORT_FOLLOW_UP_WORDS = 6
_FOLLOW_UP_PREFIXES = ("a ", "a co", "a kolik", "a kdy", "jsi si jist", "proc", "jeste", "tak ", "ano", "jo",
                       "ok", "dobre", "to ")

# Rozkazovací / zápisová slovesa (bez diakritiky, začátek slova).
_WRITE_VERB_RE = re.compile(
    r"\b(prida|pridej|pripis|zapis|zapsa|zaznamen|uloz|nastav|zmen(?:it|te|im)?\b|uprav|aktualiz|vytvor|zaloz|"
    r"oznac|pamatuj|zapamatuj|poznamen|dopln|prepis|zvys|sniz|odecti|pricti|add\b|save\b|update\b|"
    r"smaz|odstran|vymaz|zrus|oprav|posun|presun|deaktiv|delete\b|pripomen(?:\b|te\b)|odloz|snooze\b)"
)
# Phase B: úprava / mazání / dokončení EXISTUJÍCÍHO záznamu → modify_records (write_intent="mutate").
_MUTATION_VERB_RE = re.compile(
    r"\b(zmen(?:it|te|im)?\b|uprav|oprav|aktualiz|prepis|smaz|odstran|vymaz|zrus|oznac|posun|presun|deaktiv|"
    r"odloz|snooze\b|delete\b|update\b)"
)
# Phase C: vrácení provedené změny → undo_change (write_intent="undo").
_UNDO_VERB_RE = re.compile(r"\b(vrat(?:it|te)?\b|vraceni\b|undo\b|zpet\b|odvolej|anuluj)")
_MUTATION_STATEMENT_RE = re.compile(r"\b(je hotov|jsou hotov|mam hotov|uz je hotov|jsem dokoncil|jsem splnil)")
# Vytvoření nového záznamu – při současném mutačním slovese se create tooly posílají jen s tímto slovesem.
_CREATE_VERB_RE = re.compile(r"\b(prida|pridej|pripis|zapis|zapsa|zaznamen|uloz|vytvor|zaloz|pamatuj|zapamatuj|"
                             r"poznamen|pripomen(?:\b|te\b)|add\b|save\b)")
# Oznamovací věty o proběhlé události („utratil jsem 200 za oběd") – zápis jen mimo otázku.
_STATEMENT_RE = re.compile(
    r"\b(utratil|zaplatil|koupil|nakoupil|dostal|vydelal|odpracoval|pracoval jsem|splnil|dokoncil|odevzdal|"
    r"ziskal|prodal|platil|udelal jsem|napsal jsem|mam novy|mam novou|mam nove|je hotov|jsou hotov|mam hotov)"
)
_MEMORY_WRITE_RE = re.compile(r"\b(pamatuj|zapamatuj|uloz si|poznamenej si|zapis si)")
_AMOUNT_RE = re.compile(r"\d[\d\s.,]*\s?(kc|czk|korun)\b")
_QUESTION_START_RE = re.compile(
    r"^(kolik|kdy|kde|jak|co|proc|ktery|ktera|ktere|kteri|je |jsou|mam |mel |mela |byl|bylo|byla|muzu|lze)"
)
# Žádost o zobrazení dat („ukaž mi posledních 5 transakcí") – číslo v ní není zápis.
_READ_REQUEST_RE = re.compile(
    r"^(ukaz|vypis|zobraz|rekni|shrn|porovnej|spocit|najdi|vyhledej|chci vedet|potrebuju vedet|dej mi|napis mi)"
)
_DIGIT_RE = re.compile(r"\d")
_GREETING_RE = re.compile(
    r"^(ahoj|cau|cus|nazdar|zdravim|dobry den|dobre rano|dobry vecer|hey|hi|hello|diky|dekuji|dekuju|dik|"
    r"thanks|super|ok|okej|jasne|jak se mas)\b"
)
_INTENT_WORDS = {
    AREA_MEMORY: ("pamat", "pamet", "zapamatuj", "vzpomen", "memory", "uloz si", "poznamenej si"),
    AREA_ACTIVITY: ("aktivit", "zmeny", "zmenil", "zmenilo", "historie zmen", "naposledy", "co jsem delal",
                    "co se delo", "posledni zmen"),
}
_WRITE_AREAS = frozenset(a for s in WRITE_SPECS for a in s.areas)
# Oblasti, které mají aspoň jeden AI tool. Oblast poznaná jen podle slov (MRK-60: Finance) žádný nemá.
_TOOL_AREAS = frozenset(a for s in TOOL_SPECS for a in s.areas)


@dataclass(frozen=True)
class ToolRoute:
    names: tuple[str, ...]  # v pořadí registru
    reason: str
    areas: frozenset[str] = frozenset()
    write_intent: bool = False
    routed: bool = True  # False = všechny tooly (kill switch)

    @property
    def schemas(self) -> list[dict]:
        return schemas(self.names)

    def allows(self, tool_name: str) -> bool:
        return tool_name in self.names


def _ordered(names: set[str]) -> tuple[str, ...]:
    """Pořadí registru; Roadmap 6C: bez toolů, jejichž VŠECHNY oblasti patří modulům bez `ai_context`."""
    access = current_access()
    return tuple(s.name for s in TOOL_SPECS
                 if s.name in names and (not s.areas or any(access.allows_context_area(a) for a in s.areas)))


def _with_requirements(names: set[str]) -> set[str]:
    out = set(names)
    pending = list(names)
    while pending:
        for req in TOOLS_BY_NAME[pending.pop()].requires:
            if req not in out:
                out.add(req)
                pending.append(req)
    return out


def all_tools_route(reason: str = REASON_DISABLED) -> ToolRoute:
    return ToolRoute(_ordered({s.name for s in TOOL_SPECS}), reason, routed=False, write_intent=True)


def routing_text(user_texts: list[str]) -> str:
    """Aktuální zpráva + nejvýš jedna předchozí zpráva uživatele, pokud je aktuální krátký follow-up."""
    texts = [t for t in user_texts if (t or "").strip()]
    if not texts:
        return ""
    current = texts[-1]
    if len(texts) >= 2 and is_short_follow_up(current):
        return f"{texts[-2]}\n{current}"
    return current


def is_short_follow_up(message: str) -> bool:
    folded = fold_text(message).strip()
    return len(folded.split()) <= SHORT_FOLLOW_UP_WORDS or folded.startswith(_FOLLOW_UP_PREFIXES)


def _is_question(folded_line: str) -> bool:
    line = folded_line.strip()
    return "?" in line or bool(_QUESTION_START_RE.match(line))


def detect_write_intent(text: str) -> bool:
    """Deterministický write záměr; u otázek („kolik jsem utratil?") se oznamovací tvary nepočítají."""
    for line in fold_text(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if _WRITE_VERB_RE.search(line) or _UNDO_VERB_RE.search(line):
            return True
        if _is_question(line):
            continue
        if _STATEMENT_RE.search(line) or _AMOUNT_RE.search(line):
            return True
        # Oznamovací věta s číslem v konkrétní oblasti („dneska jsem byl 6 hodin v práci", „ve WoT mám 2 500 000 kreditů").
        if not _READ_REQUEST_RE.match(line) and _DIGIT_RE.search(line) and classify_areas(line, implied=False):
            return True
    return False


def detect_undo_intent(text: str) -> bool:
    """„vrať poslední změnu", „undo", „vezmi to zpět" – i v otázce („můžeš to vrátit?")."""
    return bool(_UNDO_VERB_RE.search(fold_text(text)))


def detect_mutation_intent(text: str) -> bool:
    """Záměr upravit / smazat / dokončit existující záznam (oznamovací „je hotový" jen mimo otázku)."""
    for line in fold_text(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if _MUTATION_VERB_RE.search(line):
            return True
        if not _is_question(line) and _MUTATION_STATEMENT_RE.search(line):
            return True
    return False


def intent_areas(text: str) -> frozenset[str]:
    folded = f" {fold_text(text)} "
    return frozenset(area for area, words in _INTENT_WORDS.items() if any(w in folded for w in words))


def _is_greeting(text: str) -> bool:
    folded = fold_text(text).strip()
    return bool(_GREETING_RE.match(folded)) and len(folded.split()) <= 5


def route_tools(
    user_texts: list[str],
    *,
    enabled: bool = True,
    context_areas: frozenset[str] = frozenset(),
    covered_tools: frozenset[str] = frozenset(),
    named_areas: frozenset[str] = frozenset(),
) -> ToolRoute:
    """Vybere tooly pro request. context_areas/covered_tools/named_areas pochází z CURRENT STATE (A3), pokud existuje.

    named_areas = oblasti zmíněné jménem záznamu z DB (název aktivní připomínky) – výslovná zmínka, ale
    write tooly té oblasti jen PŘIDÁ k ostatním (obyčejné slovo jako „oběd" nesmí vzít finance tooly).
    """
    if not enabled:
        return all_tools_route()

    text = routing_text(user_texts)
    intents = intent_areas(text)
    keyword_explicit = classify_areas(text, implied=False) | intents
    explicit = keyword_explicit | frozenset(named_areas)
    areas = classify_areas(text) | intents | frozenset(context_areas) | frozenset(named_areas)
    write_intent = detect_write_intent(text)

    if not areas and not write_intent and _is_greeting(text):
        return ToolRoute((), REASON_GREETING, areas, False)
    if not areas and not write_intent:
        return ToolRoute(_ordered({s.name for s in READ_SPECS}), REASON_GENERIC, areas, False)

    names: set[str] = set()
    for spec in READ_SPECS:
        if not set(spec.areas) & areas:
            continue
        asked = bool(set(spec.areas) & explicit)
        if spec.explicit_only and not asked:
            continue
        if spec.covered_by_context and spec.name in covered_tools and not asked:
            continue
        names.add(spec.name)
    if is_planner_like(text):
        names |= {t for t in PLANNER_REQUIRED_TOOLS if t not in covered_tools}

    reason = REASON_AREAS
    # MRK-60: zápis výslovně jen do oblasti bez AI toolů („přidej výdaj 300 Kč") nedostane náhradní write tooly
    # jiných oblastí – model odpoví, že to nejde, místo aby změnu zapsal jinam.
    if write_intent and explicit and not explicit & _TOOL_AREAS:
        write_intent = False
    if write_intent:
        folded = fold_text(text)
        mutate = detect_mutation_intent(text)
        undo = detect_undo_intent(text)
        # Úprava existujícího záznamu („změň výdaj na 450 Kč") nemá dostat create tool, pokud uživatel
        # zároveň výslovně nežádá i nový záznam – model by jinak mohl přidat místo upravit.
        create = not (mutate or undo) or bool(_CREATE_VERB_RE.search(folded))
        kinds = {k for k, on in (("mutate", mutate), ("create", create), ("undo", undo)) if on}
        candidates = [s for s in WRITE_SPECS if s.write_intent in kinds]
        write_areas = explicit & _WRITE_AREAS
        if _MEMORY_WRITE_RE.search(folded) and not (mutate or undo):
            write_areas = frozenset({AREA_MEMORY})
        if AREA_REMINDERS in keyword_explicit and not undo:
            # „připomeň mi za 2 hodiny…" / „posuň připomínku o hodinu": „hodin" není práce, jen čas připomínky.
            write_areas = frozenset({AREA_REMINDERS})
        if write_areas:
            names |= {s.name for s in candidates if set(s.areas) & write_areas}
            reason = REASON_WRITE
        else:
            names |= {s.name for s in candidates}
            reason = REASON_WRITE_UNKNOWN
    return ToolRoute(_ordered(_with_requirements(names)), reason, areas, write_intent)


def widen_route(route: ToolRoute) -> ToolRoute:
    """Nouzové rozšíření po odmítnutém tool callu: všechny READ tooly + WRITE jen při write záměru."""
    if not route.routed:
        return route
    names = {s.name for s in READ_SPECS} | set(route.names)
    if route.write_intent:
        names |= {s.name for s in WRITE_SPECS}
    return ToolRoute(_ordered(names), REASON_FALLBACK, route.areas, route.write_intent)
