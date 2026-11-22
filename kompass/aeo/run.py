"""Ask every buyer question, in DE and EN, to every configured assistant, N times. Store raw answers
and extracted vendor mentions.

Usage: python -m kompass.aeo.run [--repeats 3] [--questions q01 q02] [--providers claude openai]
Note: answers come from each provider's API, which can differ from the consumer chat apps
(no browsing, no personalisation). Reports say so.
"""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime

import yaml

from kompass.db import connect, ROOT
from kompass.llm import complete_text, mode
from kompass.signals.text import short_name

CFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["aeo"]


def load_questions(ids: list[str] | None = None) -> list[dict]:
    qs = yaml.safe_load((ROOT / "aeo" / "questions.yaml").read_text())["questions"]
    return [q for q in qs if not ids or q["id"] in ids]


def load_vendors() -> list[dict]:
    v = yaml.safe_load((ROOT / "aeo" / "vendors.yaml").read_text())
    sensitive = set(v.get("case_sensitive_aliases", []))
    vendors = [{**c, "kind": "competitor"} for c in v["competitors"]]
    con = connect(read_only=True)
    for aid, name in con.execute("SELECT account_id, name FROM accounts").fetchall():
        vendors.append({"id": aid, "name": short_name(name), "aliases": [short_name(name)], "kind": "account"})
    con.close()
    for vd in vendors:
        vd["patterns"] = [re.compile(rf"(?<![\w-]){re.escape(a)}(?![\w-])", 0 if a in sensitive else re.I)
                          for a in vd["aliases"]]
    return vendors


def extract_mentions(answer: str, vendors: list[dict]) -> list[dict]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    found = []
    for vd in vendors:
        hits = [m.start() for p in vd["patterns"] for m in p.finditer(answer)]
        if not hits:
            continue
        first = min(hits)
        sent = next((s for s in sentences if any(p.search(s) for p in vd["patterns"])), "")
        found.append({"vendor": vd["id"], "first_index": first, "sentence": sent.strip()[:400]})
    found.sort(key=lambda f: f["first_index"])
    for i, f in enumerate(found):
        f["position"] = i + 1
    return found


URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def named_in_question(question: str, vendors: list[dict]) -> set[str]:
    return {vd["id"] for vd in vendors if any(p.search(question) for p in vd["patterns"])}


def active_providers(only: list[str] | None = None) -> tuple[list[dict], list[str]]:
    use, skipped = [], []
    for p in CFG["providers"]:
        if only and p["id"] not in only:
            continue
        if mode() == "mock":
            use.append(p)
            continue
        from kompass.llm import paid_allowed
        if p.get("paid") and not paid_allowed():
            skipped.append(f"{p['id']}: paid provider (set KOMPASS_ALLOW_PAID=true to use)")
        elif p["kind"] == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            skipped.append(f"{p['id']}: no ANTHROPIC_API_KEY")
        elif p["kind"] != "anthropic" and not os.environ.get(p.get("key_env", "")):
            skipped.append(f"{p['id']}: no {p.get('key_env')}")
        elif not p.get("model"):
            skipped.append(f"{p['id']}: no model set in config.yaml")
        else:
            use.append(p)
    return use, skipped


def run(repeats: int | None = None, question_ids=None, provider_ids=None) -> dict:
    repeats = repeats or CFG["repeats"]
    run_id = datetime.now().strftime("aeo-%Y%m%d-%H%M%S")
    providers, skipped = active_providers(provider_ids)
    vendors = load_vendors()
    mock_names = [v["name"] for v in vendors]
    stats = {"run_id": run_id, "providers": [p["id"] for p in providers], "skipped": skipped,
             "answers": 0, "failed": 0, "mentions": 0}
    for q in load_questions(question_ids):
        for lang in ("de", "en"):
            for p in providers:
                for r in range(repeats):
                    excluded = named_in_question(q[lang], vendors)
                    try:
                        ans, cites = complete_text(q[lang], "aeo_answer", provider=p, system=CFG["system"],
                                                   with_citations=True,
                                                   context={"question": q[lang], "repeat_idx": r,
                                                            "mock_vendors": mock_names})
                    except Exception as e:
                        stats["failed"] += 1
                        print(f"failed {q['id']}/{lang}/{p['id']}: {e}")
                        continue
                    aid = hashlib.sha1(f"{run_id}:{q['id']}:{lang}:{p['id']}:{r}".encode()).hexdigest()[:14]
                    con = connect()
                    cites = list(dict.fromkeys([c for c in cites if c] + URL_RE.findall(ans)))
                    con.execute("INSERT INTO aeo_answers VALUES (?, ?, ?, ?, ?, ?, ?, ?, now(), ?, ?)",
                                [aid, run_id, q["id"], lang, p["id"], p.get("model") or "", r, ans,
                                 json.dumps(cites), json.dumps(sorted(excluded))])
                    for m in extract_mentions(ans, vendors):
                        if m["vendor"] in excluded:
                            continue                       # named in the question: not an earned mention
                        con.execute("INSERT INTO aeo_mentions VALUES (?, ?, ?, ?)",
                                    [aid, m["vendor"], m["position"], m["sentence"]])
                        stats["mentions"] += 1
                    con.close()
                    stats["answers"] += 1
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int)
    ap.add_argument("--questions", nargs="*")
    ap.add_argument("--providers", nargs="*")
    a = ap.parse_args()
    print(run(a.repeats, a.questions, a.providers))
