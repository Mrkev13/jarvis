"""Příspěvky modulu World of Tanks do globálních agregátorů (MRK-20) – přesunuto beze změny chování ze
search_service, main (GET /dashboard „wot") a context_service. Zápisy zůstávají ve wot_service."""
from __future__ import annotations

from context_format import MAX_ITEMS, PRIORITY_RANK, fmt_num, list_or_none, short
from models import WotGrind, WotMilestone, WotReplay, WotResource
import wot_account_service
import wot_mastery_service
import wot_wargaming
from module_contracts import (
    ChangeSource, activity_changes, event_changes, ContextRequest, ContextSection, DashboardSection, ModuleIntegrations,
    ScheduledStep, SearchSource,
)
from wot_account_router import router as account_router
from wot_mastery_router import router as mastery_router
from wot_stats_router import router as stats_router
import wot_stats_service
from text_utils import format_date_cz, format_num_cz, join_parts
from time_utils import to_local

ROW_LIMIT = 500
_PRIORITY = {"high": "vysoká priorita", "medium": "", "low": ""}
_GRIND_STATUS = {"active": "aktivní", "paused": "pozastaveno", "completed": "dokončeno"}

# ---------- vyhledávání ----------


def search_wot(db, q):
    for g in db.query(WotGrind).order_by(WotGrind.tank, WotGrind.id).limit(ROW_LIMIT).all():
        sub = join_parts("Grind", f"zbývá {format_num_cz(g.xp_remaining, 0)} XP", _GRIND_STATUS.get((g.status or "").lower(), ""), _PRIORITY.get((g.priority or "").lower(), ""))
        yield "wot_grind", g.id, g.tank, sub, "wot tank grind", "wot", f"/wot?grind={g.id}"
    for r in db.query(WotReplay).order_by(WotReplay.uploaded_at.desc(), WotReplay.id.desc()).limit(ROW_LIMIT).all():
        # Game Enrichment C: replay – tank (nebo technický název vozidla / souboru), mapa, štítky, poznámka
        title = r.tank_name or (r.tank_tag.split(":", 1)[-1] if r.tank_tag else None) or r.original_filename or f"Replay #{r.id}"
        tags = " ".join(r.tags or [])
        sub = join_parts("Replay", r.map_name, format_date_cz(to_local(r.played_at)) if r.played_at else "", "★" if r.favorite else "")
        # technický tag zůstává dohledatelný i když má replay lidský název („A67_T57_58")
        tag = r.tank_tag.split(":", 1)[-1] if r.tank_tag else ""
        yield "wot_replay", r.id, title, sub, f"{tags} {r.notes or ''} {r.original_filename or ''} {tag} wot replay zaznam", "wot", f"/wot/replays?replay={r.id}"


# ---------- GET /dashboard: „wot" ----------


def get_wot_quick_status(db, limit: int = 2):
    grinds = db.query(WotGrind).all()
    pr_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"active": 0, "in_progress": 1, "paused": 2}
    active_grinds = []
    for g in grinds:
        s = (g.status or "").lower()
        if s in ("completed", "done", "cancelled"):
            continue
        active_grinds.append({
            "id": g.id,
            "tank": g.tank,
            "xp_remaining": float(g.xp_remaining or 0.0),
            "priority": g.priority or "medium",
            "status": g.status or "active",
        })
    active_grinds.sort(key=lambda g: (
        pr_rank.get((g["priority"] or "").lower(), 3),
        status_rank.get((g["status"] or "").lower(), 4),
        float(g["xp_remaining"] or 0.0),
    ))
    resources = {r.resource: float(r.amount or 0.0) for r in db.query(WotResource).all()}
    return {
        "top_grinds": active_grinds[:max(0, int(limit))],
        "credits": resources.get("credits"),
        "free_xp": resources.get("free_xp"),
        "bonds": resources.get("bonds"),
    }


# ---------- AI kontext ----------


def context_wot(req: ContextRequest) -> list[str]:
    db = req.db
    resources = ", ".join(f"{r.resource} {fmt_num(float(r.amount or 0))}" for r in db.query(WotResource).all())
    grinds = [g for g in db.query(WotGrind).all() if (g.status or "").lower() == "active"]
    grinds.sort(key=lambda g: PRIORITY_RANK.get((g.priority or "").lower(), 3))
    grind_items = [f"{short(g.tank, 25)} {fmt_num(float(g.xp_remaining or 0))} XP ({g.priority})" for g in grinds[:MAX_ITEMS]]
    return [f"WoT zdroje: {resources or 'žádné'}", f"WoT aktivní grindy: {list_or_none(grind_items, len(grinds))}",
            *_mastery_lines(db), *context_mastery(req), *wot_stats_service.context_lines(db)]


