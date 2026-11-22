"""Edit-learning loop: turn reviewer edits into a proposed prompt change, for a human to approve.

1. Pull edited/rejected drafts from `reviews`.
2. Label each edit with a hypothesis from a fixed taxonomy (cheap deterministic features + LLM).
3. Rank hypotheses by IMPACT (sum of edit distance, rejects weighted), not by frequency.
   Ranking by frequency hides rare but costly problems.
4. Write a proposal + a new prompt version with the learned rules appended.
5. Run the eval gate on the new version. Only if it passes, optionally open a PR (`--open-pr`).
Nothing reaches production without a human merging the PR.

Usage: python -m kompass.learn.edits [--days 14] [--min-evidence 3] [--open-pr]
"""
import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

import yaml

from kompass.db import connect, ROOT
from kompass.llm import complete_json

TAXONOMY = {
    "shorter_drafts": "Keep the whole message under 45 words.",
    "remove_question_cta": "End with a concrete offer stated plainly, not a question.",
    "more_specific_evidence": "Sentence 1 must name the specific role from the evidence and what it implies for the team.",
    "less_salesy": "Make no claims about outcomes; describe what you noticed and offer one idea.",
    "wrong_persona": None,          # not fixable by prompt alone: route to a human
    "tone_or_wording": None,        # too vague to automate: route to a human
    "factual_error": None,          # evidence problem, not a prompt problem
}
REJECT_WEIGHT = 1.0
MAX_LEARNED_RULES = 5           # stop prompts from bloating; oldest learned rules drop off first

PROMPT = """A reviewer changed an AI-written sales message. Classify the main reason.

Original: \"\"\"{before}\"\"\"
Final: \"\"\"{after}\"\"\"
Reviewer note: \"\"\"{reason}\"\"\"

Choose one: {labels}
JSON only: {{"hypothesis": "...", "detail": "one sentence"}}"""


def features(before: str, after: str | None) -> dict:
    after = after or ""
    return {"len_ratio": round(len(after) / max(len(before), 1), 2),
            "removed_question": "?" in before and "?" not in after,
            "sentences_before": len(re.findall(r"[.!?](\s|$)", before)),
            "sentences_after": len(re.findall(r"[.!?](\s|$)", after))}


def label(before, after, reason) -> dict:
    f = features(before, after)
    if f["len_ratio"] < 0.7 and not reason:
        return {"hypothesis": "shorter_drafts", "detail": f"cut to {f['len_ratio']:.0%} of length"}
    out = complete_json(PROMPT.format(before=before, after=after or "(rejected)", reason=reason or "",
                                      labels=", ".join(TAXONOMY)),
                        purpose="edit_hypothesis", max_tokens=150,
                        context={"before": before, "after": after or "", "reason": reason})
    if out.get("hypothesis") not in TAXONOMY:
        out = {"hypothesis": "tone_or_wording", "detail": f"off-list: {out.get('hypothesis')}"}
    return out


def collect(days: int = 14, version: str | None = None) -> list[dict]:
    since = datetime.now() - timedelta(days=days)
    con = connect(read_only=True)
    sql = """SELECT r.draft_id, d.prompt_version, d.body, r.final_body, r.decision, r.reason, r.edit_distance
             FROM reviews r JOIN drafts d USING (draft_id)
             WHERE r.decision IN ('edit', 'reject') AND r.reviewed_at >= ?"""
    params = [since]
    if version:
        sql += " AND d.prompt_version = ?"
        params.append(version)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(zip(["draft_id", "version", "before", "after", "decision", "reason", "dist"], r)) for r in rows]


def rank(edits: list[dict]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "impact": 0.0, "evidence": []})
    for e in edits:
        h = label(e["before"], e["after"], e["reason"])
        g = groups[h["hypothesis"]]
        g["count"] += 1
        g["impact"] += REJECT_WEIGHT if e["decision"] == "reject" else (e["dist"] or 0)
        g["evidence"].append({"draft_id": e["draft_id"], "decision": e["decision"], "detail": h["detail"],
                              "before": e["before"][:160], "after": (e["after"] or "")[:160]})
    ranked = [{"hypothesis": k, **v, "impact": round(v["impact"], 3), "rule": TAXONOMY[k]}
              for k, v in groups.items()]
    return sorted(ranked, key=lambda g: -g["impact"])


def next_version(name: str = "draft") -> str:
    nums = [int(p.stem[1:]) for p in (ROOT / "prompts" / name).glob("v*.md") if p.stem[1:].isdigit()]
    return f"v{max(nums) + 1}"


