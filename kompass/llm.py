"""One LLM client for every module.

Modes (env KOMPASS_LLM):
  live  - Anthropic API (ANTHROPIC_API_KEY, model KOMPASS_MODEL)
  mock  - deterministic local handlers in kompass/mock_llm.py, for tests, CI and demos.
          Mock output is NEVER a source of published metrics.

Every call is logged to the llm_calls table (purpose, model, tokens, latency) so
cost-per-account and cost-per-draft can be reported from real runs.
"""
import json
import os
import re
import time

import yaml

from kompass.db import connect, ROOT

CONFIG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())


def mode() -> str:
    return os.environ.get("KOMPASS_LLM", "live")


def default_model() -> str:
    return os.environ.get("KOMPASS_MODEL", CONFIG["default_model"])


def _parse_json(text: str) -> dict:
    text = text.strip()
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


def complete_json(prompt: str, purpose: str, *, model: str | None = None,
                  max_tokens: int = 800, retries: int = 2, context: dict | None = None) -> dict:
    """Return a parsed JSON object. Retries on malformed JSON or transient API errors."""
    model = model or default_model()
    if mode() == "mock":
        from kompass.mock_llm import handle
        t0 = time.time()
        out = handle(purpose, prompt, context or {})
        _log(purpose, "mock", 0, 0, int((time.time() - t0) * 1000), True)
        return out

    import anthropic
    client = anthropic.Anthropic()
    last_err = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            msg = client.messages.create(model=model, max_tokens=max_tokens,
                                         messages=[{"role": "user", "content": prompt}])
            out = _parse_json(msg.content[0].text)
            _log(purpose, model, msg.usage.input_tokens, msg.usage.output_tokens,
                 int((time.time() - t0) * 1000), True)
            return out
        except Exception as e:  # malformed JSON, rate limit, timeout
            last_err = e
            _log(purpose, model, 0, 0, int((time.time() - t0) * 1000), False)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {retries + 1} attempts ({purpose}): {last_err}")


def complete_text(prompt: str, purpose: str, *, provider: dict | None = None, system: str | None = None,
                  max_tokens: int = 700, context: dict | None = None, with_citations: bool = False):
    """Free-text completion (used by the AEO radar). provider = one entry of config aeo.providers.
    with_citations=True returns (text, [urls]) using the provider's citation field when it has one."""
    provider = provider or {"id": "claude", "kind": "anthropic", "model": default_model()}
    model = provider.get("model") or default_model()
    t0 = time.time()
    if mode() == "mock":
        from kompass.mock_llm import handle
        res = handle(purpose, prompt, context or {})
        _log(purpose, f"mock:{provider['id']}", 0, 0, int((time.time() - t0) * 1000), True)
        return (res["answer"], res.get("citations", [])) if with_citations else res["answer"]
    try:
        if provider["kind"] == "anthropic":
            import anthropic
            kw = {"system": system} if system else {}
            msg = anthropic.Anthropic().messages.create(model=model, max_tokens=max_tokens,
                                                        messages=[{"role": "user", "content": prompt}], **kw)
            text, tin, tout = msg.content[0].text, msg.usage.input_tokens, msg.usage.output_tokens
            cites = []
        else:  # any OpenAI-compatible chat completions endpoint (OpenAI, Gemini, Perplexity, ...)
            import httpx
            key = os.environ[provider["key_env"]]
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            r = httpx.post(f"{provider['base_url'].rstrip('/')}/chat/completions", timeout=60,
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": model, "messages": msgs, "max_tokens": max_tokens})
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            cites = list(data.get("citations") or []) + \
                [r.get("url") for r in (data.get("search_results") or []) if isinstance(r, dict) and r.get("url")]
            tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        _log(purpose, f"{provider['id']}:{model}", tin, tout, int((time.time() - t0) * 1000), True)
        return (text, cites) if with_citations else text
    except Exception:
        _log(purpose, f"{provider['id']}:{model}", 0, 0, int((time.time() - t0) * 1000), False)
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