MASTERY_TOP = 5  # „který tank má nejvíc" – pár míst navíc kvůli shodám
_MASTERY_CLASS = {"first": "I. třída", "second": "II. třída", "third": "III. třída"}


def _mastery_lines(db) -> list[str]:
    """MRK-94: M-ka (odznak Mistr / ace) spočítaná kódem, stejně jako cíl MRK-82 – opakovaná M na jednom tanku se
    počítají. LLM dostane jen hotový souhrn (počty, pořadí tanků, poslední M-ko)."""
    rows = db.query(WotMilestone.id, WotMilestone.tank, WotMilestone.mastery, WotMilestone.played_on).filter(
        WotMilestone.milestone_type == "mastery").order_by(WotMilestone.id).all()
    aces = [r for r in rows if r.mastery == "ace"]
    if not aces:
        lines = ["WoT M-ka (odznak Mistr): žádná zapsaná."]
    else:
        counts: dict[str, int] = {}
        for r in aces:
            counts[r.tank] = counts.get(r.tank, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        top = [f"{short(tank, 25)} {n}×" for tank, n in ranked[:MASTERY_TOP]]
        lines = [f"WoT M-ka (odznak Mistr): celkem {len(aces)} na {len(counts)} tancích; "
                 f"podle počtu: {list_or_none(top, len(ranked))}"]
        dated = [r for r in aces if r.played_on]
        if dated:
            # stejný den → později zapsané (vyšší id) je poslední; nezávisí na pořadí řádků z DB
            last = max(dated, key=lambda r: (r.played_on, r.id))
            lines.append(f"WoT poslední M-ko: {short(last.tank, 25)} {last.played_on.isoformat()}")
    others = {label: sum(1 for r in rows if r.mastery == key) for key, label in _MASTERY_CLASS.items()}
    if any(others.values()):
        lines.append("WoT ostatní odznaky zvládnutí: " + ", ".join(f"{k} {v}×" for k, v in others.items() if v))
    return lines


def context_mastery(req: ContextRequest) -> list[str]:
    """MRK-106: souhrn tabulky odznaků z Wargaming API (detail po tancích dává tool get_wot_mastery)."""
    s = wot_mastery_service.summary(req.db)
    if not s["tanks"]:
        return []
    by = s["by_mark"]
    line = (f"WoT odznaky z Wargaming API (nejvyšší na tank): {s['tanks']} tanků, M {by['M']}, I {by['I']}, "
            f"II {by['II']}, III {by['III']}, bez odznaku {by['–']}")
    if s["pending_replays"]:
        line += f"; M čekající na replay: {s['pending_replays']}"
    return [line]


def hourly_mastery(db):
    return wot_mastery_service.sync(db, wot_wargaming.client())


def hourly_resources(db):
    """MRK-105: zdroje z propojeného Wargaming účtu (bez propojení nic, žádná síť)."""
    return wot_account_service.sync(db, wot_wargaming.client())


EVENTS = (wot_mastery_service.ACE_EVENT,)


def tank_names(db):
    """Zmínka grindovaného tanku („kolik chybí na Kranvagn") = oblast WoT."""
    return [t for (t,) in db.query(WotGrind.tank).all() if t]


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource("wot", areas=frozenset({"wot"}),
                          from_event=event_changes({"milestone": "/wot/milestones?milestone={id}"}, {wot_mastery_service.ACE_EVENT: "WoT: nové M"}),
                          from_activity=activity_changes({"wot_grind": "/wot?grind={id}",
                                                          "wot_replay": "/wot/replays?replay={id}"}, "/wot")),),
    search=(SearchSource("wot", 90, search_wot),),
    dashboard=(DashboardSection("wot", lambda db, access: get_wot_quick_status(db, limit=2)),),
    context=(
        # MRK-94: M-ka / odznak Mistr („Mek", „M-ko", „Mka") – s mezerou na začátku, ať nechytají cizí slova
        ContextSection("wot", ("wot", "tank", "kredit", "gold", "grind", "free xp", "bond", " mek", " m-ek", " m-k",
                               " mko", " mka", "mistr", "oceneni", "mastery", "odznak"), order=70,
                       build=context_wot, covered_tools=("get_wot_resources", "get_wot_grinds"), name_hints=tank_names),
    ),
    hourly=(ScheduledStep("wot mastery sync", hourly_mastery),  # MRK-146: každou hodinu (nejvýš 1× za 50 min), bez klíčů nic
            ScheduledStep("wot resources sync", hourly_resources)),  # MRK-105: jen s propojeným účtem
    routers=(mastery_router, account_router, stats_router),
)
