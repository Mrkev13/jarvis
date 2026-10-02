"""reconcile_schema_drift

Sjednotí schéma se SQLAlchemy modely (models.py) ze dvou výchozích stavů:
  a) čistá DB migrovaná 0001 → 0006 (názvy indexů / nullability dle migrací),
  b) původní produkční DB vytvořená přes create_all a následně stampnutá na 0006.
Každá operace se řídí aktuálním stavem DB (inspector), takže upgrade je pro oba
stavy idempotentní. NULL hodnoty ve sloupcích, které mají být NOT NULL, migraci
zastaví – žádné hodnoty se nevymýšlejí.

Revision ID: 0007_reconcile_schema_drift
Revises: 0006_auth_sessions
Create Date: 2026-10-02 00:00:07.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0007_reconcile_schema_drift"
down_revision = "0006_auth_sessions"
branch_labels = None
depends_on = None


# Sloupce, které jsou v modelech NOT NULL: (tabulka, sloupec, typ).
NOT_NULL_COLUMNS = [
    ("finance_transactions", "category", sa.String(length=100)),
    ("finance_transactions", "transaction_type", sa.String(length=20)),
    ("goals", "area", sa.String(length=50)),
    ("auth_sessions", "revoked", sa.Boolean()),
    ("backup_logs", "retention_days", sa.Integer()),
]

# Cílové indexy dle models.py: (tabulka, název, sloupce, unique).
MODEL_INDEXES = [
    ("finance_transactions", "ix_finance_transactions_id", ["id"], False),
    ("goals", "ix_goals_id", ["id"], False),
    ("memories", "ix_memories_id", ["id"], False),
    ("mff_characters", "ix_mff_characters_tier", ["tier"], False),
    ("mff_characters", "ix_mff_characters_priority", ["priority"], False),
    ("mff_characters", "ix_mff_characters_status", ["status"], False),
    ("mff_characters", "ix_mff_characters_build_completeness", ["build_completeness"], False),
    ("auth_sessions", "ix_auth_sessions_token_hash", ["token_hash"], True),
    ("auth_sessions", "ix_auth_sessions_last_seen_at", ["last_seen_at"], False),
    ("backup_logs", "ix_backup_logs_started_at", ["started_at"], False),
    ("pending_actions", "ix_pending_actions_status", ["status"], False),
]

# Indexy z 0005/0006, které nahrazují názvy dle modelů výše.
LEGACY_INDEXES = [
    ("auth_sessions", "ix_auth_token_hash", ["token_hash"], True),
    ("auth_sessions", "ix_auth_expires_at", ["expires_at"], False),
    ("backup_logs", "ix_backup_started_at", ["started_at"], False),
]

# UNIQUE constrainty duplikující unique index (pojmenované jen v PostgreSQL;
# nepojmenované SQLite inline constrainty se nechávají – nelze je adresovat).
REDUNDANT_UNIQUE_CONSTRAINTS = [
    ("activity_logs", ["dedupe_key"]),
    ("auth_sessions", ["token_hash"]),
]

# Nullability sloupců po 0006 (pro downgrade): jen ty, které upgrade mění na čisté DB.
NULLABLE_IN_0006 = {("auth_sessions", "revoked"), ("backup_logs", "retention_days")}


def _inspector():
    return sa.inspect(op.get_bind())


def _indexes(table: str) -> dict:
    return {ix["name"]: ix for ix in _inspector().get_indexes(table)}


def _assert_no_nulls() -> None:
    bind = op.get_bind()
    problems = []
    for table, column, _type in NOT_NULL_COLUMNS:
        count = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
        ).scalar()
        if count:
            problems.append(f"{table}.{column}: {count} NULL")
    if problems:
        raise RuntimeError(
            "0007_reconcile_schema_drift přerušena – NULL hodnoty ve sloupcích, "
            "které musí být NOT NULL: " + ", ".join(problems)
            + ". Oprav data ručně a spusť upgrade znovu (migrace hodnoty nevymýšlí)."
        )


def _set_nullable(columns: list[tuple[str, str, sa.types.TypeEngine]], nullable: bool) -> None:
    by_table: dict[str, list] = {}
    for table, column, type_ in columns:
        current = next(c for c in _inspector().get_columns(table) if c["name"] == column)
        if current["nullable"] != nullable:
            by_table.setdefault(table, []).append((column, type_))
    for table, cols in by_table.items():
        # batch: v SQLite rekreace tabulky, v PostgreSQL přímý ALTER COLUMN.
        with op.batch_alter_table(table) as batch:
            for column, type_ in cols:
                batch.alter_column(column, existing_type=type_, nullable=nullable)


def _ensure_index(table: str, name: str, columns: list[str], unique: bool) -> None:
    existing = _indexes(table).get(name)
    if existing is not None:
        if list(existing["column_names"]) == columns and bool(existing["unique"]) == unique:
            return
        op.drop_index(name, table_name=table)
    op.create_index(name, table, columns, unique=unique)


def _drop_index_if_exists(table: str, name: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def _named_unique_constraints(table: str, columns: list[str]) -> list[str]:
    return [
        uc["name"]
        for uc in _inspector().get_unique_constraints(table)
        if uc.get("name") and list(uc["column_names"]) == columns
    ]


def upgrade() -> None:
    _assert_no_nulls()
    _set_nullable(NOT_NULL_COLUMNS, nullable=False)

    # Nejdřív vytvořit cílové indexy, pak teprve rušit staré – unikátnost token_hash
    # tak nezůstane ani na okamžik nehlídaná.
    for table, name, columns, unique in MODEL_INDEXES:
        _ensure_index(table, name, columns, unique)
    for table, name, _columns, _unique in LEGACY_INDEXES:
        _drop_index_if_exists(table, name)
    for table, columns in REDUNDANT_UNIQUE_CONSTRAINTS:
        for name in _named_unique_constraints(table, columns):
            op.drop_constraint(name, table, type_="unique")


def downgrade() -> None:
    """Návrat do tvaru, který vytváří řetězec migrací 0001 → 0006.

    Pro DB původně vytvořenou přes create_all to znamená tvar dle migrací,
    ne původní nekonzistentní stav (ten se záměrně neobnovuje).
    """
    for table, name, columns, unique in LEGACY_INDEXES:
        _ensure_index(table, name, columns, unique)
    if not _named_unique_constraints("auth_sessions", ["token_hash"]) and op.get_bind().dialect.name != "sqlite":
        op.create_unique_constraint("auth_sessions_token_hash_key", "auth_sessions", ["token_hash"])
    for table, name in (
        ("auth_sessions", "ix_auth_sessions_token_hash"),
        ("auth_sessions", "ix_auth_sessions_last_seen_at"),
        ("backup_logs", "ix_backup_logs_started_at"),
        ("pending_actions", "ix_pending_actions_status"),
    ):
        _drop_index_if_exists(table, name)
    _set_nullable(
        [c for c in NOT_NULL_COLUMNS if (c[0], c[1]) in NULLABLE_IN_0006],
        nullable=True,
    )
