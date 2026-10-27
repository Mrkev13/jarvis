"""Deterministický týdenní snímek pro Týdenní přehled (Roadmap 3.0 Phase G).

Týden = pražský kalendářní týden pondělí 00:00 → neděle 24:00 (Europe/Prague, DST řeší time_utils).
Snímek pokrývá [pondělí 00:00, `cutoff`) – při nedělním generování v 19:00 tedy „týden do teď", při
dohánění po restartu celý týden. Srovnání je **like-for-like**: předchozí týden ve stejném rozsahu
(stejný den v týdnu a čas, posunuto o 7 pražských dní).

Vše, co jde spočítat, se spočítá tady – LLM jen vybírá, řadí a formuluje:
- `metrics`: číselné ukazatele (tento týden | minulý týden | změna | lepší/horší/beze změny),
- `sections`: konkrétní položky s odkazy (`assignment:12`, `goal:3`…),
- `forecasts`: kandidáti odhadů s pevně danou jistotou a podkladem (LLM si jistotu nevymýšlí),
- `next_week`: známé závazky příštího týdne.
Bez syrových dumpů, bez promptu v DB. Velikost hlídají stropy sekcí a tokenový strop.
Finance tu není ani nepřímo (MRK-60: do LLM nejde – finance_ai_policy.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from briefing_snapshot import Item, meaningful_activity
from finance_ai_policy import finance_goal_ids, is_finance_activity, is_finance_goal
from goal_history_service import compute_goal_progress_and_value
from llm_budget import estimate_tokens
from models import (
    ActivityLog, Assignment, Exam, Goal, GoalProgressHistory, Notification, Reminder,
    WorkSession,
)
from statuses import ASSIGNMENT_DONE_STATUSES, EXAM_OPEN_STATUSES, GOAL_INACTIVE_STATUSES
from time_utils import local_to_utc, local_week_bounds_utc, to_local
from text_utils import WEEKDAYS_CZ, clip as _short

MAX_SNAPSHOT_TOKENS = 2200
QUIET_MIN_SIGNALS = 4  # méně datových bodů → deterministický „málo dat" přehled bez LLM
MIN_MONEY_DELTA = 200.0  # menší změny v Kč = „beze změny" (nepřehánět drobné částky)
MIN_PCT_BASE = 500.0  # procenta jen nad rozumným základem
STALL_DAYS = 14
GOAL_FORECAST_DAYS = 28

SECTION_ORDER = ("school", "goals", "reminders", "activity", "next_week")
SECTION_TITLES = {
    "school": "ŠKOLA",
    "goals": "CÍLE",
    "reminders": "PŘIPOMÍNKY",
    "activity": "AKTIVITA (výběr)",
    "next_week": "PŘÍŠTÍ TÝDEN",
}
SECTION_CAPS = {"school": 10, "goals": 8, "reminders": 3, "activity": 4, "next_week": 10}
# Ořez na rozpočet: nejdřív detaily s nejmenší hodnotou; termíny příštího týdne a metriky až nakonec.
TRIM_ORDER = ("activity", "reminders", "goals", "school", "next_week")

CONFIDENCE_TEXT = {"high": "vysoká", "moderate": "střední", "low": "nízká"}
_GOAL_INACTIVE = GOAL_INACTIVE_STATUSES
_WEEKDAY_NAMES = WEEKDAYS_CZ


# ===== týden =====

def week_start_for(d: date) -> date:
    """Pondělí pražského týdne, do kterého patří datum d."""
    return d - timedelta(days=d.weekday())


def week_bounds_utc(week_start: date) -> tuple[datetime, datetime]:
    """[pondělí 00:00, další pondělí 00:00) Europe/Prague v naive UTC (DST-safe, 167/168/169 h)."""
    return local_week_bounds_utc(week_start)


def week_label(week_start: date) -> str:
    end = week_start + timedelta(days=6)
    if week_start.year != end.year:
        return f"{week_start.day}. {week_start.month}. {week_start.year} – {end.day}. {end.month}. {end.year}"
    if week_start.month != end.month:
        return f"{week_start.day}. {week_start.month}. – {end.day}. {end.month}. {end.year}"
    return f"{week_start.day}.–{end.day}. {end.month}. {end.year}"


@dataclass
class Period:
    start: datetime  # UTC
    end: datetime  # UTC, exkluzivně
    first_day: date
    last_day: date  # poslední (i částečně) zahrnutý den – pro data bez času (úkoly, práce)


def _period(week_start: date, cutoff_utc: datetime) -> tuple[Period, Period]:
    start, week_end = week_bounds_utc(week_start)
    end = min(cutoff_utc, week_end)
    end_local = to_local(end).replace(tzinfo=None)
    last_day = (end_local - timedelta(microseconds=1)).date()
    cur = Period(start, end, week_start, last_day)
    prev_start = local_to_utc(datetime.combine(week_start - timedelta(days=7), time.min))
    prev_end = local_to_utc(end_local - timedelta(days=7))
    prev = Period(prev_start, prev_end, week_start - timedelta(days=7), last_day - timedelta(days=7))
    return cur, prev


# ===== datové struktury =====

def _fmt(value: float, unit: str = "") -> str:
    if unit == "h":
        v = round(value, 1)
        s = f"{v:.1f}".replace(".", ",") if v != int(v) else f"{int(v)}"
        return f"{s} h"
    if unit == "Kč":
        return f"{round(value):,}".replace(",", " ") + " Kč"
    if unit == "%":
        return f"{round(value)} %"
    return f"{round(value)}" if float(value).is_integer() else f"{value:.1f}".replace(".", ",")


def plural(n: int, one: str, few: str, many: str) -> str:
    """Česká množná čísla: 1 termín, 2–4 termíny, 0/5+ termínů."""
    return one if n == 1 else few if 2 <= n <= 4 else many


@dataclass
class Metric:
    key: str
    label: str
    cur: float
    prev: float | None
    unit: str = ""
    polarity: str = "neutral"  # up_good | down_good | neutral
    min_delta: float = 1.0  # menší rozdíl = „beze změny"
    prev_label: str = "minulý týden"
    note: str = ""
    url: str = "/"

    @property
    def ref(self) -> str:
        return f"metric:{self.key}"

    @property
    def delta(self) -> float | None:
        return None if self.prev is None else round(self.cur - self.prev, 2)

    @property
    def pct(self) -> int | None:
        if self.prev is None or abs(self.prev) < (MIN_PCT_BASE if self.unit == "Kč" else 1) or self.prev == 0:
            return None
        if self.unit not in ("Kč", "h"):
            return None
        return round((self.cur - self.prev) / abs(self.prev) * 100)

    @property
    def trend(self) -> str:
        """better | worse | same | up | down | n/a – „lepší/horší" jen u veličin s jasnou polaritou."""
        d = self.delta
        if d is None:
            return "n/a"
        if abs(d) < self.min_delta:
            return "same"
        if self.polarity == "neutral":
            return "up" if d > 0 else "down"
        good = d > 0 if self.polarity == "up_good" else d < 0
        return "better" if good else "worse"

    def delta_text(self) -> str:
        d = self.delta
        if d is None:
            return ""
        sign = "+" if d > 0 else "−" if d < 0 else "±"
        out = f"{sign}{_fmt(abs(d), self.unit)}"
        if self.pct is not None and d:
            out += f" ({'+' if self.pct > 0 else '−'}{abs(self.pct)} %)"
        return out

    def line(self) -> str:
        trend_cz = {"better": "lepší", "worse": "horší", "same": "beze změny", "up": "víc", "down": "méně",
                    "n/a": ""}[self.trend]
        parts = [f"[{self.ref}] {self.label}: {_fmt(self.cur, self.unit)}"]
        if self.prev is not None:
            parts.append(f"{self.prev_label} {_fmt(self.prev, self.unit)}")
            parts.append(self.delta_text())
            parts.append(trend_cz)
        if self.note:
            parts.append(self.note)
        return " · ".join(p for p in parts if p)

    def as_dict(self) -> dict:
        return {"ref": self.ref, "key": self.key, "label": self.label, "unit": self.unit,
                "cur": self.cur, "prev": self.prev, "prev_label": self.prev_label, "delta": self.delta,
                "pct": self.pct, "trend": self.trend, "cur_text": _fmt(self.cur, self.unit),
                "prev_text": None if self.prev is None else _fmt(self.prev, self.unit),
                "delta_text": self.delta_text(), "note": self.note, "url": self.url}


