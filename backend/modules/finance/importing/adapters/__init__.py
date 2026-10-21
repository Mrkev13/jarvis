"""Production statement adapters (MRK-63+)."""
from modules.finance.importing.adapters.mbank_gpc import MbankGpcAdapter
from modules.finance.importing.rows import REGISTRY

PRODUCTION_ADAPTERS = (MbankGpcAdapter,)


def register_production_adapters() -> None:
    """Zaregistruje produkční adaptéry v `rows.REGISTRY` (idempotentní; volá finance_integrations při startu)."""
    for adapter in PRODUCTION_ADAPTERS:
        REGISTRY.register(adapter())
