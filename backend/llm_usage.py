"""Bezpečné logování využití LLM: jen čísla (tokeny, latence, kola, rate-limit, retry).

NIKDY nelogovat obsah promptu, zprávy uživatele, argumenty toolů, odpovědi ani klíče.
Logger „standa_hub.llm" má vlastní handler, aby byl vidět i pod uvicornem (root logger je WARNING).
"""
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("standa_hub.llm")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s [llm] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_DEFAULT_RETRY_WAIT = 2.5
_TRY_AGAIN_RE = re.compile(r"try again in ([0-9.]+)(ms|s)", re.I)
# Groq 429 text: "... on tokens per minute (TPM): Limit 8000 ..." → jen druh limitu (žádný obsah).
_LIMIT_KIND_RE = re.compile(r"\((TPM|TPD|RPM|RPD|ASH|ASD)\)")


@dataclass(frozen=True)
class LLMCallRecord:
    attempt: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    ratelimit_remaining_tokens: str | None = None
    tool_calls: int = 0
    rate_limited: bool = False
    error_status: int | None = None
    limit_kind: str | None = None  # TPM / TPD / RPM / RPD z Groq 429 zprávy


def rate_limit_kind(exc: Exception) -> str | None:
    """Druh vyčerpaného limitu z Groq 429 (TPM vs TPD apod.) – rozhoduje, zda má smysl čekat."""
    m = _LIMIT_KIND_RE.search(str(exc))
    return m.group(1) if m else None


def ratelimit_remaining_tokens(headers) -> str | None:
    if headers is None:
        return None
    return headers.get("x-ratelimit-remaining-tokens")


def retry_wait_seconds(exc: Exception, max_wait: float) -> float:
    """Čekání po 429: hlavička retry-after → text „try again in Xms/Xs" → default. Omezeno max_wait."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    wait = None
    if headers is not None and headers.get("retry-after"):
        try:
            wait = float(headers.get("retry-after"))
        except ValueError:
            wait = None
    if wait is None:
        m = _TRY_AGAIN_RE.search(str(exc))
        if m:
            wait = float(m.group(1)) / (1000.0 if m.group(2).lower() == "ms" else 1.0)
    if wait is None:
        wait = _DEFAULT_RETRY_WAIT
    return max(0.0, min(float(max_wait), wait + 0.3))


def log_call(record: LLMCallRecord, enabled: bool = True) -> None:
    if not enabled:
        return
    if record.rate_limited:
        logger.warning(
            "call attempt=%s 429 rate_limited limit=%s latency_ms=%s rl_remaining_tokens=%s",
            record.attempt, record.limit_kind or "?", record.latency_ms, record.ratelimit_remaining_tokens,
        )
    elif record.error_status is not None:
        logger.warning("call attempt=%s api_error status=%s latency_ms=%s", record.attempt, record.error_status, record.latency_ms)
    else:
        logger.info(
            "call attempt=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s latency_ms=%s "
            "tool_calls=%s rl_remaining_tokens=%s",
            record.attempt, record.prompt_tokens, record.completion_tokens, record.total_tokens,
            record.latency_ms, record.tool_calls, record.ratelimit_remaining_tokens,
        )


def log_history(result, enabled: bool = True) -> None:
    """Souhrn přípravy historie (A4) – jen počty, nikdy obsah zpráv ani shrnutí."""
    if enabled:
        logger.info(
            "history messages=%s window=%s history_tokens=%s summary_used=%s summary_called=%s "
            "summary_failed=%s dropped_messages=%s",
            len(result.messages), result.window_messages, result.history_tokens, result.summary_used,
            result.summary_called, result.summary_failed, result.dropped_messages,
        )


def log_retry(attempt: int, max_attempts: int, wait_s: float, reason: str, enabled: bool = True) -> None:
    if enabled:
        logger.warning("retry after %s attempt=%s/%s wait_s=%.1f", reason, attempt, max_attempts, wait_s)


def log_request_summary(
    records: list[LLMCallRecord],
    tool_rounds: int,
    latency_ms: int,
    *,
    planner_actions_removed: int = 0,
    planner_nudged: bool = False,
    planner_memories_autoloaded: bool = False,
    context_tokens: int = 0,
    context_sections: int = 0,
    tools_exposed: int = 0,
    tool_schema_tokens: int = 0,
    tool_route: str = "",
    route_widened: bool = False,
    enabled: bool = True,
) -> None:
    if not enabled:
        return
    ok = [r for r in records if not r.rate_limited and r.error_status is None]
    logger.info(
        "request calls=%s tool_rounds=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s latency_ms=%s "
        "rate_limited=%s api_errors=%s context_tokens=%s context_sections=%s "
        "planner_memories_autoloaded=%s planner_nudged=%s planner_actions_removed=%s "
        "tools_exposed=%s tool_schema_tokens=%s tool_route=%s route_widened=%s",
        len(records), tool_rounds,
        sum(r.prompt_tokens or 0 for r in ok), sum(r.completion_tokens or 0 for r in ok),
        sum(r.total_tokens or 0 for r in ok), latency_ms,
        sum(1 for r in records if r.rate_limited), sum(1 for r in records if r.error_status is not None),
        context_tokens, context_sections,
        planner_memories_autoloaded, planner_nudged, planner_actions_removed,
        tools_exposed, tool_schema_tokens, tool_route or "-", route_widened,
    )