@dataclass
class Forecast:
    key: str
    statement: str
    confidence: str  # high | moderate | low – pravidlo je deterministické (viz _forecasts)
    basis: list[str]
    rule: str  # krátké vysvětlení pravidla (pro UI „na čem odhad stojí")

    @property
    def ref(self) -> str:
        return f"forecast:{self.key}"

    def line(self) -> str:
        basis = ", ".join(self.basis)
        return f"[{self.ref}] jistota {CONFIDENCE_TEXT[self.confidence]} · podklad {basis} · {self.statement}"

    def as_dict(self) -> dict:
        return {"ref": self.ref, "key": self.key, "statement": self.statement, "confidence": self.confidence,
                "basis": list(self.basis), "rule": self.rule}


@dataclass
class WeeklySnapshot:
    week_start: date
    period_end: datetime  # UTC
    partial: bool
    metrics: list[Metric] = field(default_factory=list)
    sections: dict[str, list[Item]] = field(default_factory=dict)
    forecasts: list[Forecast] = field(default_factory=list)
    activity_summary: str = ""
    signals: int = 0

    @property
    def is_quiet(self) -> bool:
        return self.signals < QUIET_MIN_SIGNALS

    def items(self) -> list[Item]:
        return [i for s in SECTION_ORDER for i in self.sections.get(s, [])]

    def by_ref(self) -> dict:
        out: dict = {i.ref: i for i in self.items()}
        out.update({m.ref: m for m in self.metrics})
        out.update({f.ref: f for f in self.forecasts})
        return out

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)

    def render(self) -> str:
        ws = self.week_start
        end_local = to_local(self.period_end)
        lines = [
            f"TÝDEN {ws.isoformat()} až {(ws + timedelta(days=6)).isoformat()} (pondělí–neděle, Europe/Prague); "
            f"data do {end_local:%Y-%m-%d %H:%M}{' (týden ještě běží)' if self.partial else ''}. "
            "Srovnání = předchozí týden ve stejném rozsahu.",
            "METRIKY (tento týden · minulý týden · změna · hodnocení)",
        ]
        lines.extend(f"- {m.line()}" for m in self.metrics)
        for key in SECTION_ORDER:
            items = self.sections.get(key) or []
            if key == "activity" and self.activity_summary:
                lines.append(f"AKTIVITA: {self.activity_summary}")
            if not items:
                continue
            title = SECTION_TITLES[key]
            if key == "next_week":
                nws = ws + timedelta(days=7)
                title += f" ({nws.isoformat()} až {(nws + timedelta(days=6)).isoformat()})"
            lines.append(title)
            lines.extend(f"- {i.line()}" for i in items)
        if self.forecasts:
            lines.append("ODHADY – kandidáti (jistota a podklad jsou pevně dané)")
            lines.extend(f"- {f.line()}" for f in self.forecasts)
        else:
            lines.append("ODHADY: žádné – na odhad nejsou dost podložená data.")
        return "\n".join(lines)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.render())

    def source_hash(self) -> str:
        canonical = json.dumps({"m": [m.as_dict() for m in self.metrics],
                                "s": {k: [i.as_dict() for i in self.sections.get(k, [])] for k in SECTION_ORDER},
                                "f": [f.as_dict() for f in self.forecasts], "a": self.activity_summary},
                               ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ===== dílčí výpočty =====

def _activity(db: Session, p: Period) -> list[ActivityLog]:
    logs = meaningful_activity(db.query(ActivityLog)
                               .filter(ActivityLog.timestamp >= p.start, ActivityLog.timestamp < p.end)
                               .order_by(ActivityLog.timestamp.desc()).all())
    finance_goals = finance_goal_ids(db)
    return [lg for lg in logs if not is_finance_activity(lg.area, lg.entity_type, lg.entity_id, finance_goals)]


def _delta_status(log: ActivityLog) -> str | None:
    try:
        delta = json.loads(log.delta_json or "{}")
    except ValueError:
        return None
    new = (delta.get("status") or {}).get("new") if isinstance(delta, dict) else None
    return str(new).strip().lower() if new is not None else None


def _completed_assignment_ids(logs: list[ActivityLog]) -> list[int]:
    ids: list[int] = []
    for lg in logs:
        if lg.entity_type != "Assignment" or lg.entity_id is None:
            continue
        if lg.action_type == "complete" or _delta_status(lg) in ASSIGNMENT_DONE_STATUSES:
            if lg.entity_id not in ids:
                ids.append(lg.entity_id)
    return ids


def _goal_completed_ids(logs: list[ActivityLog]) -> list[int]:
    return list(dict.fromkeys(lg.entity_id for lg in logs if lg.entity_type == "Goal" and lg.entity_id is not None
                              and (lg.action_type == "complete" or _delta_status(lg) == "completed")))


def _is_done(a: Assignment) -> bool:
    return (a.status or "").strip().lower() in ASSIGNMENT_DONE_STATUSES


def _work(db: Session, first: date, last: date) -> tuple[float, float, int]:
    hours = income = 0.0
    count = 0
    for s in db.query(WorkSession).filter(WorkSession.date >= first, WorkSession.date <= last).all():
        hours += float(s.hours or 0)
        income += float(s.hours or 0) * float(s.hourly_rate or 0)
        count += 1
    return round(hours, 2), round(income, 2), count


def _goal_history(db: Session, goal_id: int) -> list[GoalProgressHistory]:
    return (db.query(GoalProgressHistory).filter(GoalProgressHistory.goal_id == goal_id)
            .order_by(GoalProgressHistory.recorded_at).all())


def _progress_at(history: list[GoalProgressHistory], moment: datetime) -> int | None:
    value = None
    for h in history:
        if h.recorded_at < moment:
            value = int(h.progress or 0)
    return value


def _last_change(history: list[GoalProgressHistory], until: datetime) -> datetime | None:
    last, prev = None, None
    for h in history:
        if h.recorded_at >= until:
            break
        if prev is not None and int(h.progress or 0) != prev:
            last = h.recorded_at
        prev = int(h.progress or 0)
    return last


# ===== hlavní sestavení =====

def build_weekly_snapshot(db: Session, week_start: date, cutoff_utc: datetime, *,
                          max_tokens: int = MAX_SNAPSHOT_TOKENS) -> WeeklySnapshot:
    week_start = week_start_for(week_start)
    cur, prev = _period(week_start, cutoff_utc)
    _ws, week_end = week_bounds_utc(week_start)
    snap = WeeklySnapshot(week_start, cur.end, partial=cur.end < week_end,
                          sections={k: [] for k in SECTION_ORDER})
    today = cur.last_day
    metrics: list[Metric] = []
    signals = 0

    # --- aktivita (bez technického šumu, sdílený filtr z Phase F) ---
    logs_cur, logs_prev = _activity(db, cur), _activity(db, prev)

    # --- škola ---
    assignments = {a.id: a for a in db.query(Assignment).all()}
    done_cur = [i for i in _completed_assignment_ids(logs_cur) if i in assignments and _is_done(assignments[i])]
    done_prev = [i for i in _completed_assignment_ids(logs_prev) if i in assignments and _is_done(assignments[i])]
    created_cur = {lg.entity_id for lg in logs_cur if lg.entity_type == "Assignment" and lg.action_type == "create"}
    created_prev = {lg.entity_id for lg in logs_prev if lg.entity_type == "Assignment" and lg.action_type == "create"}
    open_items = [a for a in assignments.values() if not _is_done(a) and a.due_date is not None]
    # Rozpracovaný týden (neděle 19:00): úkol s termínem dnes ještě není po termínu; celý týden: i neděle.
    overdue_end = [a for a in open_items if (a.due_date < today if snap.partial else a.due_date <= today)]
    # Rekonstrukce stavu na začátku týdne: dnes otevřené + během týdne dokončené (obojí s termínem před pondělím),
    # bez úkolů založených až během týdne.
    overdue_start = {a.id for a in open_items if a.due_date < week_start and a.id not in created_cur}
    overdue_start |= {i for i in done_cur if assignments[i].due_date and assignments[i].due_date < week_start}
    due_week = [a for a in assignments.values() if a.due_date and week_start <= a.due_date <= week_start + timedelta(days=6)]
    metrics.append(Metric("assignments_completed", "Dokončené úkoly", len(done_cur), len(done_prev),
                          polarity="up_good", url="/school"))
    if created_cur or created_prev:
        metrics.append(Metric("assignments_created", "Nově přidané úkoly", len(created_cur), len(created_prev),
                              url="/school"))
    if overdue_start or overdue_end:
        metrics.append(Metric("overdue_backlog", "Úkoly po termínu (začátek → konec týdne)", len(overdue_end),
                              len(overdue_start), polarity="down_good", prev_label="na začátku týdne",
                              url="/school"))
    for i in done_cur:
        a = assignments[i]
        snap.sections["school"].append(Item(f"assignment:{a.id}", "assignment", _short(a.title), "dokončeno tento týden",
                                            a.due_date.isoformat() if a.due_date else None, "/school"))
    for a in sorted(overdue_end, key=lambda a: a.due_date):
        snap.sections["school"].append(Item(f"assignment:{a.id}", "assignment", _short(a.title),
                                            f"po termínu od {a.due_date.day}. {a.due_date.month}.",
                                            a.due_date.isoformat(), "/school",
                                            "priorita high" if (a.priority or "").lower() == "high" else ""))
    exams_week = [e for e in db.query(Exam).filter(Exam.exam_date >= week_start,
                                                   Exam.exam_date <= today).all()]
    for e in sorted(exams_week, key=lambda e: e.exam_date):
        status = (e.status or "").strip().lower()
        result = {"passed": "složeno", "failed": "nesloženo"}.get(status,
                                                                  "bez zapsaného výsledku" if status in EXAM_OPEN_STATUSES else status)
        snap.sections["school"].append(Item(f"exam:{e.id}", "exam", _short(e.title),
                                            f"zkouška {e.exam_date.day}. {e.exam_date.month}.",
                                            e.exam_date.isoformat(), "/school", f"výsledek: {result}"))
    signals += len(exams_week)  # zkoušky nemají vlastní záznam v aktivitě, když se jen konají

    # --- práce ---
    hours, income, sessions = _work(db, cur.first_day, cur.last_day)
    p_hours, p_income, _ = _work(db, prev.first_day, prev.last_day)
    history_hours = [_work(db, week_start - timedelta(days=7 * k), week_start - timedelta(days=7 * k - 6))[0]
                     for k in (3, 2, 1)]
    if hours or p_hours:
        note = ""
        avg = sum(history_hours) / 3
        steady = all(h > 0 for h in history_hours)  # „neobvyklé" jen proti souvislé historii, ne proti nulám
        if steady and avg >= 2 and hours >= 1.5 * avg:
            note = f"neobvykle vysoko (průměr 3 týdnů {_fmt(avg, 'h')})"
        elif steady and avg >= 2 and hours <= 0.5 * avg:
            note = f"neobvykle nízko (průměr 3 týdnů {_fmt(avg, 'h')})"
        metrics.append(Metric("work_hours", "Odpracováno", hours, p_hours, unit="h", min_delta=1.0, note=note,
                              url="/work"))
    if income or p_income:
        metrics.append(Metric("work_income", "Výdělek z práce", income, p_income, unit="Kč", polarity="up_good",
                              min_delta=MIN_MONEY_DELTA, url="/work"))

    # --- cíle ---
    goals = [g for g in db.query(Goal).all() if (g.status or "").strip().lower() not in _GOAL_INACTIVE
             and not is_finance_goal(g.source)]
    progressed = p_progressed = 0
    goal_items: list[Item] = []
    goal_paces: dict[int, tuple[float, int, int]] = {}
    for g in goals:
        hist = _goal_history(db, g.id)
        p_now, _ = compute_goal_progress_and_value(db, g, today=today)
        start_p, end_p = _progress_at(hist, cur.start), _progress_at(hist, cur.end)
        pstart_p = _progress_at(hist, prev.start)
        end_p = end_p if end_p is not None else (p_now if not hist else None)
        if start_p is not None and end_p is not None and end_p != start_p:
            progressed += int(end_p > start_p)
            sign = "+" if end_p > start_p else "−"
            goal_items.append(Item(f"goal:{g.id}", "goal", _short(g.title), f"{start_p} % → {end_p} %",
                                   g.target_date.isoformat() if g.target_date else None, "/goals",
                                   f"{sign}{abs(end_p - start_p)} %"))
        if pstart_p is not None and start_p is not None and start_p > pstart_p:
            p_progressed += 1
        last_change = _last_change(hist, cur.end)
        stalled_since = last_change or (hist[0].recorded_at if hist else None)
        created = g.created_at or cur.start
        if (p_now < 100 and stalled_since is not None and cur.end - stalled_since >= timedelta(days=STALL_DAYS)
                and cur.end - created >= timedelta(days=STALL_DAYS)
                and not any(i.ref == f"goal:{g.id}" for i in goal_items)):
            days = (cur.end - stalled_since).days
            goal_items.append(Item(f"goal:{g.id}", "goal", _short(g.title), f"beze změny {days} dní",
                                   g.target_date.isoformat() if g.target_date else None, "/goals", f"{p_now} %"))
        if g.target_date and g.target_date < today and not any(i.ref == f"goal:{g.id}" for i in goal_items):
            goal_items.append(Item(f"goal:{g.id}", "goal", _short(g.title),
                                   f"po cílovém datu {g.target_date.day}. {g.target_date.month}.",
                                   g.target_date.isoformat(), "/goals", f"{p_now} %"))
        # tempo pro odhad: poslední záznamy přes ≥ 7 dní
        if hist and g.target_date and today < g.target_date <= today + timedelta(days=GOAL_FORECAST_DAYS) and p_now < 100:
            window = [h for h in hist if h.recorded_at < cur.end]
            if len(window) >= 2 and (window[-1].recorded_at - window[0].recorded_at).days >= 7:
                first = next((h for h in window if h.recorded_at >= window[-1].recorded_at - timedelta(days=28)),
                             window[0])
                span = max(7, (window[-1].recorded_at - first.recorded_at).days)
                pace = (int(window[-1].progress or 0) - int(first.progress or 0)) / span * 7
                goal_paces[g.id] = (round(pace, 1), span, p_now)
    for gid in _goal_completed_ids(logs_cur):
        g = db.get(Goal, gid)
        if g is not None and not is_finance_goal(g.source):
            goal_items.insert(0, Item(f"goal:{g.id}", "goal", _short(g.title), "splněno tento týden", None, "/goals"))
    if goals and (progressed or p_progressed):
        metrics.append(Metric("goals_progressed", "Cíle s posunem", progressed, p_progressed, polarity="up_good",
                              url="/goals"))
    signals += progressed  # posun automatických cílů nemá záznam v aktivitě (snapshoty jsou šum)
    seen: set[str] = set()
    snap.sections["goals"] = [i for i in goal_items if not (i.ref in seen or seen.add(i.ref))]

    # --- připomínky ---
    def fired(p: Period) -> int:
        return (db.query(Notification).filter(Notification.notification_type == "reminder",
                                              Notification.created_at >= p.start, Notification.created_at < p.end)
                .count())

    f_cur, f_prev = fired(cur), fired(prev)
    done_r = sum(1 for lg in logs_cur if lg.area == "reminders" and lg.action_type == "complete")
    p_done_r = sum(1 for lg in logs_prev if lg.area == "reminders" and lg.action_type == "complete")
    snoozed = sum(1 for lg in logs_cur if lg.area == "reminders" and lg.action_type == "snooze")
    signals += f_cur  # zazvonění není uživatelská aktivita
    if f_cur or f_prev:
        metrics.append(Metric("reminders_fired", "Zazněné připomínky", f_cur, f_prev,
                              note=f"hotovo {done_r} (minulý týden {p_done_r}), odloženo {snoozed}",
                              url="/reminders"))
    for r in db.query(Reminder).filter(Reminder.status == "fired").order_by(Reminder.due_at).all():
        t = to_local(r.last_fired_at or r.due_at)
        snap.sections["reminders"].append(Item(f"reminder:{r.id}", "reminder", _short(r.title),
                                               f"zazněla {t.day}. {t.month}., nevyřízená", t.date().isoformat(),
                                               "/reminders"))

    # --- aktivita ---
    counts: dict[str, int] = {}
    for lg in logs_cur:
        counts[lg.area] = counts.get(lg.area, 0) + 1
    if counts:
        snap.activity_summary = (", ".join(f"{n}× {a}" for a, n in sorted(counts.items(), key=lambda kv: -kv[1]))
                                 + f" (minulý týden {len(logs_prev)} záznamů)")
    for lg in logs_cur:
        if lg.entity_type in ("Assignment", "Goal") and lg.action_type == "complete":
            continue  # už je ve škole / cílech
        snap.sections["activity"].append(Item(f"activity:{lg.id}", "activity", _short(lg.summary, 60), "", None,
                                              "/activity"))
    signals += len(logs_cur)  # uživatelské změny (škola, práce, cíle, připomínky…) bez šumu

    # --- příští týden (jen známé závazky) ---
    nws, nwe = week_start + timedelta(days=7), week_start + timedelta(days=13)
    n_start, n_end = week_bounds_utc(nws)
    upcoming: list[Item] = []
    for a in open_items:
        if nws <= a.due_date <= nwe:
            upcoming.append(Item(f"assignment:{a.id}", "assignment", _short(a.title),
                                 f"termín {_WEEKDAY_NAMES[a.due_date.weekday()]} {a.due_date.day}. {a.due_date.month}.",
                                 a.due_date.isoformat(), "/school",
                                 "priorita high" if (a.priority or "").lower() == "high" else ""))
    for e in db.query(Exam).filter(Exam.exam_date >= nws, Exam.exam_date <= nwe).all():
        if (e.status or "").strip().lower() in EXAM_OPEN_STATUSES:
            upcoming.append(Item(f"exam:{e.id}", "exam", _short(e.title),
                                 f"zkouška {_WEEKDAY_NAMES[e.exam_date.weekday()]} {e.exam_date.day}. {e.exam_date.month}.",
                                 e.exam_date.isoformat(), "/school"))
    deadlines = list(upcoming)
    for r in db.query(Reminder).filter(Reminder.status == "scheduled", Reminder.recurrence == "none",
                                       Reminder.due_at >= n_start, Reminder.due_at < n_end).all():
        t = to_local(r.due_at)
        upcoming.append(Item(f"reminder:{r.id}", "reminder", _short(r.title),
                             f"připomínka {_WEEKDAY_NAMES[t.weekday()]} {t.day}. {t.month}. {t:%H:%M}",
                             t.date().isoformat(), "/reminders"))
    for g in goals:
        if g.target_date and nws <= g.target_date <= nwe:
            upcoming.append(Item(f"goal:{g.id}", "goal", _short(g.title),
                                 f"cílové datum {g.target_date.day}. {g.target_date.month}.",
                                 g.target_date.isoformat(), "/goals"))
    upcoming.sort(key=lambda i: (i.date or "9999", i.ref))
    snap.sections["next_week"] = upcoming
    signals += len(upcoming)  # známé závazky příštího týdne
    this_week_deadlines = len(due_week) + len([e for e in db.query(Exam).filter(
        Exam.exam_date >= week_start, Exam.exam_date <= week_start + timedelta(days=6)).all()])
    per_day: dict[date, int] = {}
    for i in deadlines:
        d = date.fromisoformat(i.date)
        per_day[d] = per_day.get(d, 0) + 1
    busiest = max(per_day.items(), key=lambda kv: (kv[1], -kv[0].toordinal())) if per_day else None
    if deadlines or this_week_deadlines:
        note = (f"nejvíc {_WEEKDAY_NAMES[busiest[0].weekday()]} {busiest[0].day}. {busiest[0].month}. ({busiest[1]})"
                if busiest and busiest[1] >= 2 else "")
        metrics.append(Metric("next_week_deadlines", "Termíny úkolů a zkoušek příští týden", len(deadlines),
                              this_week_deadlines, prev_label="tento týden", note=note, url="/school"))

    snap.metrics = metrics
    snap.forecasts = _forecasts(db, snap, cur, deadlines, per_day, busiest, this_week_deadlines, history_hours,
                                hours, goal_paces, len(overdue_start), len(overdue_end))
    snap.signals = signals
    for key, cap in SECTION_CAPS.items():
        snap.sections[key] = snap.sections[key][:cap]
    # Rozpočet tokenů: ubírat od nejméně hodnotných detailů.
    for key in TRIM_ORDER:
        while snap.tokens > max_tokens and snap.sections[key]:
            snap.sections[key].pop()
        if key == "activity" and snap.tokens > max_tokens:
            snap.activity_summary = ""
        if snap.tokens <= max_tokens:
            break
    return snap


def _forecasts(db, snap, cur, deadlines, per_day, busiest, this_week_deadlines, history_hours, hours,
               goal_paces, overdue_start, overdue_end) -> list[Forecast]:
    """Konzervativní kandidáti odhadů. Jistota je pravidlo, ne názor LLM:
    - high: plyne ze známých závazků (termíny v kalendáři),
    - moderate: trend nebo tempo s dostatečnou historií (≥ 14 dní dat v měsíci, ≥ 21 dní u cíle),
    - low: kratší historie / tří-týdenní trend.
    Nikdy: zdraví, nálada, motivace, výsledky zkoušek, nepodložený příjem."""
    out: list[Forecast] = []
    if len(deadlines) >= 3:
        day_txt = (f"; nejvíc {_WEEKDAY_NAMES[busiest[0].weekday()]} {busiest[0].day}. {busiest[0].month}. ({busiest[1]})"
                   if busiest and busiest[1] >= 2 else "")
        out.append(Forecast(
            "deadline_load",
            f"Příští týden bude na termíny náročnější: {len(deadlines)} "
            f"{plural(len(deadlines), 'termín', 'termíny', 'termínů')} (tento týden {this_week_deadlines}){day_txt}.",
            "high", [i.ref for i in deadlines][:6], "známé termíny v kalendáři"))
    elif not deadlines and this_week_deadlines >= 2:
        out.append(Forecast("deadline_light", "Příští týden zatím nemá žádné termíny úkolů ani zkoušek.", "high",
                            ["metric:next_week_deadlines"], "známé termíny v kalendáři"))

    # trend hodin práce (tři po sobě jdoucí změny stejným směrem, ≥ 25 %)
    seq = history_hours[1:] + [hours]  # w-2, w-1, tento týden
    if seq[0] >= 4 and seq[0] > seq[1] > seq[2] and (seq[0] - seq[2]) / seq[0] >= 0.25:
        out.append(Forecast(
            "work_trend_down",
            f"Odpracované hodiny klesají třetí týden po sobě ({' → '.join(_fmt(h, 'h') for h in seq)}); "
            "pokud trend vydrží, příští týden může být podobně slabý.",
            "low", ["metric:work_hours"], "trend tří týdnů"))
    elif seq[2] >= 4 and seq[0] < seq[1] < seq[2] and seq[0] > 0 and (seq[2] - seq[0]) / seq[0] >= 0.25:
        out.append(Forecast(
            "work_trend_up",
            f"Odpracované hodiny rostou třetí týden po sobě ({' → '.join(_fmt(h, 'h') for h in seq)}); "
            "pokud trend vydrží, příští týden může být podobně vytížený.",
            "low", ["metric:work_hours"], "trend tří týdnů"))

    # cíle s blízkým termínem a nedostatečným tempem
    for gid, (pace, span, p_now) in sorted(goal_paces.items()):
        g = db.get(Goal, gid)
        days_left = (g.target_date - cur.last_day).days
        needed = (100 - p_now) / max(days_left, 1) * 7
        if pace < needed:
            pace_txt = f"+{_fmt(pace)} % týdně" if pace > 0 else "bez posunu"
            out.append(Forecast(
                f"goal_{gid}",
                f"Cíl „{_short(g.title, 40)}“ při dosavadním tempu ({pace_txt}) nejspíš do "
                f"{g.target_date.day}. {g.target_date.month}. nestihne 100 % (teď {p_now} %).",
                "moderate" if span >= 21 else "low", [f"goal:{gid}"], "tempo z historie progresu"))
        if len(out) >= 5:
            break

    if overdue_end - overdue_start >= 2:
        out.append(Forecast(
            "backlog_growing",
            f"Úkolů po termínu přibylo ({overdue_start} → {overdue_end}); bez dokončování bude seznam dál růst.",
            "low", ["metric:overdue_backlog"], "změna backlogu za týden"))
    return out[:5]
