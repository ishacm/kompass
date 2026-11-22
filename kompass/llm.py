"""One LLM client for every module, with a switchable provider.

Modes (env KOMPASS_LLM):
  live  - the provider set in config.yaml -> llm.provider (override: env KOMPASS_PROVIDER)
  mock  - deterministic local handlers in kompass/mock_llm.py, for tests, CI and demos.
          Mock output is NEVER a source of published metrics.

Providers: Anthropic, or any OpenAI-compatible endpoint (Groq, Gemini, OpenAI, OpenRouter, a local
Ollama server, ...). Free mode = Groq. Model override: env KOMPASS_MODEL.

Privacy guard: purposes that carry personal data (inbound leads) are refused on providers whose
free tier uses prompts for training. The caller then falls back to a human.

Every call is logged to llm_calls (purpose, provider:model, tokens, latency) for cost reporting.
"""
import json
import os
import re
import time

import yaml

from kompass.db import connect, ROOT

CONFIG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())
LLM = CONFIG["llm"]


class PaidProviderError(RuntimeError):
    """A paid provider was selected without explicitly allowing paid usage."""


def paid_allowed() -> bool:
    return os.environ.get("KOMPASS_ALLOW_PAID", "").lower() == "true"


def check_cost(prov: dict) -> None:
    if prov.get("paid") and not paid_allowed():
        raise PaidProviderError(f"provider '{prov['id']}' costs money and KOMPASS_ALLOW_PAID is not 'true'. "
                                f"Use the free provider (groq) or set KOMPASS_ALLOW_PAID=true deliberately.")


class PrivacyError(RuntimeError):
    """A personal-data purpose was sent to a provider that may train on it."""


def mode() -> str:
    return os.environ.get("KOMPASS_LLM", "live")


def provider_id() -> str:
    return os.environ.get("KOMPASS_PROVIDER", LLM["provider"])


def provider(pid: str | None = None) -> dict:
    pid = pid or provider_id()
    if pid not in LLM["providers"]:
        raise KeyError(f"unknown LLM provider '{pid}'; options: {', '.join(LLM['providers'])}")
    return {"id": pid, **LLM["providers"][pid]}


def default_model() -> str:
    return os.environ.get("KOMPASS_MODEL") or provider().get("model") or "unset"


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    return json.loads(m.group(0))


def _log(purpose, model, tin, tout, ms, ok):
    try:
        con = connect()
        con.execute("INSERT INTO llm_calls (purpose, model, mode, input_tokens, output_tokens, latency_ms, ok) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", [purpose, model, mode(), tin, tout, ms, ok])
        con.close()
    except Exception:
        pass  # logging must never break the pipeline


def check_privacy(purpose: str, prov: dict) -> None:
    if purpose in LLM.get("personal_data_purposes", []) and prov.get("free_tier_trains_on_data"):
        raise PrivacyError(f"'{purpose}' carries personal data; provider '{prov['id']}' may train on "
                           f"free-tier prompts. Use another provider for this purpose.")


def _call(prov: dict, model: str, prompt: str, system: str | None, max_tokens: int) -> tuple[str, int, int, dict]:
    """One request. Returns (text, input_tokens, output_tokens, raw_json_or_empty)."""
    if prov["kind"] == "anthropic":
        import anthropic
        kw = {"system": system} if system else {}
        msg = anthropic.Anthropic().messages.create(model=model, max_tokens=max_tokens,
                                                    messages=[{"role": "user", "content": prompt}], **kw)
        return msg.content[0].text, msg.usage.input_tokens, msg.usage.output_tokens, {}

    import httpx
    key = os.environ.get(prov.get("key_env") or "", "")
    if prov.get("key_env") and not key:
        raise RuntimeError(f"{prov['key_env']} is not set")
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    # reasoning models spend tokens before answering, so give them room
    body = {"model": model, "messages": msgs, "max_tokens": max(max_tokens, prov.get("min_max_tokens", 0))}
    extra = prov.get("extra") or {}
    url = f"{prov['base_url'].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = httpx.post(url, timeout=90, headers=headers, json={**body, **extra})
    if r.status_code == 400 and extra:          # provider rejected an optional parameter: retry without it
        r = httpx.post(url, timeout=90, headers=headers, json=body)
    if r.status_code == 429:
        raise RateLimited(float(r.headers.get("retry-after", "5") or 5))
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    return (data["choices"][0]["message"].get("content") or "", usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0), data)


