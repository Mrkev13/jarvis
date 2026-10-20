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

## Next

Schema modernization (MRK-61), import core (MRK-62), mBank adapter (MRK-63), import UI (MRK-64),
transactions/categories/rules (MRK-65), overview/Search/What Changed (MRK-66), real-data acceptance (MRK-68).
Real bank files are never committed, logged or put into fixtures.
