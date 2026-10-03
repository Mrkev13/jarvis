"""Okno historie konverzace + průběžné shrnutí starších zpráv (Roadmap 3.0 A4).

Do LLM requestu jde: [shrnutí starší historie] + [starší, zatím neshrnuté zprávy pod prahem] + [posledních
N zpráv doslovně]. Když neshrnuté starší zprávy přesáhnou práh, shrnou se JEDNÍM voláním (dávka omezená
na SUMMARY_INPUT_FACTOR × práh) a `summarized_until_message_id` se posune – stejné zprávy se už neshrnují.
Selhání shrnutí request neshodí: starší neshrnuté zprávy se pro tento turn vynechají (truncation).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from llm_budget import estimate_tokens
from llm_config import LLMSettings
from models import Conversation, Message

SUMMARY_HEADER = "CONVERSATION SUMMARY (earlier messages of this chat; context only, never a source of current data)"
SUMMARY_INPUT_FACTOR = 3  # max vstup jednoho shrnutí = 3 × AI_SUMMARY_TRIGGER_TOKENS
MESSAGE_OVERHEAD_TOKENS = 4  # role + oddělovače v chat šabloně
CHAT_ROLES = ("user", "assistant")

Summarizer = Callable[[str | None, list[dict]], str]


@dataclass(frozen=True)
class HistoryResult:
    messages: list[dict]  # pro ask_ai: [shrnutí jako system zpráva] + historie
    history_tokens: int
    window_messages: int
    summary_used: bool = False
    summary_called: bool = False
    summary_failed: bool = False
    dropped_messages: int = 0


def message_tokens(messages: list[dict]) -> int:
    return sum(estimate_tokens(str(m.get("content") or "")) + MESSAGE_OVERHEAD_TOKENS for m in messages)


def clip_to_tokens(text: str, max_tokens: int) -> str:
    """Zkrátí text pod odhad max_tokens (shrnutí od modelu nesmí rozbít rozpočet)."""
    text = (text or "").strip()
    while text and estimate_tokens(text) > max_tokens:
        text = text[: int(len(text) * 0.9)].rstrip()
    return text


def _summary_message(summary: str) -> dict:
    return {"role": "system", "content": f"{SUMMARY_HEADER}\n{summary}"}


def _assemble(summary: str | None, history: list[dict], max_history_tokens: int) -> tuple[list[dict], int]:
    """Složí výstup a vynutí tvrdé maximum: odebírá nejstarší zprávy, poslední zprávu nikdy."""
    history = list(history)
    dropped = 0
    head = [_summary_message(summary)] if summary else []
    while len(history) > 1 and message_tokens(head + history) > max_history_tokens:
        history = history[1:]
        dropped += 1
    return head + history, dropped


def window_client_messages(messages: list[dict], settings: LLMSettings) -> HistoryResult:
    """Historie poslaná klientem (bez conversation_id) – nelze ukládat shrnutí, jen okno + tvrdé maximum."""
    chat = [m for m in messages if m.get("role") in CHAT_ROLES]
    window = chat[-settings.history_window_messages:]
    out, dropped_by_cap = _assemble(None, window, settings.max_history_tokens)
    return HistoryResult(
        messages=out,
        history_tokens=message_tokens(out),
        window_messages=len(out),
        dropped_messages=len(chat) - len(window) + dropped_by_cap,
    )


def _summary_batch(pending: list[Message], max_input_tokens: int) -> list[Message]:
    batch: list[Message] = []
    total = 0
    for m in pending:
        cost = estimate_tokens(m.content or "") + MESSAGE_OVERHEAD_TOKENS
        if batch and total + cost > max_input_tokens:
            break
        batch.append(m)
        total += cost
    return batch


def prepare_conversation_history(
    db: Session,
    conversation: Conversation,
    db_messages: list[Message],
    settings: LLMSettings,
    summarize: Summarizer,
) -> HistoryResult:
    chat = [m for m in db_messages if m.role in CHAT_ROLES]
    window_size = settings.history_window_messages
    window = chat[-window_size:]
    older = chat[:-window_size] if len(chat) > window_size else []
    until = conversation.summarized_until_message_id or 0
    pending = [m for m in older if m.id > until]
    summary = conversation.summary
    to_dicts = lambda msgs: [{"role": m.role, "content": m.content} for m in msgs]  # noqa: E731

    called = failed = False
    dropped = 0
    if message_tokens(to_dicts(pending)) > settings.summary_trigger_tokens:
        batch = _summary_batch(pending, settings.summary_trigger_tokens * SUMMARY_INPUT_FACTOR)
        called = True
        try:
            new_summary = clip_to_tokens(summarize(summary, to_dicts(batch)), settings.max_summary_tokens)
            if not new_summary:
                raise ValueError("prázdné shrnutí")
            conversation.summary = new_summary
            conversation.summarized_until_message_id = batch[-1].id
            db.commit()
            summary = new_summary
            pending = pending[len(batch):]
        except Exception:  # noqa: BLE001 - shrnutí je optimalizace; request musí projít
            db.rollback()
            failed = True
        # Při selhání (nebo zbytku nad práh u velkého dohánění) se starší neshrnuté zprávy tento turn
        # neposílají; další turn je shrne inkrementálně.
        if failed or message_tokens(to_dicts(pending)) > settings.summary_trigger_tokens:
            dropped = len(pending)
            pending = []

    out, dropped_by_cap = _assemble(summary, to_dicts(pending) + to_dicts(window), settings.max_history_tokens)
    return HistoryResult(
        messages=out,
        history_tokens=message_tokens(out),
        window_messages=len(window),
        summary_used=bool(summary),
        summary_called=called,
        summary_failed=failed,
        dropped_messages=dropped + dropped_by_cap,
    )