class RateLimited(RuntimeError):
    def __init__(self, wait: float):
        super().__init__(f"rate limited, retry after {wait}s")
        self.wait = min(wait, 60.0)


def complete_json(prompt: str, purpose: str, *, model: str | None = None, max_tokens: int = 800,
                  retries: int = 2, context: dict | None = None, provider_override: str | None = None) -> dict:
    """Return a parsed JSON object. Retries on malformed JSON, rate limits and transient errors."""
    if mode() == "mock":
        from kompass.mock_llm import handle
        t0 = time.time()
        out = handle(purpose, prompt, context or {})
        _log(purpose, "mock", 0, 0, int((time.time() - t0) * 1000), True)
        return out

    prov = provider(provider_override or LLM.get("purpose_providers", {}).get(purpose))
    check_cost(prov)
    check_privacy(purpose, prov)
    model = model or os.environ.get("KOMPASS_MODEL") or prov.get("model")
    if not model:
        raise RuntimeError(f"no model set for provider '{prov['id']}' in config.yaml")
    last_err = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            text, tin, tout, _ = _call(prov, model, prompt, None, max_tokens)
            out = _parse_json(text)
            _log(purpose, f"{prov['id']}:{model}", tin, tout, int((time.time() - t0) * 1000), True)
            return out
        except RateLimited as e:
            last_err = e
            _log(purpose, f"{prov['id']}:{model}", 0, 0, int((time.time() - t0) * 1000), False)
            time.sleep(e.wait)
        except Exception as e:  # malformed JSON, timeout, server error
            last_err = e
            _log(purpose, f"{prov['id']}:{model}", 0, 0, int((time.time() - t0) * 1000), False)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {retries + 1} attempts ({purpose}): {last_err}")


def complete_text(prompt: str, purpose: str, *, provider: dict | None = None, system: str | None = None,
                  max_tokens: int = 700, context: dict | None = None, with_citations: bool = False):
    """Free-text completion (used by the AEO radar). provider = one entry of config aeo.providers.
    with_citations=True returns (text, [urls]) using the provider's citation field when it has one."""
    prov = provider or {**globals()["provider"](), "id": provider_id()}
    model = prov.get("model") or default_model()
    t0 = time.time()
    if mode() == "mock":
        from kompass.mock_llm import handle
        res = handle(purpose, prompt, context or {})
        _log(purpose, f"mock:{prov['id']}", 0, 0, int((time.time() - t0) * 1000), True)
        return (res["answer"], res.get("citations", [])) if with_citations else res["answer"]
    check_cost(prov)
    try:
        text, tin, tout, data = _call(prov, model, prompt, system, max_tokens)
        cites = list(data.get("citations") or []) + \
            [x.get("url") for x in (data.get("search_results") or []) if isinstance(x, dict) and x.get("url")]
        _log(purpose, f"{prov['id']}:{model}", tin, tout, int((time.time() - t0) * 1000), True)
        return (text, cites) if with_citations else text
    except Exception:
        _log(purpose, f"{prov['id']}:{model}", 0, 0, int((time.time() - t0) * 1000), False)
        raise


def cost_summary() -> list[dict]:
    """Tokens and (if prices are configured) cost per purpose, from logged live calls."""
    prices = CONFIG.get("prices_per_million_tokens") or {}
    con = connect(read_only=True)
    rows = con.execute("""SELECT purpose, model, count(*) AS calls, sum(input_tokens) AS tin,
                                 sum(output_tokens) AS tout, avg(latency_ms) AS avg_ms
                          FROM llm_calls WHERE mode = 'live' AND ok GROUP BY 1, 2""").fetchall()
    con.close()
    out = []
    for purpose, model, calls, tin, tout, avg_ms in rows:
        p = prices.get(model) or {}
        cost = None
        if p.get("input") is not None and p.get("output") is not None:
            cost = (tin * p["input"] + tout * p["output"]) / 1e6
        out.append({"purpose": purpose, "model": model, "calls": calls, "input_tokens": tin,
                    "output_tokens": tout, "avg_latency_ms": round(avg_ms or 0),
                    "cost": cost, "cost_per_call": (cost / calls) if cost is not None else None})
    return out
