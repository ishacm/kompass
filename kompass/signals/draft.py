"""Cited first-touch drafts + a guard that blocks anything a human shouldn't even have to see.

Guard checks (all must pass, otherwise the draft is stored as 'blocked' with reasons):
- every why_now claim cites a source id that exists
- every [S#] in the body exists; body cites at least one source
- sentence count within limits; no banned phrases
- no numbers in the body that don't appear in the cited evidence (stops invented metrics)
"""
import hashlib
import json
import re

import yaml

from kompass.db import connect, ROOT
from kompass.llm import complete_json, default_model
from kompass.signals.text import clean_title, short_name

CFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["drafts"]
POSITIONING = (ROOT / "context" / "positioning.yaml").read_text()


def registry() -> dict:
    return yaml.safe_load((ROOT / "prompts" / "registry.yaml").read_text())


def load_prompt(name: str, version: str) -> str:
    return (ROOT / "prompts" / name / f"{version}.md").read_text()


def assign_variant(account_id: str, reg: dict) -> tuple[str, str]:
    """Deterministic A/B split: same account always gets the same arm."""
    cfg = reg["draft"]
    if cfg.get("experiment") and cfg.get("experiment_share", 0) > 0:
        bucket = int(hashlib.sha1(account_id.encode()).hexdigest(), 16) % 1000 / 1000
        if bucket < cfg["experiment_share"]:
            return "experiment", cfg["experiment"]
    return "production", cfg["production"]


def build_sources(signals: list[dict]) -> dict:
    return {f"S{i + 1}": s for i, s in enumerate(signals[:5])}


def _sentences(text: str) -> list[str]:
    clean = re.sub(r"\[S\d+\]", "", text)
    return [s for s in re.split(r"(?<=[.!?])\s+", clean.strip()) if len(s.strip()) > 2]


def guard(out: dict, sources: dict) -> list[str]:
    issues = []
    body = out.get("body") or ""
    if not body.strip():
        return ["empty body"]
    for c in out.get("why_now", []):
        if c.get("source_id") not in sources:
            issues.append(f"why_now claim without valid source: {c.get('claim', '')[:60]}")
    cited = set(re.findall(r"\[(S\d+)\]", body))
    if not cited:
        issues.append("body cites no source")
    for sid in cited - set(sources):
        issues.append(f"body cites unknown source {sid}")
    n = len(_sentences(body))
    if not CFG["min_sentences"] <= n <= CFG["max_sentences"]:
        issues.append(f"{n} sentences (allowed {CFG['min_sentences']}-{CFG['max_sentences']})")
    low = body.lower()
    for p in CFG["banned_phrases"]:
        if p in low:
            issues.append(f"banned phrase: '{p}'")
    evidence = " ".join(f"{s['title']} {s.get('evidence_text', '')}" for s in sources.values())
    for num in re.findall(r"\b\d[\d.,%]*\b", re.sub(r"\[S\d+\]", "", body)):
        if num not in evidence and num not in {"15", "30"}:      # meeting lengths are allowed
            issues.append(f"number not in evidence: {num}")
    return issues


FULLCFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())


def play_context(acc: dict) -> dict:
    """Recipient persona and channel recommendation for the reviewer."""
    top = acc["signals"][0]["signal_type"] if acc["signals"] else None
    persona = FULLCFG["personas_by_signal"].get(top, "founder_ceo")
    pol = FULLCFG["channel_policy"].get(acc.get("country") or "", FULLCFG["channel_policy"]["default"])
    return {"persona": persona, "channel": pol["first_touch"], "channel_note": pol["note"]}


def make_draft(acc: dict, *, prompt_name: str = "draft", version: str | None = None,
               variant: str | None = None, model: str | None = None) -> dict:
    reg = registry()
    if version is None:
        variant, version = assign_variant(acc["account_id"], reg)
    acc = {**acc, "name": short_name(acc["name"]),
           "signals": [{**s, "title": clean_title(s["title"])} for s in acc["signals"]]}
    sources = build_sources(acc["signals"])
    sources_block = "\n".join(f"[{sid}] {s['signal_type']}: \"{s['title']}\" — {s['url']}"
                              + (f"\n     excerpt: {s['evidence_text'][:300]}" if s.get("evidence_text") else "")
                              for sid, s in sources.items())
    play = play_context(acc)
    prompt = load_prompt(prompt_name, version).format(
        account_name=acc["name"], domain=acc["domain"], tier=acc.get("tier", "?"),
        persona=play["persona"],
        sources_block=sources_block, strategy=POSITIONING,
        min_sentences=CFG["min_sentences"], max_sentences=CFG["max_sentences"],
        banned=", ".join(CFG["banned_phrases"]))
    out = complete_json(prompt, purpose="draft", model=model, max_tokens=600,
                        context={"account_name": acc["name"], "signals": list(sources.values()),
                                 "prompt_version": version})
    issues = guard(out, sources)
    draft = {
        "draft_id": hashlib.sha1(f"{acc['account_id']}:{version}:{out.get('body')}".encode()).hexdigest()[:12],
        "account_id": acc["account_id"], "prompt_name": prompt_name, "prompt_version": version,
        "variant": variant or "manual", "model": model or default_model(),
        "why_now": out.get("why_now", []), "body": out.get("body", ""),
        "sources": {k: v["url"] for k, v in sources.items()},
        "guard_ok": not issues, "guard_issues": issues,
        "status": "pending" if not issues else "blocked",
        "play": play,
    }
    return draft


def save_draft(d: dict) -> None:
    con = connect()
    con.execute("""INSERT OR REPLACE INTO drafts (draft_id, account_id, prompt_name, prompt_version, variant,
                     model, why_now, body, sources, guard_ok, guard_issues, status, play)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [d["draft_id"], d["account_id"], d["prompt_name"], d["prompt_version"], d["variant"],
                 d["model"], json.dumps(d["why_now"]), d["body"], json.dumps(d["sources"]),
                 d["guard_ok"], json.dumps(d["guard_issues"]), d["status"], json.dumps(d.get("play", {}))])
    con.close()
