# Finance

Status: legacy module + Finance v1 in progress (Linear milestone "Finance v1 — mBank import", MRK-60…MRK-68).

## Finance is not part of AI (MRK-60)

Finance holds real bank data. In Finance v1 **no Finance data reaches an LLM**: no transactions, no balances,
no monthly totals or other aggregates. Bank/manual imports become the source of truth for real cashflow, so
Finance stays a deterministic module (pages, Search, dashboard, Quick Add, What Changed).

What that means in code (one rule, `backend/finance_ai_policy.py`):

| Surface | Behaviour |
|---|---|
| CURRENT STATE (`context_service`) | Module `finance` has no `ai_context` capability. Its `ContextSection` carries only keywords (no `build`, no data), so a Finance question is recognised as an area **without** tools. |
| AI tool routing (`tool_router`) | A Finance-only request gets **no tools**; a write request naming only Finance gets no substitute write tools of other areas. |
| AI tools (`tool_registry`) | No `get_finance_summary` / `get_finance_transactions`. `add_finance_transaction` is in `MANUAL_ONLY_SPECS`: Quick Add can use it, the model never sees it, and `execute_confirm_action` refuses it for a non-manual source. |
| AI edit / undo (`mutation_service`) | No `finance_transaction` entity. Older AI plans or undo records for Finance are refused without any change. |
| Goals | Automatic goals computed from Finance (`source` `finance_*`) are hidden from AI context, AI goal tools, AI goal edits, the daily briefing and the weekly review. Manual goals with area "finance" are ordinary Goals data. |
| Notifications, Activity | Finance notifications and Finance activity rows (they carry amounts) are excluded from AI context, AI tools and both snapshots. |
| Daily briefing / weekly review | No Finance section, metrics, category changes or spending-pace forecast. |
| System prompt | States that Finance is unavailable; the assistant must not estimate amounts. |

Not affected: the Finance page and REST API, Search, the dashboard widget, Quick Add, What Changed
(all deterministic, no LLM). Any future AI access to Finance is a separate, explicit decision.

## Work no longer writes Finance (MRK-60)

Work sessions used to create a Finance income transaction (`sync_to_finance`, default true). With bank imports
that would double-count income, so:

- new or edited work sessions **never** create or change a Finance transaction (REST, AI, Quick Add);
- `sync_to_finance` is still accepted from older clients but ignored; new rows store `false`
  (model default `false`, no migration);
- the Work form and Quick Add no longer offer "Zapsat výdělek do Financí";
- **historical links stay**: existing `work_sessions.finance_transaction_id` values and the transactions they point to
  are not deleted, nulled or rewritten. The Work page still shows "Zapsáno ve Financích" for them;
- work earnings stay in the Work module (and its AI tools); only the Finance link is hidden from AI.

## Ledger schema (MRK-61, migration `0025_finance_ledger`)

`finance_transactions` is **evolved, not replaced** (no parallel ledger). New tables: `finance_accounts`,
`finance_imports`, `finance_import_issues`, `finance_categories`, `finance_rules`, `finance_transaction_revisions`
(`backend/modules/finance/models.py`). New columns on transactions: account/import/source, `booked_on`/`value_on`,
`amount_minor` (BIGINT, signed: minus = money out) + `currency` + `direction`, counterparty (masked/hashed account),
VS/KS/SS, `txn_key`/`fingerprint` (dedupe, MRK-62), system/override/effective category, `transfer_link_id`,
`review_flag`, `voided_at`/`void_reason`, `search_text`.

- **Money:** new logic uses `amount_minor` + `currency` only (`modules/finance/money.py`, Decimal parsing).
  A test fails if `modules/finance/` uses `float` outside the legacy bridge.
- **Legacy bridge** (`modules/finance/legacy_compat.py`): `amount` (Float) and `category` (text) stay as a mirror.
  A before-insert/update hook fills the ledger columns from legacy writes (and the mirror from ledger writes), so old
  writers and fixtures keep working. It is the only Float code; remove it with the legacy columns in a later migration.
- **Legacy rows** were moved to the built-in account „Ruční / hotovost“ (`key = manual_cash`, CZK):
  `amount_minor = round(amount × 100)` signed by type (same totals per type), `booked_on` = Prague date of
  `created_at` (migration day if missing; `created_at` itself untouched), `source = work_sync` where a work session
  links the row (links unchanged), legacy text category → built-in category as a manual override
  (`category_source = legacy`; unknown → Ostatní / Ostatní příjmy).
