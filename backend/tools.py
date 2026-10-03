from datetime import date

from database import SessionLocal
from models import WotResource, WotGrind
from models import FinanceTransaction
from time_utils import today_local
from models import Subject, Assignment, Exam
from models import WorkSession
from models import MffCharacter
from models import Goal
from models import Memory
from models import GoalProgressHistory
from models import (
    compute_mff_build_completeness,
    legacy_role_string_to_list,
    parse_legacy_uru_state,
)
from activity_service import log_activity, delta_dict
from text_utils import finance_summary_cz, format_czk_cz, format_date_cz, format_hours_cz


def get_wot_resources():
    db = SessionLocal()

    try:
        resources = db.query(WotResource).all()

        return {
            item.resource: item.amount
            for item in resources
        }

    finally:
        db.close()



def get_wot_grinds():
    db = SessionLocal()

    try:
        grinds = db.query(WotGrind).all()

        return [
            {
                "id": item.id,
                "tank": item.tank,
                "xp_remaining": item.xp_remaining,
                "priority": item.priority,
                "status": item.status
            }
            for item in grinds
        ]

    finally:
        db.close()

def get_finance_summary():
    db = SessionLocal()

    try:
        transactions = db.query(FinanceTransaction).all()

        income = sum(
            item.amount
            for item in transactions
            if item.transaction_type == "income"
        )

        expenses = sum(
            item.amount
            for item in transactions
            if item.transaction_type == "expense"
        )

        return {
            "income": income,
            "expenses": expenses,
            "balance": income - expenses,
            "transactions_count": len(transactions)
        }

    finally:
        db.close()


