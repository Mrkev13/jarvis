"""Finance statement import core (MRK-62): adapter → NormalizedRow → validation → preview → confirm → persistence.

Bank adapters (MRK-63) only parse; dedupe, validation, categorization hook, audit and file handling live here.
Nothing in this package logs or returns row contents, account numbers, counterparty names or filenames.
"""
