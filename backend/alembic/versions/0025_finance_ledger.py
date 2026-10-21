"""Finance v1 ledger: accounts, imports, import issues, categories, rules, revisions + evolved transactions (MRK-61).

Additive. `finance_transactions` keeps every legacy column and row (`amount`, `category`, `created_at` untouched) and
gains the ledger columns. Existing rows move to the built-in „Ruční / hotovost“ account (CZK) with
`amount_minor` = round(amount × 100) signed by type, `booked_on` = Prague date of `created_at` (the migration day when
`created_at` is missing), `source` = work_sync where a work session links the row, else manual, and the legacy
category mapped onto a built-in category as a manual override. Category seeds are a frozen copy of
`modules/finance/categories.py`. No statement data, filenames or account numbers are stored.

Downgrade refuses while anything exists that it would lose or resurrect (imports, rules, revisions, user accounts or
categories, voided rows, imported rows, extra user data) – remove it deliberately first.

Revision ID: 0025_finance_ledger
Revises: 0024_offsite_backup_runs
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
import unicodedata
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision = '0025_finance_ledger'
down_revision = '0024_offsite_backup_runs'
branch_labels = None
depends_on = None

PRAGUE = ZoneInfo('Europe/Prague')
MANUAL_ACCOUNT_KEY = 'manual_cash'

CATEGORIES = (  # frozen: (key, name, kind, parent key)
    ('housing', 'Bydlení', 'expense', None), ('food', 'Potraviny', 'expense', None),
    ('restaurants', 'Restaurace a jídlo', 'expense', None), ('transport', 'Doprava', 'expense', None),
    ('shopping', 'Nákupy', 'expense', None), ('health', 'Zdraví', 'expense', None),
    ('entertainment', 'Zábava', 'expense', None), ('education', 'Vzdělávání', 'expense', None),
    ('subscriptions', 'Předplatné', 'expense', None), ('income', 'Příjmy', 'income', None),
    ('salary', 'Výplata', 'income', 'income'), ('income_other', 'Ostatní příjmy', 'income', 'income'),
    ('other', 'Ostatní', 'expense', None), ('transfers', 'Převody', 'transfer', None),
    ('uncategorized', 'Nezařazeno', 'system', None),
)
LEGACY_KEYS = {  # frozen copy of categories.LEGACY_CATEGORY_KEYS
    'bydleni': 'housing', 'najem': 'housing', 'energie': 'housing', 'housing': 'housing', 'rent': 'housing',
    'potraviny': 'food', 'food': 'food', 'groceries': 'food',
    'jidlo': 'restaurants', 'restaurace': 'restaurants', 'restaurants': 'restaurants',
    'doprava': 'transport', 'transport': 'transport', 'nakupy': 'shopping', 'shopping': 'shopping',
    'zdravi': 'health', 'health': 'health', 'zabava': 'entertainment', 'entertainment': 'entertainment',
    'vzdelavani': 'education', 'skola': 'education', 'education': 'education',
    'predplatne': 'subscriptions', 'subscriptions': 'subscriptions',
    'vyplata': 'salary', 'plat': 'salary', 'salary': 'salary', 'work': 'salary', 'prace': 'salary',
    'prijem': 'income_other', 'income': 'income_other',
    'prevod': 'transfers', 'prevody': 'transfers', 'transfer': 'transfers', 'ostatni': 'other', 'other': 'other',
}
NEW_NOT_NULL = ('account_id', 'source', 'booked_on', 'amount_minor', 'currency', 'direction', 'review_flag')


def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', (text or '').lower()) if not unicodedata.combining(c))


def _category_key(text, direction):
    key = LEGACY_KEYS.get(_fold(text).strip())
    if key is None:
        return 'income_other' if direction == 'in' else 'other'
    if direction == 'in' and key not in ('salary', 'income_other', 'transfers'):
        return 'income_other'
    return key


def _new_columns(not_null=False):
    """Ledger columns; `not_null` = final shape (after backfill)."""
    nn = (lambda name: not not_null or name not in NEW_NOT_NULL)
    return [
        sa.Column('account_id', sa.Integer(), nullable=nn('account_id')),
        sa.Column('import_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(20), nullable=nn('source')),
        sa.Column('booked_on', sa.Date(), nullable=nn('booked_on')),
        sa.Column('value_on', sa.Date(), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=nn('amount_minor')),
        sa.Column('currency', sa.String(3), nullable=nn('currency')),
        sa.Column('direction', sa.String(3), nullable=nn('direction')),
        sa.Column('counterparty_name', sa.String(200), nullable=True),
        sa.Column('counterparty_account_masked', sa.String(40), nullable=True),
        sa.Column('counterparty_account_hash', sa.String(64), nullable=True),
        sa.Column('vs', sa.String(10), nullable=True),
        sa.Column('ks', sa.String(10), nullable=True),
        sa.Column('ss', sa.String(10), nullable=True),
        sa.Column('txn_key', sa.String(128), nullable=True),
        sa.Column('fingerprint', sa.String(64), nullable=True),
        sa.Column('extra', sa.Text(), nullable=True),
        sa.Column('system_category_id', sa.Integer(), nullable=True),
        sa.Column('category_source', sa.String(20), nullable=True),
        sa.Column('override_category_id', sa.Integer(), nullable=True),
        sa.Column('effective_category_id', sa.Integer(), nullable=True),
        sa.Column('transfer_link_id', sa.Integer(), nullable=True),
        sa.Column('review_flag', sa.Boolean(), nullable=nn('review_flag')),
        sa.Column('voided_at', sa.DateTime(), nullable=True),
        sa.Column('void_reason', sa.String(200), nullable=True),
        sa.Column('search_text', sa.String(600), nullable=True),
    ]


FKS = (  # (name, column, referred table)
    ('fk_finance_transactions_account_id', 'account_id', 'finance_accounts'),
    ('fk_finance_transactions_import_id', 'import_id', 'finance_imports'),
    ('fk_finance_transactions_system_category_id', 'system_category_id', 'finance_categories'),
    ('fk_finance_transactions_override_category_id', 'override_category_id', 'finance_categories'),
    ('fk_finance_transactions_effective_category_id', 'effective_category_id', 'finance_categories'),
    ('fk_finance_transactions_transfer_link_id', 'transfer_link_id', 'finance_transactions'),
)
CHECKS = (
    ('ck_finance_transactions_source', "source IN ('manual', 'work_sync', 'import')"),
    ('ck_finance_transactions_direction', "direction IN ('in', 'out')"),
    ('ck_finance_transactions_sign',
     "(direction = 'in' AND amount_minor >= 0) OR (direction = 'out' AND amount_minor <= 0)"),
    ('ck_finance_transactions_currency', 'length(currency) = 3'),
)
INDEXES = (
    ('ix_finance_transactions_account_booked', ['account_id', 'booked_on']),
    ('ix_finance_transactions_booked_on', ['booked_on']),
    ('ix_finance_transactions_category_booked', ['effective_category_id', 'booked_on']),
    ('ix_finance_transactions_fingerprint', ['fingerprint']),
)


def _legacy_columns():
    return [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('transaction_type', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    ]


def _transactions(ledger=None):
    """Exact table shape for SQLite batch recreation (constraints/indexes are not reliably reflected).
    ledger=None → legacy shape; False → + nullable ledger columns, no ledger constraints (backfill);
    True → final shape with NOT NULL and all ledger constraints/indexes."""
    items = [*_legacy_columns(), sa.PrimaryKeyConstraint('id'), sa.Index('ix_finance_transactions_id', 'id')]
    if ledger is not None:
        items += _new_columns(not_null=ledger)
    if ledger:
        items += [sa.ForeignKeyConstraint([col], [f'{ref}.id'], name=name, ondelete='RESTRICT') for name, col, ref in FKS]
        items += [sa.CheckConstraint(sql, name=name) for name, sql in CHECKS]
        items.append(sa.UniqueConstraint('account_id', 'txn_key', name='uq_finance_transactions_account_txn_key'))
        items += [sa.Index(name, *cols) for name, cols in INDEXES]
    return sa.Table('finance_transactions', sa.MetaData(), *items)


def _create_tables():
    op.create_table('finance_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(40), nullable=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('institution', sa.String(120), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('masked_identifier', sa.String(40), nullable=True),
        sa.Column('identifier_hash', sa.String(64), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('current', 'savings', 'card', 'cash', 'other')", name='ck_finance_accounts_kind'),
        sa.CheckConstraint('length(currency) = 3', name='ck_finance_accounts_currency'),
        sa.UniqueConstraint('key', name='uq_finance_accounts_key'),
        sa.UniqueConstraint('identifier_hash', name='uq_finance_accounts_identifier_hash'),
        sa.PrimaryKeyConstraint('id'))
    op.create_table('finance_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(40), nullable=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('expense', 'income', 'transfer', 'system')", name='ck_finance_categories_kind'),
        sa.ForeignKeyConstraint(['parent_id'], ['finance_categories.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('key', name='uq_finance_categories_key'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_finance_categories_parent_id', 'finance_categories', ['parent_id'])
    op.create_table('finance_imports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('adapter', sa.String(40), nullable=False),
        sa.Column('adapter_version', sa.String(20), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        *[sa.Column(f'count_{n}', sa.Integer(), nullable=False)
          for n in ('new', 'duplicate', 'changed', 'pending', 'rejected', 'possible_duplicate')],
        sa.Column('date_from', sa.Date(), nullable=True),
        sa.Column('date_to', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('previewed', 'committed', 'failed', 'cancelled')",
                           name='ck_finance_imports_status'),
        sa.ForeignKeyConstraint(['account_id'], ['finance_accounts.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('account_id', 'file_sha256', name='uq_finance_imports_account_sha'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_finance_imports_account_id', 'finance_imports', ['account_id'])
    op.create_table('finance_import_issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('import_id', sa.Integer(), nullable=False),
        sa.Column('row_no', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('field', sa.String(40), nullable=True),
        sa.ForeignKeyConstraint(['import_id'], ['finance_imports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_finance_import_issues_import_id', 'finance_import_issues', ['import_id'])
    op.create_table('finance_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('match_type', sa.String(20), nullable=False),
        sa.Column('pattern', sa.String(200), nullable=False),
        sa.Column('direction', sa.String(3), nullable=True),
        sa.Column('amount_min_minor', sa.BigInteger(), nullable=True),
        sa.Column('amount_max_minor', sa.BigInteger(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("match_type IN ('contains', 'starts_with', 'equals')", name='ck_finance_rules_match_type'),
        sa.CheckConstraint("direction IS NULL OR direction IN ('in', 'out')", name='ck_finance_rules_direction'),
        sa.ForeignKeyConstraint(['account_id'], ['finance_accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['category_id'], ['finance_categories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_finance_rules_active_priority', 'finance_rules', ['active', 'priority'])


def _seed(bind, now):
    accounts = sa.table('finance_accounts', sa.column('key'), sa.column('name'), sa.column('kind'),
                        sa.column('currency'), sa.column('created_at'))
    bind.execute(accounts.insert().values(key=MANUAL_ACCOUNT_KEY, name='Ruční / hotovost', kind='cash',
                                          currency='CZK', created_at=now))
    categories = sa.table('finance_categories', sa.column('id'), sa.column('key'), sa.column('name'),
                          sa.column('kind'), sa.column('parent_id'), sa.column('created_at'))
    ids = {}
    for key, name, kind, parent in CATEGORIES:
        bind.execute(categories.insert().values(key=key, name=name, kind=kind,
                                                parent_id=ids.get(parent) if parent else None, created_at=now))
        ids[key] = bind.execute(sa.text('SELECT id FROM finance_categories WHERE key = :k'), {'k': key}).scalar()
    account_id = bind.execute(sa.text('SELECT id FROM finance_accounts WHERE key = :k'),
                              {'k': MANUAL_ACCOUNT_KEY}).scalar()
    return account_id, ids


def _backfill(bind, account_id, category_ids, now):
    linked = {row[0] for row in bind.execute(sa.text(
        'SELECT DISTINCT finance_transaction_id FROM work_sessions WHERE finance_transaction_id IS NOT NULL'))}
    names = {key: name for key, name, _kind, _parent in CATEGORIES}
    today = now.replace(tzinfo=timezone.utc).astimezone(PRAGUE).date()
    rows = bind.execute(sa.text(
        'SELECT id, amount, category, description, transaction_type, created_at FROM finance_transactions')).fetchall()
    for tx_id, amount, category, description, tx_type, created_at in rows:
        direction = 'in' if (tx_type or '').strip().lower() == 'income' else 'out'
        minor = int((abs(Decimal(str(amount or 0))) * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if isinstance(created_at, str):  # SQLite vrací DateTime někdy jako text
            created_at = datetime.fromisoformat(created_at)
        booked_on = created_at.replace(tzinfo=timezone.utc).astimezone(PRAGUE).date() if created_at else today
        key = _category_key(category, direction)
        search = _fold(' '.join(p for p in (description, category, names[key]) if p)).strip()[:600]
        bind.execute(sa.text(
            'UPDATE finance_transactions SET account_id = :account, source = :source, booked_on = :booked, '
            'amount_minor = :minor, currency = :currency, direction = :direction, override_category_id = :cat, '
            'effective_category_id = :cat, category_source = :csource, review_flag = :flag, search_text = :search '
            'WHERE id = :id'),
            {'account': account_id, 'source': 'work_sync' if tx_id in linked else 'manual', 'booked': booked_on,
             'minor': minor if direction == 'in' else -minor, 'currency': 'CZK', 'direction': direction,
             'cat': category_ids[key], 'csource': 'legacy', 'flag': False, 'search': search, 'id': tx_id})


def upgrade():
    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _create_tables()
    account_id, category_ids = _seed(bind, now)
    with op.batch_alter_table('finance_transactions', copy_from=_transactions()) as batch:
        for column in _new_columns():
            batch.add_column(column)
    _backfill(bind, account_id, category_ids, now)
    with op.batch_alter_table('finance_transactions', copy_from=_transactions(ledger=False)) as batch:
        for name in NEW_NOT_NULL:
            column = next(c for c in _new_columns(not_null=True) if c.name == name)
            batch.alter_column(name, existing_type=column.type, nullable=False)
        for name, col, ref in FKS:
            batch.create_foreign_key(name, ref, [col], ['id'], ondelete='RESTRICT')
        for name, sql in CHECKS:
            batch.create_check_constraint(name, sql)
        batch.create_unique_constraint('uq_finance_transactions_account_txn_key', ['account_id', 'txn_key'])
        for name, cols in INDEXES:
            batch.create_index(name, cols)
    op.create_table('finance_transaction_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('import_id', sa.Integer(), nullable=True),
        sa.Column('changed', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['finance_transactions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['import_id'], ['finance_imports.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_finance_transaction_revisions_transaction_id', 'finance_transaction_revisions',
                    ['transaction_id'])


GUARDS = (  # (SQL count, what would be lost)
    ('SELECT COUNT(*) FROM finance_imports', 'imports'),
    ('SELECT COUNT(*) FROM finance_rules', 'rules'),
    ('SELECT COUNT(*) FROM finance_transaction_revisions', 'transaction revisions'),
    (f"SELECT COUNT(*) FROM finance_accounts WHERE key IS NULL OR key <> '{MANUAL_ACCOUNT_KEY}'", 'user accounts'),
    ('SELECT COUNT(*) FROM finance_categories WHERE key IS NULL', 'user categories'),
    ("SELECT COUNT(*) FROM finance_transactions WHERE source = 'import' OR import_id IS NOT NULL", 'imported rows'),
    ('SELECT COUNT(*) FROM finance_transactions WHERE voided_at IS NOT NULL', 'voided rows (would reappear)'),
    ('SELECT COUNT(*) FROM finance_transactions WHERE counterparty_name IS NOT NULL OR txn_key IS NOT NULL '
     'OR transfer_link_id IS NOT NULL OR value_on IS NOT NULL', 'ledger-only transaction data'),
)


def downgrade():
    bind = op.get_bind()
    blocking = [what for sql, what in GUARDS if bind.execute(sa.text(sql)).scalar()]
    if blocking:
        raise RuntimeError('finance ledger contains ' + ', '.join(blocking) +
                           '; remove it deliberately before downgrading 0025_finance_ledger')
    op.drop_index('ix_finance_transaction_revisions_transaction_id', table_name='finance_transaction_revisions')
    op.drop_table('finance_transaction_revisions')
    with op.batch_alter_table('finance_transactions', copy_from=_transactions(ledger=True)) as batch:
        for name, _cols in INDEXES:
            batch.drop_index(name)
        batch.drop_constraint('uq_finance_transactions_account_txn_key', type_='unique')
        for name, _sql in CHECKS:
            batch.drop_constraint(name, type_='check')
        for name, _col, _ref in FKS:
            batch.drop_constraint(name, type_='foreignkey')
        for column in _new_columns():
            batch.drop_column(column.name)
    op.drop_index('ix_finance_rules_active_priority', table_name='finance_rules')
    op.drop_table('finance_rules')
    op.drop_index('ix_finance_import_issues_import_id', table_name='finance_import_issues')
    op.drop_table('finance_import_issues')
    op.drop_index('ix_finance_imports_account_id', table_name='finance_imports')
    op.drop_table('finance_imports')
    op.drop_index('ix_finance_categories_parent_id', table_name='finance_categories')
    op.drop_table('finance_categories')
    op.drop_table('finance_accounts')