def get_finance_transactions():
    db = SessionLocal()

    try:
        items = (
            db.query(FinanceTransaction)
            .order_by(FinanceTransaction.created_at.desc())
            .all()
        )

        return [
            {
                "id": item.id,
                "amount": item.amount,
                "category": item.category,
                "description": item.description,
                "transaction_type": item.transaction_type,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]

    finally:
        db.close()


def get_school_subjects():
    db = SessionLocal()

    try:
        items = db.query(Subject).order_by(Subject.name).all()
        return [
            {
                "id": item.id,
                "name": item.name,
                "code": item.code,
                "semester": item.semester,
                "credits": item.credits,
                "active": item.active,
            }
            for item in items
        ]

    finally:
        db.close()


def get_school_assignments():
    db = SessionLocal()

    try:
        items = (
            db.query(Assignment)
            .order_by(Assignment.due_date.is_(None), Assignment.due_date)
            .all()
        )
        result = []
        for item in items:
            subject = db.query(Subject).filter(Subject.id == item.subject_id).first()
            result.append({
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "priority": item.priority,
                "status": item.status,
                "subject_id": item.subject_id,
                "subject_name": subject.name if subject else "",
            })
        return result

    finally:
        db.close()


def get_school_exams():
    db = SessionLocal()

    try:
        items = (
            db.query(Exam)
            .order_by(Exam.exam_date.is_(None), Exam.exam_date)
            .all()
        )
        result = []
        for item in items:
            subject = db.query(Subject).filter(Subject.id == item.subject_id).first()
            result.append({
                "id": item.id,
                "title": item.title,
                "exam_type": item.exam_type,
                "exam_date": item.exam_date.isoformat() if item.exam_date else None,
                "status": item.status,
                "notes": item.notes,
                "subject_id": item.subject_id,
                "subject_name": subject.name if subject else "",
            })
        return result

    finally:
        db.close()


def get_work_sessions():
    db = SessionLocal()

    try:
        items = (
            db.query(WorkSession)
            .order_by(WorkSession.date.desc(), WorkSession.id.desc())
            .all()
        )
        return [
            {
                "id": item.id,
                "date": item.date.isoformat(),
                "hours": item.hours,
                "project": item.project,
                "description": item.description,
                "hourly_rate": item.hourly_rate,
                "earnings": round(item.hours * item.hourly_rate, 2),
                "finance_transaction_id": item.finance_transaction_id,
                "sync_to_finance": bool(getattr(item, "sync_to_finance", True)),
            }
            for item in items
        ]

    finally:
        db.close()


def get_work_summary():
    db = SessionLocal()

    try:
        items = db.query(WorkSession).all()
        today = today_local()
        this_month = (today.year, today.month)

        total_hours = 0.0
        total_earnings = 0.0
        this_month_hours = 0.0
        this_month_earnings = 0.0

        for item in items:
            earn = item.hours * item.hourly_rate
            total_hours += item.hours
            total_earnings += earn
            if (item.date.year, item.date.month) == this_month:
                this_month_hours += item.hours
                this_month_earnings += earn

        return {
            "total_hours": round(total_hours, 2),
            "total_earnings": round(total_earnings, 2),
            "this_month_hours": round(this_month_hours, 2),
            "this_month_earnings": round(this_month_earnings, 2),
        }

    finally:
        db.close()


def add_work_session(
    date_value: str,
    hours: float,
    project: str,
    hourly_rate: float,
    description: str = "",
    sync_to_finance: bool = True,
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        item = WorkSession(
            date=date.fromisoformat(date_value),
            hours=hours,
            project=project,
            hourly_rate=hourly_rate,
            description=description,
            sync_to_finance=sync_to_finance,
        )

        db.add(item)
        db.flush()

        earnings = round(item.hours * item.hourly_rate, 2)
        finance_item = None
        if earnings > 0 and sync_to_finance and item.finance_transaction_id is None:
            f_desc = f"Work: {item.project or 'Práce'}"
            if item.description:
                f_desc = f"{f_desc} – {item.description}"
            finance_item = FinanceTransaction(
                amount=earnings,
                category="work",
                description=f_desc,
                transaction_type="income",
            )
            db.add(finance_item)
            db.flush()
            item.finance_transaction_id = finance_item.id

        work_summary = f"Práce {format_hours_cz(hours)}"
        if project:
            work_summary = f"{work_summary} – {project}"
        if description:
            work_summary = f"{work_summary} ({description})"
        log_activity(
            db, "work", "create", work_summary,
            entity_type="WorkSession", entity_id=item.id,
            delta=delta_dict(None, item, ["date", "hours", "project", "description", "hourly_rate", "sync_to_finance"]),
            user_context=user_context
        )

        if finance_item is not None:
            fin_summary = f"Zapsáno z Práce: příjem {format_czk_cz(earnings)}"
            if description:
                fin_summary = f"{fin_summary} – {description}"
            log_activity(
                db, "finance", "sync", fin_summary,
                entity_type="FinanceTransaction", entity_id=finance_item.id,
                delta=delta_dict(None, finance_item, ["amount", "category", "description", "transaction_type"]),
                user_context=user_context
            )

        db.commit()
        db.refresh(item)

        from goal_history_service import ensure_goal_progress_snapshot, compute_goal_progress_and_value

        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source.in_(["work_month_hours", "finance_balance"]))
            .all()
        )
        changed = 0
        for g in goals:
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context=user_context
                    )
                changed += 1
        if changed:
            db.commit()

        return {
            "id": item.id,
            "date": item.date.isoformat(),
            "hours": item.hours,
            "project": item.project,
            "hourly_rate": item.hourly_rate,
            "description": item.description,
            "earnings": earnings,
            "finance_transaction_id": item.finance_transaction_id,
            "sync_to_finance": sync_to_finance,
        }

    finally:
        db.close()


