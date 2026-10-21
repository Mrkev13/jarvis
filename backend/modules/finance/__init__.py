"""Finance v1 ledger (MRK-61): accounts, imports, categories, rules and the evolved `finance_transactions`.

The legacy `FinanceTransaction` model stays in `models.py` (many readers import it); its new columns are declared
there. New business logic uses `amount_minor` (signed integer, minus = money out) + `currency`, never Float.
Finance never reaches an LLM (MRK-60, `finance_ai_policy.py`).
"""
