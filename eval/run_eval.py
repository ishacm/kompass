"""Run the golden set against one or more prompt versions and models.

Usage:
  python eval/run_eval.py --versions v1 v2 --models claude-sonnet-5-5 [--judge] [--out eval/reports/x.json]
Prints a comparison table. With KOMPASS_LLM=mock it tests the harness only (no publishable numbers).
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kompass.llm import complete_json, default_model, mode  # noqa: E402
from kompass.signals.draft import make_draft, build_sources  # noqa: E402

UNSUPPORTED_KEYS = ("without valid source", "unknown source", "number not in evidence", "cites no source")


def load_golden(path: Path | None = None) -> list[dict]:
    return yaml.safe_load((path or ROOT / "eval" / "golden" / "golden.yaml").read_text())["cases"]


def judge(d: dict, case: dict, judge_version: str = "v1", judge_model: str | None = None) -> dict | None:
    if mode() == "mock":
        return None
    tmpl = (ROOT / "eval" / "judge" / f"{judge_version}.md").read_text()
    sources = build_sources(case["signals"])
    block = "\n".join(f"[{k}] {v['title']} — {v.get('evidence_text', '')}" for k, v in sources.items())
    return complete_json(tmpl.format(persona=d["play"]["persona"], account_name=case["account"]["name"],
                                     sources_block=block, body=d["body"]), purpose="judge", max_tokens=400,
                         model=judge_model)


def eval_case(case: dict, version: str, model: str | None, use_judge: bool,
              judge_model: str | None = None) -> dict:
    acc = {**case["account"], "signals": [{**s, "confidence": 0.9} for s in case["signals"]]}
    t0 = time.time()
    d = make_draft(acc, version=version, variant="eval", model=model)
    latency = time.time() - t0
    body = d["body"].lower()
    mentions = case.get("must_mention", [])
    hit = sum(1 for m in mentions if m.lower() in body)
    must_not = [p for p in case.get("must_not", []) if p.lower() in body]
    unsupported = [i for i in d["guard_issues"] if i.startswith(UNSUPPORTED_KEYS)]
    words = len(re.sub(r"\[S\d+\]", "", d["body"]).split())
    res = {"case": case["id"], "synthetic": case.get("synthetic", False), "guard_ok": d["guard_ok"],
           "guard_issues": d["guard_issues"], "must_mention_hit": hit, "must_mention_total": len(mentions),
           "must_not_violations": must_not, "unsupported_claims": len(unsupported), "words": words,
           "latency_s": round(latency, 2), "body": d["body"]}
    if use_judge:
        res["judge"] = judge(d, case, judge_model=judge_model)
    return res


def summarise(results: list[dict]) -> dict:
    n = len(results)
    tot_m = sum(r["must_mention_total"] for r in results) or 1
    s = {
        "cases": n,
        "synthetic_cases": sum(r["synthetic"] for r in results),
        "guard_pass_rate": round(sum(r["guard_ok"] for r in results) / n, 3),
        "must_mention_rate": round(sum(r["must_mention_hit"] for r in results) / tot_m, 3),
        "unsupported_claim_rate": round(sum(r["unsupported_claims"] for r in results) / n, 3),
        "must_not_violations": sum(len(r["must_not_violations"]) for r in results),
        "avg_words": round(sum(r["words"] for r in results) / n, 1),
        "avg_latency_s": round(sum(r["latency_s"] for r in results) / n, 2),
    }
    judged = [r["judge"] for r in results if r.get("judge")]
    if judged:
        for k in ("specificity", "relevance", "human"):
            s[f"judge_{k}"] = round(sum(j.get(k, 0) for j in judged) / len(judged), 2)
    return s


def _tokens_since(t0: datetime) -> dict:
    from kompass.db import connect
    con = connect(read_only=True)
    row = con.execute("""SELECT count(*), coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0)
                         FROM llm_calls WHERE purpose = 'draft' AND called_at >= ?""", [t0]).fetchone()
    con.close()
    return {"draft_calls": row[0], "input_tokens": row[1], "output_tokens": row[2]}


def run(versions: list[str], models: list[str], use_judge: bool = False, golden: Path | None = None,
        judge_model: str | None = None) -> dict:
    cases = load_golden(golden)
    if use_judge and judge_model and judge_model in models:
        print("warning: judge model is also a candidate model; scores may be biased")
    report = {"run_at": datetime.now().isoformat(timespec="seconds"), "llm_mode": mode(),
              "judge_model": judge_model if use_judge else None, "runs": []}
    models = [m or default_model() for m in models]
    for v in versions:
        for m in models:
            t0 = datetime.now()
            results = [eval_case(c, v, m, use_judge, judge_model) for c in cases]
            summary = summarise(results)
            tok = _tokens_since(t0)
            summary["tokens_per_draft"] = round((tok["input_tokens"] + tok["output_tokens"]) / max(len(cases), 1))
            report["runs"].append({"version": v, "model": m, "summary": summary, "results": results})
    return report


def table(report: dict) -> str:
    cols = ["guard_pass_rate", "must_mention_rate", "unsupported_claim_rate", "must_not_violations", "avg_words",
            "tokens_per_draft"]
    lines = ["| version | model | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 2)]
    for r in report["runs"]:
        lines.append(f"| {r['version']} | {r['model']} | " + " | ".join(str(r["summary"].get(c)) for c in cols) + " |")
    note = "\n\n_Mock mode: harness test only, not model results._" if report["llm_mode"] == "mock" else ""
    syn = any(r["summary"]["synthetic_cases"] for r in report["runs"])
    note += "\n\n_Includes synthetic golden cases: do not publish._" if syn else ""
    return "\n".join(lines) + note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="+", default=["v1"])
    ap.add_argument("--models", nargs="+", default=[default_model()])
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", help="use a different model than the candidates to reduce self-grading bias")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = run(args.versions, args.models, args.judge, judge_model=args.judge_model)
    out = args.out or ROOT / "eval" / "reports" / f"{report['run_at'].replace(':', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(table(report))
    print(f"\nfull report: {out}")


if __name__ == "__main__":
    os.environ.setdefault("KOMPASS_DB", str(ROOT / "data" / "eval.duckdb"))
    main()