def add_finance_transaction(
    amount: float,
    category: str,
    transaction_type: str,
    description: str = "",
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        item = FinanceTransaction(
            amount=amount,
            category=category,
            description=description,
            transaction_type=transaction_type,
        )

        db.add(item)
        db.flush()

        summary = finance_summary_cz(transaction_type, amount, category, description)
        log_activity(
            db, "finance", "create", summary,
            entity_type="FinanceTransaction", entity_id=item.id,
            delta=delta_dict(None, item, ["amount", "category", "description", "transaction_type"]),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        from goal_history_service import ensure_goal_progress_snapshot, compute_goal_progress_and_value

        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source == "finance_balance")
            .all()
        )
        changed = 0
        for g in goals:
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context=user_context
                    )
                changed += 1
        if changed:
            db.commit()

        return {
            "id": item.id,
            "amount": item.amount,
            "category": item.category,
            "description": item.description,
            "transaction_type": item.transaction_type,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    finally:
        db.close()


def add_school_subject(
    name: str,
    code: str = "",
    semester: str = "",
    credits: int = 0,
    active: bool = True,
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        item = Subject(
            name=name,
            code=code,
            semester=semester,
            credits=credits,
            active=active,
        )
        db.add(item)
        db.flush()

        summary = f"Nový předmět: {name}"
        if code:
            summary = f"{summary} ({code})"
        if credits:
            summary = f"{summary}, {credits} ECTS"
        log_activity(
            db, "school", "create", summary,
            entity_type="Subject", entity_id=item.id,
            delta=delta_dict(None, item, ["name", "code", "semester", "credits", "active"]),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "name": item.name,
            "code": item.code,
            "semester": item.semester,
            "credits": item.credits,
            "active": item.active,
        }

    finally:
        db.close()


def add_school_assignment(
    title: str,
    subject_id: int,
    description: str = "",
    due_date: str | None = None,
    priority: str = "medium",
    status: str = "todo",
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        item = Assignment(
            title=title,
            description=description,
            due_date=date.fromisoformat(due_date) if due_date else None,
            priority=priority,
            status=status,
            subject_id=subject_id,
        )
        db.add(item)
        db.flush()

        summary = f"Nový úkol: {title}"
        if due_date:
            summary = f"{summary}, termín {format_date_cz(item.due_date)}"
        log_activity(
            db, "school", "create", summary,
            entity_type="Assignment", entity_id=item.id,
            delta=delta_dict(None, item, ["title", "description", "due_date", "priority", "status", "subject_id"]),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "title": item.title,
            "description": item.description,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "priority": item.priority,
            "status": item.status,
            "subject_id": item.subject_id,
        }

    finally:
        db.close()


def add_school_exam(
    title: str,
    subject_id: int,
    exam_type: str = "exam",
    exam_date: str | None = None,
    status: str = "upcoming",
    notes: str = "",
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        item = Exam(
            title=title,
            exam_type=exam_type,
            exam_date=date.fromisoformat(exam_date) if exam_date else None,
            status=status,
            notes=notes,
            subject_id=subject_id,
        )
        db.add(item)
        db.flush()

        type_map = {"exam": "Zkouška", "colloquium": "Kolokvium", "test": "Test", "quiz": "Kvíz"}
        type_label = type_map.get(exam_type, exam_type)
        summary = f"{type_label}: {title}"
        if exam_date:
            summary = f"{summary} ({format_date_cz(item.exam_date)})"
        log_activity(
            db, "school", "create", summary,
            entity_type="Exam", entity_id=item.id,
            delta=delta_dict(None, item, ["title", "exam_type", "exam_date", "status", "notes", "subject_id"]),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "title": item.title,
            "exam_type": item.exam_type,
            "exam_date": item.exam_date.isoformat() if item.exam_date else None,
            "status": item.status,
            "notes": item.notes,
            "subject_id": item.subject_id,
        }

    finally:
        db.close()


def update_wot_resource(resource: str, amount: float, user_context: str = "manual"):
    db = SessionLocal()

    try:
        existing = (
            db.query(WotResource)
            .filter(WotResource.resource == resource)
            .first()
        )

        old_amount = None
        if existing:
            old_amount = float(existing.amount or 0.0)
            existing.amount = amount
            result_id = existing.id
            action_type = "update"
        else:
            item = WotResource(resource=resource, amount=amount)
            db.add(item)
            db.flush()
            result_id = item.id
            action_type = "create"

        if action_type == "update" and old_amount is not None:
            old_str = f"{old_amount:,.0f}".replace(",", " ")
            new_str = f"{float(amount):,.0f}".replace(",", " ")
            summary = f"Zdroj {resource}: {old_str} → {new_str}"
            delta = delta_dict(
                type("Temp", (), {"amount": old_amount})(),
                type("Temp", (), {"amount": float(amount)})(),
                ["amount"]
            )
            log_activity(
                db, "wot", action_type, summary,
                entity_type="WotResource", entity_id=result_id,
                delta=delta,
                user_context=user_context
            )
        else:
            amount_str = f"{float(amount):,.0f}".replace(",", " ")
            summary = f"Zdroj {resource} nastaven na {amount_str}"
            delta = delta_dict(None, type("Temp", (), {"amount": float(amount), "resource": resource})(), ["resource", "amount"])
            log_activity(
                db, "wot", action_type, summary,
                entity_type="WotResource", entity_id=result_id,
                delta=delta,
                user_context=user_context
            )

        db.commit()

        return {
            "id": result_id,
            "resource": resource,
            "amount": amount,
        }

    finally:
        db.close()


def upsert_wot_grind(
    tank: str,
    xp_remaining: float,
    priority: str = "medium",
    status: str = "active",
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        existing = (
            db.query(WotGrind)
            .filter(WotGrind.tank == tank)
            .first()
        )

        tracked_fields = ["xp_remaining", "priority", "status"]
        if existing:
            old_obj = WotGrind()
            for f in tracked_fields:
                setattr(old_obj, f, getattr(existing, f, None))

            existing.xp_remaining = xp_remaining
            existing.priority = priority
            existing.status = status
            result_id = existing.id

            xp_str = f"{float(xp_remaining or 0):,.0f}".replace(",", " ")
            summary = f"Grind {tank} upraven – zbývá {xp_str} XP"
            log_activity(
                db, "wot", "update", summary,
                entity_type="WotGrind", entity_id=result_id,
                delta=delta_dict(old_obj, existing, tracked_fields),
                user_context=user_context
            )
        else:
            item = WotGrind(
                tank=tank,
                xp_remaining=xp_remaining,
                priority=priority,
                status=status,
            )
            db.add(item)
            db.flush()
            result_id = item.id

            xp_str = f"{float(xp_remaining or 0):,.0f}".replace(",", " ")
            summary = f"Nový grind {tank} – zbývá {xp_str} XP"
            log_activity(
                db, "wot", "create", summary,
                entity_type="WotGrind", entity_id=result_id,
                delta=delta_dict(None, item, tracked_fields + ["tank"]),
                user_context=user_context
            )

        db.commit()

        return {
            "id": result_id,
            "tank": tank,
            "xp_remaining": xp_remaining,
            "priority": priority,
            "status": status,
        }

    finally:
        db.close()


def upsert_mff_character(
    name: str,
    tier: str = "T3",
    level: int = 80,
    uniform: str = "",
    ctp: str = "",
    artifact: str = "",
    priority: str = "medium",
    status: str = "built",
    notes: str = "",
    role: str = "",
    team: str = "",
    uru_state: str = "",
    iso8_set: str = "",
    build_completeness: int = 0,
    roles: list[str] | None = None,
    team_supports: str = "",
    uru_slots_total: int | None = None,
    uru_slots_filled: int | None = None,
    odin_blessings_count: int | None = None,
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        if roles is None:
            roles = legacy_role_string_to_list(role or "")
        if isinstance(roles, str):
            roles = legacy_role_string_to_list(roles)
        roles_clean = [r.strip() for r in (roles or []) if r and str(r).strip()]
        level_i = max(1, int(level or 80))
        def_ut, def_uf, def_ob = parse_legacy_uru_state(uru_state)
        ut = int(uru_slots_total) if uru_slots_total is not None else def_ut
        uf = int(uru_slots_filled) if uru_slots_filled is not None else def_uf
        ob = int(odin_blessings_count) if odin_blessings_count is not None else def_ob
        ut = max(0, ut)
        uf = max(0, min(uf, ut if ut > 0 else uf))
        ob = max(0, ob)
        ts = (team_supports or "").strip() or (team or "").strip()
        auto_bc = compute_mff_build_completeness(
            tier,
            level_i,
            uniform,
            ctp,
            artifact,
            ut,
            uf,
            iso8_set,
            ts,
        )
        tracked_fields = ["tier", "build_completeness", "status", "priority"]
        existing = (
            db.query(MffCharacter)
            .filter(MffCharacter.name == name)
            .first()
        )
        if existing:
            old_obj = MffCharacter()
            for f in tracked_fields + ["level", "uniform", "ctp", "artifact", "notes"]:
                setattr(old_obj, f, getattr(existing, f, None))
            old_tier = existing.tier
            old_bc = int(getattr(existing, "build_completeness", 0) or 0)
            old_status = (existing.status or "").strip().lower()
            old_priority = (existing.priority or "").strip().lower()

            existing.tier = tier
            existing.level = level_i
            existing.uniform = (uniform or "").strip()
            existing.ctp = (ctp or "").strip()
            existing.artifact = (artifact or "").strip()
            existing.priority = (priority or "medium").strip().lower()
            cur_status = (existing.status or "").strip().lower()
            new_status = (status or cur_status or "built").strip().lower()
            if cur_status == "built" or new_status != cur_status:
                existing.status = new_status
            existing.notes = (notes or "").strip()
            existing.role = (role or "").strip()
            existing.team = (team or "").strip()
            existing.uru_state = (uru_state or "").strip()
            existing.iso8_set = (iso8_set or "").strip()
            existing.roles = roles_clean
            existing.team_supports = ts
            existing.uru_slots_total = ut
            existing.uru_slots_filled = uf
            existing.odin_blessings_count = ob
            existing.build_completeness = max(0, min(100, int(auto_bc)))
            result_id = existing.id

            new_tier = existing.tier
            new_bc = int(getattr(existing, "build_completeness", 0) or 0)
            new_status = (existing.status or "").strip().lower()
            new_priority = (existing.priority or "").strip().lower()
            parts = []
            if old_tier != new_tier:
                parts.append(f"Tier {old_tier or '?'} → {new_tier}")
            if old_bc != new_bc:
                parts.append(f"Build {old_bc}% → {new_bc}%")
            if old_status != new_status:
                parts.append(f"Status {old_status} → {new_status}")
            if old_priority != new_priority:
                parts.append(f"Priorita {old_priority} → {new_priority}")
            summary = f"Postava '{name}' upravena"
            if parts:
                summary = f"Postava '{name}': " + ", ".join(parts)
            log_activity(
                db, "mff", "update", summary,
                entity_type="MffCharacter", entity_id=result_id,
                delta=delta_dict(old_obj, existing, tracked_fields),
                user_context=user_context
            )
        else:
            item = MffCharacter(
                name=name,
                tier=tier,
                level=level_i,
                uniform=(uniform or "").strip(),
                ctp=(ctp or "").strip(),
                artifact=(artifact or "").strip(),
                priority=(priority or "medium").strip().lower(),
                status=(status or "built").strip().lower(),
                notes=(notes or "").strip(),
                role=(role or "").strip(),
                team=(team or "").strip(),
                uru_state=(uru_state or "").strip(),
                iso8_set=(iso8_set or "").strip(),
                build_completeness=max(0, min(100, int(auto_bc))),
                roles=roles_clean,
                team_supports=ts,
                uru_slots_total=ut,
                uru_slots_filled=uf,
                odin_blessings_count=ob,
            )
            db.add(item)
            db.flush()
            result_id = item.id

            bc = max(0, min(100, int(auto_bc)))
            summary = f"Nová postava '{name}' ({tier}, {bc}%)"
            log_activity(
                db, "mff", "create", summary,
                entity_type="MffCharacter", entity_id=result_id,
                delta=delta_dict(None, item, tracked_fields),
                user_context=user_context
            )

        db.commit()

        from goal_history_service import ensure_goal_progress_snapshot

        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source.in_(["mff_t4_count", "mff_built_t4_count", "mff_high_priority_built_count"]))
            .all()
        )
        changed = 0
        for g in goals:
            before_pct = None
            from goal_history_service import compute_goal_progress_and_value
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context=user_context
                    )
                changed += 1
        if changed:
            db.commit()

        return {
            "id": result_id,
            "name": name,
            "tier": tier,
            "level": level_i,
            "uniform": (uniform or "").strip(),
            "ctp": (ctp or "").strip(),
            "artifact": (artifact or "").strip(),
            "priority": (priority or "medium").strip().lower(),
            "status": (status or "built").strip().lower(),
            "notes": (notes or "").strip(),
            "role": (role or "").strip(),
            "team": (team or "").strip(),
            "uru_state": (uru_state or "").strip(),
            "iso8_set": (iso8_set or "").strip(),
            "roles": roles_clean,
            "team_supports": ts,
            "uru_slots_total": ut,
            "uru_slots_filled": uf,
            "odin_blessings_count": ob,
            "build_completeness": max(0, min(100, int(auto_bc))),
        }

    finally:
        db.close()


def upsert_goal(
    area: str,
    title: str,
    id: int | None = None,
    description: str = "",
    status: str = "active",
    priority: str = "medium",
    progress: int = 0,
    target_date: str | None = None,
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        progress_clamped = max(0, min(100, int(progress or 0)))
        from goal_history_service import ensure_goal_progress_snapshot, compute_goal_progress_and_value

        if id is not None:
            existing = db.query(Goal).filter(Goal.id == id).first()
            if existing:
                tracked_fields = ["area", "title", "description", "status", "priority", "progress", "target_date"]
                old_obj = Goal()
                for f in tracked_fields:
                    setattr(old_obj, f, getattr(existing, f, None))

                before_pct, _ = compute_goal_progress_and_value(db, existing)

                existing.area = area
                existing.title = title
                existing.description = description
                existing.status = status
                existing.priority = priority
                existing.progress = progress_clamped
                existing.target_date = (
                    date.fromisoformat(target_date) if target_date else None
                )

                update_summary = f"Cíl upraven: '{title}' ({area})"
                if old_obj.progress != progress_clamped:
                    update_summary = f"{update_summary} – progress {old_obj.progress}%→{progress_clamped}%"
                log_activity(
                    db, "goals", "update", update_summary,
                    entity_type="Goal", entity_id=existing.id,
                    delta=delta_dict(old_obj, existing, tracked_fields),
                    user_context=user_context
                )

                db.commit()

                after_pct, _ = compute_goal_progress_and_value(db, existing)
                if ensure_goal_progress_snapshot(db, existing):
                    after_snap_pct, _ = compute_goal_progress_and_value(db, existing)
                    if after_pct != after_snap_pct:
                        log_activity(
                            db, "goals", "snapshot",
                            f"Cíl '{existing.title}' {after_pct}% → {after_snap_pct}%",
                            entity_type="Goal", entity_id=existing.id,
                            user_context=user_context
                        )
                    db.commit()
                return {
                    "id": existing.id,
                    "area": existing.area,
                    "title": existing.title,
                    "description": existing.description,
                    "status": existing.status,
                    "priority": existing.priority,
                    "progress": existing.progress,
                    "target_date": (
                        existing.target_date.isoformat()
                        if existing.target_date
                        else None
                    ),
                    "updated": True,
                }

        item = Goal(
            area=area,
            title=title,
            description=description,
            status=status,
            priority=priority,
            progress=progress_clamped,
            target_date=date.fromisoformat(target_date) if target_date else None,
        )
        db.add(item)
        db.flush()

        create_summary = f"Nový cíl: '{title}' ({area}, {progress_clamped}%)"
        tracked_fields = ["area", "title", "description", "status", "priority", "progress", "target_date"]
        log_activity(
            db, "goals", "create", create_summary,
            entity_type="Goal", entity_id=item.id,
            delta=delta_dict(None, item, tracked_fields),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        after_pct, _ = compute_goal_progress_and_value(db, item)
        if ensure_goal_progress_snapshot(db, item):
            after_snap_pct, _ = compute_goal_progress_and_value(db, item)
            if after_pct != after_snap_pct:
                log_activity(
                    db, "goals", "snapshot",
                    f"Cíl '{item.title}' {after_pct}% → {after_snap_pct}%",
                    entity_type="Goal", entity_id=item.id,
                    user_context=user_context
                )
            db.commit()

        return {
            "id": item.id,
            "area": item.area,
            "title": item.title,
            "description": item.description,
            "status": item.status,
            "priority": item.priority,
            "progress": item.progress,
            "target_date": (
                item.target_date.isoformat() if item.target_date else None
            ),
            "updated": False,
        }

    finally:
        db.close()


def get_mff_characters():
    db = SessionLocal()

    try:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        items = (
            db.query(MffCharacter)
            .all()
        )
        result_items = []
        for item in items:
            roles_list = getattr(item, "roles", None)
            if roles_list is None or isinstance(roles_list, str):
                roles_list = legacy_role_string_to_list(roles_list if isinstance(roles_list, str) else (getattr(item, "role", "") or ""))
            ut = int(getattr(item, "uru_slots_total", 0) or 0)
            uf = int(getattr(item, "uru_slots_filled", 0) or 0)
            ob = int(getattr(item, "odin_blessings_count", 0) or 0)
            if ut <= 0:
                ut2, uf2, ob2 = parse_legacy_uru_state(getattr(item, "uru_state", "") or "")
                if ut <= 0:
                    ut = ut2 or 20
                if uf <= 0 and uf2:
                    uf = uf2
                if ob <= 0 and ob2:
                    ob = ob2
            ts = (getattr(item, "team_supports", None) or "") or (getattr(item, "team", "") or "")
            auto_bc = compute_mff_build_completeness(
                item.tier,
                item.level,
                item.uniform,
                item.ctp,
                item.artifact,
                ut,
                uf,
                item.iso8_set,
                ts,
            )
            db_bc = int(getattr(item, "build_completeness", 0) or 0)
            final_bc = auto_bc if db_bc == 0 or auto_bc >= db_bc else max(db_bc, auto_bc)
            result_items.append((
                item,
                {
                    "roles": roles_list,
                    "team_supports": ts,
                    "uru_slots_total": ut,
                    "uru_slots_filled": uf,
                    "odin_blessings_count": ob,
                    "build_completeness": max(0, min(100, int(final_bc))),
                },
            ))
        items_sorted = sorted(
            result_items,
            key=lambda pair: (
                priority_order.get(((pair[0].priority) or "").lower(), 3),
                int(pair[1]["build_completeness"]),
                (pair[0].name or "").lower(),
            ),
        )
        return [
            {
                "id": item.id,
                "name": item.name,
                "tier": item.tier,
                "level": item.level,
                "uniform": item.uniform,
                "ctp": item.ctp,
                "artifact": item.artifact,
                "priority": item.priority,
                "status": item.status,
                "notes": item.notes,
                "role": getattr(item, "role", "") or "",
                "team": getattr(item, "team", "") or "",
                "uru_state": getattr(item, "uru_state", "") or "",
                "iso8_set": getattr(item, "iso8_set", "") or "",
                "roles": extra["roles"],
                "team_supports": extra["team_supports"],
                "uru_slots_total": extra["uru_slots_total"],
                "uru_slots_filled": extra["uru_slots_filled"],
                "odin_blessings_count": extra["odin_blessings_count"],
                "build_completeness": extra["build_completeness"],
                "updated_at": (
                    item.updated_at.isoformat()
                    if getattr(item, "updated_at", None)
                    else None
                ),
            }
            for item, extra in items_sorted
        ]

    finally:
        db.close()


def get_mff_summary():
    db = SessionLocal()

    try:
        items = db.query(MffCharacter).all()
        tracked = len(items)
        t4 = 0
        t3 = 0
        priority_high = 0
        built_count = 0
        fully_built_t4 = 0
        build_sum = 0.0
        for it in items:
            t = (it.tier or "").lower().replace(" ", "")
            is_t4 = t in ("t4", "tier4", "transcendent")
            if is_t4:
                t4 += 1
            elif t in ("t3", "tier3"):
                t3 += 1
            if (it.priority or "").lower() == "high":
                priority_high += 1
            if (it.status or "").strip().lower() == "built":
                built_count += 1
            roles_list = getattr(it, "roles", None)
            if roles_list is None or isinstance(roles_list, str):
                roles_list = legacy_role_string_to_list(roles_list if isinstance(roles_list, str) else (getattr(it, "role", "") or ""))
            ut = int(getattr(it, "uru_slots_total", 0) or 0)
            uf = int(getattr(it, "uru_slots_filled", 0) or 0)
            ob = int(getattr(it, "odin_blessings_count", 0) or 0)
            if ut <= 0:
                ut2, uf2, ob2 = parse_legacy_uru_state(getattr(it, "uru_state", "") or "")
                if ut <= 0:
                    ut = ut2 or 20
                if uf <= 0 and uf2:
                    uf = uf2
                if ob <= 0 and ob2:
                    ob = ob2
            ts = (getattr(it, "team_supports", None) or "") or (getattr(it, "team", "") or "")
            bc = compute_mff_build_completeness(
                it.tier,
                it.level,
                it.uniform,
                it.ctp,
                it.artifact,
                ut,
                uf,
                it.iso8_set,
                ts,
            )
            if is_t4 and bc >= 100:
                fully_built_t4 += 1
            build_sum += float(bc)
        avg_bc = 0 if tracked == 0 else int(round(build_sum / tracked))
        return {
            "tracked_characters": tracked,
            "t4_count": t4,
            "t3_count": t3,
            "priority_count": priority_high,
            "built_count": built_count,
            "fully_built_t4_count": fully_built_t4,
            "average_build_completeness": avg_bc,
        }

    finally:
        db.close()


def get_goals():
    db = SessionLocal()

    try:
        from goal_history_service import compute_automatic_goal_current_value_with_ok

        priority_order = {"high": 0, "medium": 1, "low": 2}
        status_order = {
            "active": 0,
            "in_progress": 1,
            "paused": 2,
            "cancelled": 3,
            "completed": 4,
        }
        items = db.query(Goal).all()
        result = []
        for it in items:
            tracking_type = (it.tracking_type or "manual").lower()
            target_value = it.target_value
            source = it.source
            current_value = None
            if tracking_type == "automatic" and source and target_value and float(target_value) > 0:
                cv, ok = compute_automatic_goal_current_value_with_ok(db, source)
                if ok:
                    current_value = cv
                    progress_int = min(
                        100,
                        max(0, int(round(float(current_value) / float(target_value) * 100))),
                    )
                else:
                    progress_int = max(0, min(100, int(it.progress or 0)))
            else:
                progress_int = max(0, min(100, int(it.progress or 0)))

            result.append({
                "id": it.id,
                "area": it.area,
                "title": it.title,
                "description": it.description or "",
                "status": it.status,
                "priority": it.priority,
                "progress": progress_int,
                "tracking_type": tracking_type,
                "target_value": float(target_value) if target_value is not None else None,
                "source": source,
                "current_value": float(current_value) if current_value is not None else None,
                "target_date": it.target_date.isoformat() if it.target_date else None,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            })

        result.sort(
            key=lambda g: (
                status_order.get((g["status"] or "").lower(), 99),
                priority_order.get((g["priority"] or "").lower(), 3),
                -(g["progress"] or 0),
            ),
        )
        return result

    finally:
        db.close()


def get_goals_summary():
    db = SessionLocal()

    try:
        items = db.query(Goal).all()
        counts = {
            "active": 0,
            "in_progress": 0,
            "completed": 0,
            "paused": 0,
            "cancelled": 0,
        }
        for it in items:
            key = (it.status or "").lower()
            if key in counts:
                counts[key] += 1
        return {
            "active": counts["active"],
            "in_progress": counts["in_progress"],
            "completed": counts["completed"],
            "paused": counts["paused"],
            "cancelled": counts["cancelled"],
            "total": len(items),
        }

    finally:
        db.close()


def get_memories(area: str | None = None, category: str | None = None):
    db = SessionLocal()

    try:
        query = db.query(Memory).filter(Memory.active == True)
        if area:
            query = query.filter(Memory.area == area)
        if category:
            query = query.filter(Memory.category == category)

        items = query.order_by(Memory.importance.desc(), Memory.updated_at.desc()).all()

        return [
            {
                "id": it.id,
                "area": it.area,
                "category": it.category,
                "content": it.content,
                "importance": it.importance,
                "active": it.active,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ]

    finally:
        db.close()


def save_memory(
    area: str = "general",
    category: str = "context",
    content: str = "",
    importance: int = 5,
    active: bool = True,
    user_context: str = "manual",
):
    db = SessionLocal()

    try:
        importance_clamped = max(1, min(10, int(importance or 5)))

        item = Memory(
            area=area,
            category=category,
            content=content,
            importance=importance_clamped,
            active=bool(active),
        )
        db.add(item)
        db.flush()

        content_preview = (content or "").strip()
        if len(content_preview) > 60:
            content_preview = content_preview[:60].rstrip() + "…"
        log_activity(
            db, "memory", "create", f"Poznámka přidána do paměti: {content_preview}",
            entity_type="Memory", entity_id=item.id,
            delta=delta_dict(None, item, ["area", "category", "content", "importance", "active"]),
            user_context=user_context
        )

        db.commit()
        db.refresh(item)

        return {
            "status": "ok",
            "id": item.id,
            "area": item.area,
            "category": item.category,
            "content": item.content,
            "importance": item.importance,
            "active": item.active,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }

    finally:
        db.close()


def get_notifications(
    unread_only: bool = False,
    severity: str | None = None,
    area: str | None = None,
    include_resolved: bool = False,
):
    db = SessionLocal()
    try:
        from notifications_service import list_notifications

        return list_notifications(
            db,
            unread_only=bool(unread_only),
            severity=severity,
            area=area,
            include_resolved=bool(include_resolved),
        )
    finally:
        db.close()


def get_notification_summary():
    db = SessionLocal()
    try:
        from notifications_service import notifications_summary

        return notifications_summary(db)
    finally:
        db.close()


def get_goal_progress_history(goal_id: int):
    db = SessionLocal()
    try:
        rows = (
            db.query(GoalProgressHistory)
            .filter(GoalProgressHistory.goal_id == goal_id)
            .order_by(GoalProgressHistory.recorded_at.asc(), GoalProgressHistory.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "goal_id": r.goal_id,
                "progress": int(r.progress or 0),
                "current_value": float(r.current_value) if r.current_value is not None else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()