- **Void, not delete:** `DELETE /finance/transaction/{id}` sets `voided_at` (+ Activity delta). Voided rows stay in the
  DB (and keep work links) but are excluded from totals, lists, Search, the dashboard and goals
  (`service.active_transactions`). Imported rows cannot be voided (MRK-62/65: review flag).
- **Readers moved:** Search, dashboard, `finance_*` goals, `/finance/summary` and the legacy routes read
  `amount_minor`, `booked_on` and skip voided rows. The legacy API keeps its fields (`amount` as a positive number)
  and adds `amount_minor`, `currency`, `direction`, `booked_on`, `account_id`, `source`, `category_id`.
- **Accounts/categories service:** create, update/rename, archive (built-ins cannot be archived; categories at most two
  levels). Account numbers: only a masked suffix and a SHA-256 fingerprint for matching (low-entropy numbers – the
  fingerprint is not a secret; protection is the private DB). UI comes in MRK-65.
- **Downgrade guard:** `0025` refuses to downgrade while imports, rules, revisions, user accounts/categories, voided or
  imported rows exist.

## Import core (MRK-62)

`backend/modules/finance/importing/`: **adapter → `NormalizedRow` → validation → preview → commit**. Adapters only
parse (`rows.ImportAdapter`: `id`, `family`, `version`, `detect(head)`, `parse(stream)`); the registry picks exactly one
adapter by signature, otherwise `unknown_format` (never a guess). Production registers no adapter until MRK-63; tests
use the synthetic format in `tests/finance_fakes.py` (not a real bank format).

- **REST** (`modules/finance/router.py`): `POST /finance/imports/preview?account_id=…` (raw body, no filename,
  `text/csv`/`text/plain`/`application/octet-stream`, streamed, cap `FINANCE_IMPORT_MAX_MB`, default 20, max 200) →
  counts `new/duplicate/changed/pending_skipped/invalid/possible_duplicate`, date range, issues (row, code, field) and a
  `preview_token`; `POST /finance/imports/{token}/commit[?skip_invalid=true]`; `POST /finance/imports/{token}/cancel`;
  `GET /finance/imports` (history, counts only). Errors are `{"category": <code>}`.
- **Preview = dry run**: only the `finance_imports` row (`previewed`) is written. The same file again on the same
  account (UNIQUE account + SHA-256) → `already_imported`, 0 new rows.
- **Commit**: recomputes the plan against the current DB and writes transactions, corrections + revisions, issues, the
  import record, the `finance.import.completed` event and its Activity summary in **one transaction**. Invalid rows
  need `skip_invalid=true`. Any failure rolls everything back and marks the import `failed` separately; retry = upload
  again (the same import record is reused, no duplicates).
- **Dedupe**: bank ID → `txn_key = bank:<family>:<id>` (same fields = duplicate; different = correction with a revision,
  manual/legacy category kept); otherwise a fingerprint (account, booking day, amount, currency, counterparty account
  hash, VS/KS/SS, normalized text without digit runs ≥ 12) with the multiset rule – k equal rows in the file vs m in the
  DB → insert k−m as `fp:<fingerprint>:<ordinal>` (m+1…k); nothing is ever deleted when k < m. A new row without bank ID
  matching an active row by account + amount within ±3 days but with a different fingerprint is inserted with
  `review_flag` (possible duplicate), never merged. Pending rows are skipped and counted.
- **Categories**: a `Categorizer` hook (rules arrive in MRK-65); until then imported rows are „Nezařazeno“.
- **Raw file**: `FINANCE_IMPORT_TMP_DIR` (default: system temp / `standa-hub-finance-import`), outside `MEDIA_DIR` and
  backups, named only by import id; deleted after commit, failure, cancel or the 30-minute TTL (hourly cleanup also
  removes leftovers). Only the SHA-256 and counts remain.
- **Privacy**: responses, issues, events, Activity and logs never contain row values, account/card numbers,
  counterparty names, filenames or file contents (canary test). Stored descriptions mask digit runs ≥ 12 as „…1234“.

## Next

mBank adapter (MRK-63), import UI (MRK-64),
transactions/categories/rules (MRK-65), overview/Search/What Changed (MRK-66), real-data acceptance (MRK-68).
Real bank files are never committed, logged or put into fixtures.
