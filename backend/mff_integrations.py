"""Příspěvky modulu Marvel Future Fight do globálních agregátorů (MRK-20) – přesunuto beze změny chování ze
search_service, main (GET /dashboard „mff") a context_service (oblast jen pro routing toolů, bez sekce)."""
from __future__ import annotations

from models import MffCharacter
from module_contracts import ContextSection, DashboardSection, ModuleIntegrations, SearchSource
from text_utils import join_parts

ROW_LIMIT = 500
_MFF_STATUS = {"built": "postaveno", "building": "rozpracováno", "in_progress": "rozpracováno", "planned": "plánováno", "inactive": "neaktivní"}

# ---------- vyhledávání ----------


def search_mff(db, q):
    for c in db.query(MffCharacter).limit(ROW_LIMIT).all():
        sub = join_parts(f"{c.tier} · Lv. {c.level}" if c.level else c.tier, _MFF_STATUS.get((c.status or "").lower(), ""), c.uniform)
        yield "mff_character", c.id, c.name, sub, f"{c.uniform} {c.team} {c.role} mff postava", "mff", f"/mff?character={c.id}"


# ---------- GET /dashboard: „mff" ----------


def get_mff_quick_status(db):
    items = db.query(MffCharacter).all()
    tracked = len(items)
    t4_count = 0
    priority_high_count = 0
    bc_sum = 0.0
    from models import compute_mff_build_completeness, parse_legacy_uru_state, legacy_role_string_to_list
    for it in items:
        t = (it.tier or "").strip().lower().replace(" ", "")
        if t in ("t4", "tier4", "transcendent"):
            t4_count += 1
        if (it.priority or "").lower() == "high":
            priority_high_count += 1
        roles_list = getattr(it, "roles", None)
        if roles_list is None or isinstance(roles_list, str):
            roles_list = legacy_role_string_to_list(
                roles_list if isinstance(roles_list, str) else (getattr(it, "role", "") or "")
            )
        ut = int(getattr(it, "uru_slots_total", 0) or 0)
        uf = int(getattr(it, "uru_slots_filled", 0) or 0)
        ob = int(getattr(it, "odin_blessings_count", 0) or 0)
        if ut <= 0:
            _ut2, _uf2, _ob2 = parse_legacy_uru_state(getattr(it, "uru_state", "") or "")
            if ut <= 0:
                ut = _ut2 or 20
            if uf <= 0 and _uf2:
                uf = _uf2
            if ob <= 0 and _ob2:
                ob = _ob2
        ts = (getattr(it, "team_supports", None) or "") or (getattr(it, "team", "") or "")
        bc = compute_mff_build_completeness(
            it.tier, it.level, it.uniform, it.ctp, it.artifact, ut, uf, it.iso8_set, ts,
        )
        bc_sum += float(bc)
    return {
        "tracked_characters": tracked,
        "t4_count": t4_count,
        "priority_count": priority_high_count,
        "average_build_completeness": 0 if tracked == 0 else int(round(bc_sum / tracked)),
    }


INTEGRATIONS = ModuleIntegrations(
    search=(SearchSource("mff", 100, search_mff),),
    dashboard=(DashboardSection("mff", lambda db, access: get_mff_quick_status(db)),),
    # MFF nemá CURRENT STATE sekci; oblast slouží routingu toolů (A5) a řazení paměti.
    context=(ContextSection("mff", ("mff", "marvel", "future fight", "uniform", " ctp", " uru", "iso-8", "iso8")),),
)
