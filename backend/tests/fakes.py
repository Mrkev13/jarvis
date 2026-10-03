"""Sdílené test doubles (Roadmap 3.5) – testy je importují odsud, ne z jiných testovacích modulů.

- FakeGroq: lokální HTTP fake Groq (httpx.MockTransport) za skutečným OpenAI SDK – žádná síť, žádný reálný Groq.
- completion / groq_error: tvar odpovědí OpenAI-kompatibilního API.
- FakeProvider: doručovací kanál (Phase E) s předem danými výsledky.
"""
import json


def completion(content, finish="stop", refusal=None, reasoning=150):
    return {
        "id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": "openai/gpt-oss-120b",
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content, "refusal": refusal}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 400, "total_tokens": 1300,
                  "completion_tokens_details": {"reasoning_tokens": reasoning}},
    }


def groq_error(status, message, code=None):
    return status, {"error": {"message": message, "type": "invalid_request_error", "code": code}}


class FakeGroq:
    """Odpovědi (status, body) v pořadí; po vyčerpání `default_response()` (podtřídy ji mohou přepsat)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def default_response(self):
        raise AssertionError("FakeGroq: žádná další připravená odpověď")

    def handler(self, request):
        import httpx

        self.requests.append(json.loads(request.content))
        status, body = self.responses.pop(0) if self.responses else self.default_response()
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers={"content-type": "text/plain"})
        return httpx.Response(status, json=body)

    def client(self):
        import httpx
        from openai import OpenAI

        return OpenAI(api_key="test", base_url="http://groq.fake/openai/v1", max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(self.handler)))


class FakeProvider:
    """Kanál s předem danými výsledky. targets = [(id, od kdy)]."""

    def __init__(self, channel="fake", targets=((1, None),), results=None):
        self.channel = channel
        self._targets = list(targets)
        self.results = list(results or [])
        self.calls = []

    def is_configured(self):
        return True

    def targets(self, db):
        return list(self._targets)

    def send(self, db, target_id, message, dedupe_key):
        import delivery_service as ds

        self.calls.append((target_id, message, dedupe_key))
        outcome = self.results.pop(0) if self.results else ds.DeliveryResult(True, message_id="m1")
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(target_id)
        return outcome