def propose(days=14, min_evidence=3, base_version=None) -> dict:
    reg = yaml.safe_load((ROOT / "prompts" / "registry.yaml").read_text())
    base = base_version or reg["draft"]["production"]
    ranked = rank(collect(days, base))
    actionable = [g for g in ranked if g["rule"] and g["count"] >= min_evidence]
    human_only = [g for g in ranked if not g["rule"]]
    if not actionable:
        return {"base": base, "ranked": ranked, "proposal": None,
                "note": f"no automatable hypothesis with >= {min_evidence} pieces of evidence"}
    base_text = (ROOT / "prompts" / "draft" / f"{base}.md").read_text()
    actionable = [g for g in actionable if g["rule"] not in base_text]        # don't re-add known rules
    if not actionable:
        return {"base": base, "ranked": ranked, "proposal": None, "note": "all learned rules already in prompt"}
    new_v = next_version()
    m = re.search(r"## Learned from reviewer edits\n(.*?)\n\n## Output", base_text, re.S)
    existing = m.group(1).splitlines() if m else []
    new_lines = [f"- {g['rule']}  <!-- learned: {g['hypothesis']}, impact {g['impact']}, n={g['count']} -->"
                 for g in actionable]
    kept = (existing + new_lines)[-MAX_LEARNED_RULES:]
    section = "## Learned from reviewer edits\n" + "\n".join(kept) + "\n\n## Output"
    new_text = (base_text.replace(m.group(0), section) if m else base_text.replace("## Output", section))
    (ROOT / "prompts" / "draft" / f"{new_v}.md").write_text(new_text)

    body = [f"# Prompt proposal: draft {base} -> {new_v}", "",
            f"Generated {datetime.now():%Y-%m-%d %H:%M} from {sum(g['count'] for g in ranked)} edited/rejected drafts "
            f"in the last {days} days. Ranked by impact (edit distance; reject = {REJECT_WEIGHT}).", "",
            "| hypothesis | impact | count | proposed rule |", "|---|---|---|---|"]
    body += [f"| {g['hypothesis']} | {g['impact']} | {g['count']} | {g['rule'] or 'needs a human'} |" for g in ranked]
    body += ["", "## Evidence"]
    for g in actionable:
        body.append(f"### {g['hypothesis']}")
        body += [f"- `{e['draft_id']}` ({e['decision']}): {e['detail']}\n  - before: {e['before']}\n"
                 f"  - after: {e['after']}" for e in g["evidence"][:5]]
    if human_only:
        body += ["", "## Needs a human (not automated)"] + \
                [f"- {g['hypothesis']}: {g['count']} cases" for g in human_only]
    body += ["", "## Before merging", f"- [ ] `python eval/run_eval.py --versions {base} {new_v}` passes the gate",
             f"- [ ] Start as A/B: set `experiment: {new_v}`, `experiment_share: 0.5` in prompts/registry.yaml"]
    prop_path = ROOT / "prompts" / "proposals" / f"draft-{new_v}.md"
    prop_path.parent.mkdir(exist_ok=True)
    prop_path.write_text("\n".join(body))
    return {"base": base, "new_version": new_v, "ranked": ranked, "proposal": str(prop_path)}


def gate_new_version(base: str, new_v: str) -> bool:
    import sys
    sys.path.insert(0, str(ROOT / "eval"))
    from gate import compare
    from run_eval import run
    rep = run([base, new_v], [None])
    s = {r["version"]: r["summary"] for r in rep["runs"]}
    rules = yaml.safe_load((ROOT / "eval" / "gate.yaml").read_text())
    fails = compare(s[new_v], s[base], rules)
    for f in fails:
        print("  gate:", f)
    return not fails


def open_pr(new_v: str, proposal: str) -> None:
    branch = f"prompt/draft-{new_v}"
    cmds = [["git", "checkout", "-b", branch],
            ["git", "add", f"prompts/draft/{new_v}.md", proposal],
            ["git", "commit", "-m", f"Propose draft prompt {new_v} from reviewer edits"],
            ["git", "push", "-u", "origin", branch],
            ["gh", "pr", "create", "--title", f"Prompt proposal: draft {new_v}", "--body-file", proposal]]
    for c in cmds:
        subprocess.run(c, check=True, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-evidence", type=int, default=3)
    ap.add_argument("--open-pr", action="store_true")
    args = ap.parse_args()
    res = propose(args.days, args.min_evidence)
    print(json.dumps({k: v for k, v in res.items() if k != "ranked"}, indent=2))
    for g in res["ranked"]:
        print(f"  {g['hypothesis']:24} impact={g['impact']:<6} n={g['count']}")
    if res.get("new_version"):
        ok = gate_new_version(res["base"], res["new_version"])
        print("eval gate:", "PASSED" if ok else "FAILED (proposal kept for review, no PR opened)")
        if ok and args.open_pr:
            open_pr(res["new_version"], res["proposal"])


if __name__ == "__main__":
    main()
