"""Provider switching (free mode), privacy guard, retries, and the stateless free-host start-up."""
import json

import httpx
import pytest

from kompass import llm, ingest, score
from kompass.db import connect


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._p, self.headers = status, payload or {}, headers or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def ok(content, pt=10, ct=5):
    return FakeResp(200, {"choices": [{"message": {"content": content}}],
                          "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


@pytest.fixture
def live_groq(monkeypatch):
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("KOMPASS_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def install(responses):
        it = iter(responses)

        def fake_post(url, **kw):
            calls.append({"url": url, **kw})
            return next(it)
        monkeypatch.setattr(httpx, "post", fake_post)
        return calls
    return install


def test_free_mode_is_the_default_provider():
    assert llm.LLM["provider"] == "groq"
    assert llm.provider()["kind"] == "openai_compatible"


def test_groq_request_shape_and_json_parsing(live_groq):
    calls = live_groq([ok('Sure: {"segment": "cobots_and_arms", "confidence": "high"}')])
    out = llm.complete_json("classify", purpose="segment_classify")
    assert out["segment"] == "cobots_and_arms"
    c = calls[0]
    assert c["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert c["headers"]["Authorization"] == "Bearer test-key"
    assert c["json"]["model"] == "openai/gpt-oss-120b" and c["json"]["max_tokens"] >= 2048
    assert c["json"]["reasoning_effort"] == "low"
    row = connect(read_only=True).execute("SELECT model, input_tokens, ok FROM llm_calls").fetchone()
    assert row == ("groq:openai/gpt-oss-120b", 10, True)


def test_rejected_optional_param_is_dropped(live_groq):
    calls = live_groq([FakeResp(400), ok('{"a": 1}')])
    assert llm.complete_json("x", purpose="segment_classify") == {"a": 1}
    assert "reasoning_effort" in calls[0]["json"] and "reasoning_effort" not in calls[1]["json"]


def test_rate_limit_is_retried(live_groq):
    calls = live_groq([FakeResp(429, headers={"retry-after": "2"}), ok('{"a": 2}')])
    assert llm.complete_json("x", purpose="segment_classify") == {"a": 2}
    assert len(calls) == 2


def test_missing_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("KOMPASS_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        llm.complete_json("x", purpose="segment_classify", retries=0)


def test_personal_data_never_goes_to_a_training_free_tier(monkeypatch):
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("KOMPASS_PROVIDER", "gemini")
    with pytest.raises(llm.PrivacyError):
        llm.complete_json("lead message", purpose="inbound_need")


def test_inbound_falls_back_to_human_when_provider_is_unsafe(fixture_accounts_csv, monkeypatch):
    from kompass.inbound import qualify
    ingest.ingest([str(fixture_accounts_csv)])
    score.main()
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("KOMPASS_PROVIDER", "gemini")
    out = qualify.process_lead({"name": "A", "email": "a@testbot.example", "message": "can we talk about a pilot?",
                                "consent": True})
    assert out["route"] == "human_review" and "personal data" in out["need"]["summary"]


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("KOMPASS_PROVIDER", "nope")
    with pytest.raises(KeyError):
        llm.provider()


def test_export_and_reload_without_llm(fixture_accounts_csv, tmp_path, monkeypatch):
    from kompass import export_accounts
    ingest.ingest([str(fixture_accounts_csv)])
    con = connect()
    con.execute("UPDATE accounts SET segment='cobots_and_arms', segment_confidence='high', "
                "sells_b2b_industrial=true WHERE domain='testbot.example'")
    con.close()
    out = tmp_path / "public.csv"
    assert export_accounts.export(out) == 4
    # fresh database, as on a free host after a restart
    monkeypatch.setenv("KOMPASS_DB", str(tmp_path / "fresh.duckdb"))
    ingest.ingest([str(out)])
    score.main()
    row = connect(read_only=True).execute(
        "SELECT a.segment, s.tier FROM accounts a JOIN account_scores s USING (account_id) "
        "WHERE domain='testbot.example'").fetchone()
    assert row == ("cobots_and_arms", "A")


def test_healthz():
    from fastapi.testclient import TestClient
    from kompass.inbound.app import app
    assert TestClient(app).get("/healthz").json() == {"ok": True}
