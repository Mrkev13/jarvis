"""Finance v1 tables (MRK-61). Nothing here stores full account numbers, statement filenames or raw rows:
accounts keep a masked identifier + hash, imports keep a SHA-256 + counts, import issues keep row number + code."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)

from database import Base
from time_utils import utc_now

ACCOUNT_KINDS = ("current", "savings", "card", "cash", "other")
CATEGORY_KINDS = ("expense", "income", "transfer", "system")
IMPORT_STATUSES = ("previewed", "committed", "failed", "cancelled")
RULE_MATCH_TYPES = ("contains", "starts_with", "equals")
DIRECTIONS = ("in", "out")
SOURCES = ("manual", "work_sync", "import")
CATEGORY_SOURCES = ("legacy", "manual", "rule", "none")

# Built-in „Ruční / hotovost" account: legacy rows and manual entries live here (key is the stable identity).
MANUAL_ACCOUNT_KEY = "manual_cash"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class FinanceAccount(Base):
    __tablename__ = "finance_accounts"
    __table_args__ = (
        CheckConstraint(_in("kind", ACCOUNT_KINDS), name="ck_finance_accounts_kind"),
        CheckConstraint("length(currency) = 3", name="ck_finance_accounts_currency"),
        UniqueConstraint("key", name="uq_finance_accounts_key"),
        UniqueConstraint("identifier_hash", name="uq_finance_accounts_identifier_hash"),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(40))  # jen vestavěné účty (MANUAL_ACCOUNT_KEY)
    name = Column(String(120), nullable=False)
    institution = Column(String(120))
    kind = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False)
    masked_identifier = Column(String(40))  # např. „…1234"; nikdy celé číslo účtu
    identifier_hash = Column(String(64))  # HMAC/SHA-256 normalizovaného čísla – párování bez uložení čísla
    archived_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class FinanceCategory(Base):
    __tablename__ = "finance_categories"
    __table_args__ = (
        CheckConstraint(_in("kind", CATEGORY_KINDS), name="ck_finance_categories_kind"),
        UniqueConstraint("key", name="uq_finance_categories_key"),
        Index("ix_finance_categories_parent_id", "parent_id"),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(40))  # jen vestavěné kategorie; uživatelské mají NULL
    name = Column(String(80), nullable=False)
    parent_id = Column(Integer, ForeignKey("finance_categories.id", ondelete="RESTRICT"))
    kind = Column(String(10), nullable=False)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class FinanceImport(Base):
    __tablename__ = "finance_imports"
    __table_args__ = (
        CheckConstraint(_in("status", IMPORT_STATUSES), name="ck_finance_imports_status"),
        UniqueConstraint("account_id", "file_sha256", name="uq_finance_imports_account_sha"),
        Index("ix_finance_imports_account_id", "account_id"),
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("finance_accounts.id", ondelete="RESTRICT"), nullable=False)
    adapter = Column(String(40), nullable=False)
    adapter_version = Column(String(20), nullable=False)
    file_sha256 = Column(String(64), nullable=False)  # žádný název souboru – ten může nést osobní údaje
    size_bytes = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False)
    count_new = Column(Integer, nullable=False, default=0)
    count_duplicate = Column(Integer, nullable=False, default=0)
    count_changed = Column(Integer, nullable=False, default=0)
    count_pending = Column(Integer, nullable=False, default=0)
    count_rejected = Column(Integer, nullable=False, default=0)
    count_possible_duplicate = Column(Integer, nullable=False, default=0)
    date_from = Column(Date)
    date_to = Column(Date)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime)


class FinanceImportIssue(Base):
    """Problém řádku importu: číslo řádku + bezpečný kód (+ název pole). Nikdy hodnota z výpisu."""
    __tablename__ = "finance_import_issues"
    __table_args__ = (Index("ix_finance_import_issues_import_id", "import_id"),)
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("finance_imports.id", ondelete="CASCADE"), nullable=False)
    row_no = Column(Integer, nullable=False)
    code = Column(String(40), nullable=False)
    field = Column(String(40))


class FinanceRule(Base):
    __tablename__ = "finance_rules"
    __table_args__ = (
        CheckConstraint(_in("match_type", RULE_MATCH_TYPES), name="ck_finance_rules_match_type"),
        CheckConstraint(f"direction IS NULL OR {_in('direction', DIRECTIONS)}", name="ck_finance_rules_direction"),
        Index("ix_finance_rules_active_priority", "active", "priority"),
    )
    id = Column(Integer, primary_key=True)
    priority = Column(Integer, nullable=False, default=100)
    match_type = Column(String(20), nullable=False)
    pattern = Column(String(200), nullable=False)  # normalizovaný (text_utils.fold_text)
    direction = Column(String(3))
    amount_min_minor = Column(BigInteger)
    amount_max_minor = Column(BigInteger)
    account_id = Column(Integer, ForeignKey("finance_accounts.id", ondelete="RESTRICT"))
    category_id = Column(Integer, ForeignKey("finance_categories.id", ondelete="RESTRICT"), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class FinanceTransactionRevision(Base):
    """Staré hodnoty importovaných polí, když je pozdější import změní (MRK-62); historie se nepřepisuje."""
    __tablename__ = "finance_transaction_revisions"
    __table_args__ = (Index("ix_finance_transaction_revisions_transaction_id", "transaction_id"),)
    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("finance_transactions.id", ondelete="RESTRICT"), nullable=False)
    import_id = Column(Integer, ForeignKey("finance_imports.id", ondelete="RESTRICT"))
    changed = Column(Text, nullable=False)  # JSON {pole: stará hodnota}, jen allowlist importovaných polí
    created_at = Column(DateTime, nullable=False, default=utc_now)
