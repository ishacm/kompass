"""Turn AEO answers into share of voice, DE/EN gaps, stability, an accuracy review queue,
and `aeo_gap` signals for Module 2.

Usage: python -m kompass.aeo.analyze [--run-id aeo-...] [--emit-signals] [--report]
"""
import argparse
import csv
import hashlib
import itertools
import json
from collections import defaultdict

from kompass.db import connect, ROOT

GAP_THRESHOLD = 0.2      # EN share of voice minus DE share of voice that counts as a language gap
MIN_N = 10               # cells with fewer answers are flagged as too small to conclude from


def latest_run() -> str | None:
    con = connect(read_only=True)
    r = con.execute("SELECT run_id FROM aeo_answers ORDER BY asked_at DESC LIMIT 1").fetchone()
    con.close()
    return r[0] if r else None


def load(run_id: str):
    con = connect(read_only=True)
    answers = con.execute("SELECT answer_id, question_id, lang, provider, repeat_idx FROM aeo_answers "
                          "WHERE run_id = ?", [run_id]).fetchall()
    mentions = con.execute("""SELECT m.answer_id, m.vendor, m.position, m.sentence FROM aeo_mentions m
                              JOIN aeo_answers a USING (answer_id) WHERE a.run_id = ?""", [run_id]).fetchall()
    con.close()
    return answers, mentions


def share_of_voice(answers, mentions) -> dict:
    by_answer = defaultdict(set)
    pos = defaultdict(list)
    for aid, vendor, position, _ in mentions:
        by_answer[aid].add(vendor)
        pos[vendor].append(position)
    totals = defaultdict(int)
    hits = defaultdict(lambda: defaultdict(int))
    for aid, _, lang, provider, _ in answers:
        for key in (lang, f"{provider}:{lang}", "all"):
            totals[key] += 1
            for v in by_answer.get(aid, ()):
                hits[v][key] += 1
    sov = {}
    for v, h in hits.items():
        sov[v] = {k: round(h[k] / totals[k], 3) for k in totals if h.get(k)}
        sov[v]["n"] = {k: totals[k] for k in ("de", "en", "all")}
        sov[v]["small_sample"] = min(totals.get("de", 0), totals.get("en", 0)) < MIN_N
        sov[v]["avg_position"] = round(sum(pos[v]) / len(pos[v]), 2)
        sov[v]["de_en_gap"] = round(sov[v].get("en", 0) - sov[v].get("de", 0), 3)
    return dict(sorted(sov.items(), key=lambda kv: -kv[1].get("all", 0)))


def stability(answers, mentions) -> float | None:
    """Mean pairwise Jaccard of vendor sets across repeats of the same question/lang/provider."""
    by_answer = defaultdict(set)
    for aid, vendor, _, _ in mentions:
        by_answer[aid].add(vendor)
    groups = defaultdict(list)
    for aid, q, lang, provider, _ in answers:
        groups[(q, lang, provider)].append(by_answer.get(aid, set()))
    scores = []
    for sets in groups.values():
        for a, b in itertools.combinations(sets, 2):
            scores.append(len(a & b) / len(a | b) if (a | b) else 1.0)
    return round(sum(scores) / len(scores), 3) if scores else None


def cited_domains(run_id: str, top: int = 15) -> list[tuple[str, int]]:
    from urllib.parse import urlparse
    con = connect(read_only=True)
    rows = con.execute("SELECT citations FROM aeo_answers WHERE run_id = ?", [run_id]).fetchall()
    con.close()
    counts = defaultdict(int)
    for (c,) in rows:
        for url in json.loads(c or "[]"):
            host = urlparse(url).netloc.removeprefix("www.")
            if host:
                counts[host] += 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top]


DISCOVER_PROMPT = """List every company or product brand named in this answer. JSON only: {{"names": ["..."]}}
Answer: \"\"\"{answer}\"\"\""""


def untracked_vendors(run_id: str, limit: int = 60) -> list[tuple[str, int]]:
    """Companies the assistants name that we don't track yet (live mode only)."""
    from kompass.llm import complete_json, mode
    if mode() == "mock":
        return []
    from kompass.aeo.run import load_vendors
    known = {a.lower() for v in load_vendors() for a in v["aliases"]}
    con = connect(read_only=True)
    rows = con.execute("SELECT answer FROM aeo_answers WHERE run_id = ? LIMIT ?", [run_id, limit]).fetchall()
    con.close()
    counts = defaultdict(int)
    for (ans,) in rows:
        try:
            names = complete_json(DISCOVER_PROMPT.format(answer=ans[:3000]), purpose="aeo_entities",
                                  max_tokens=300).get("names", [])
        except Exception:
            continue
        for n in {n.strip() for n in names if n.strip()}:
            if n.lower() not in known:
                counts[n] += 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:20]


def gap_accounts(sov: dict) -> list[dict]:
    con = connect(read_only=True)
    accs = con.execute("""SELECT a.account_id, a.name, s.tier FROM accounts a JOIN account_scores s USING (account_id)
                          WHERE s.tier IN ('A', 'B')""").fetchall()
    con.close()
    out = []
    for aid, name, tier in accs:
        s = sov.get(aid)
        if not s:
            out.append({"account_id": aid, "name": name, "tier": tier, "gap": "invisible",
                        "detail": "not named in any answer to our buyer questions"})
        elif s["de_en_gap"] >= GAP_THRESHOLD:
            out.append({"account_id": aid, "name": name, "tier": tier, "gap": "weaker_in_german",
                        "detail": f"named in {s.get('en', 0):.0%} of English answers vs {s.get('de', 0):.0%} of German"})
    return out


def accuracy_queue(run_id: str, path) -> int:
    """Sentences that describe our accounts, next to what we know, for a human to mark accurate or not."""
    con = connect(read_only=True)
    rows = con.execute("""SELECT a.question_id, a.lang, a.provider, m.vendor, m.sentence, ac.segment, ac.segment_reason
                          FROM aeo_mentions m JOIN aeo_answers a USING (answer_id)
                          JOIN accounts ac ON ac.account_id = m.vendor WHERE a.run_id = ?""", [run_id]).fetchall()
    con.close()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["question", "lang", "provider", "account", "model_sentence", "our_segment", "our_evidence",
                    "accurate (y/n)"])
        w.writerows([list(r) + [""] for r in rows])
    return len(rows)


def emit_signals(run_id: str, gaps: list[dict]) -> int:
    con = connect()
    for g in gaps:
        sid = hashlib.sha1(f"{run_id}:{g['account_id']}".encode()).hexdigest()[:12]
        con.execute("INSERT OR REPLACE INTO signals VALUES (?, ?, 'aeo_gap', ?, ?, ?, now(), 0.8, 'aeo', NULL)",
                    [sid, g["account_id"], f"AI assistant visibility: {g['gap']}",
                     f"kompass://aeo/{run_id}/{g['account_id']}", g["detail"]])
    con.close()
    return len(gaps)


def report(run_id: str, emit: bool = False, discover: bool = False) -> dict:
    answers, mentions = load(run_id)
    sov = share_of_voice(answers, mentions)
    gaps = gap_accounts(sov)
    con = connect(read_only=True)
    providers = sorted({r[3] for r in answers})
    names = dict(con.execute("SELECT account_id, name FROM accounts").fetchall())
    con.close()
    out_dir = ROOT / "aeo" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_queue = accuracy_queue(run_id, out_dir / f"{run_id}-accuracy-review.csv")
    res = {"run_id": run_id, "answers": len(answers), "providers": providers,
           "stability": stability(answers, mentions), "share_of_voice": sov, "gap_accounts": gaps,
           "accuracy_review_rows": n_queue, "cited_domains": cited_domains(run_id),
           "untracked_vendors": untracked_vendors(run_id) if discover else None}
    if emit:
        res["signals_emitted"] = emit_signals(run_id, gaps)

    lines = [f"# AI assistant visibility: DACH robotics & industrial AI", "",
             f"Run `{run_id}` · {len(answers)} answers · providers: {', '.join(providers)} · "
             f"answer stability (Jaccard across repeats): {res['stability']}", "",
             "> Answers come from provider APIs, which can differ from consumer chat apps. Single snapshot.", "",
             "| vendor | share of voice | German | English | EN−DE | avg position |", "|---|---|---|---|---|---|"]
    for v, s in list(sov.items())[:15]:
        flag = " ⚠ small n" if s["small_sample"] else ""
        lines.append(f"| {names.get(v, v)}{flag} | {s.get('all', 0):.0%} | {s.get('de', 0):.0%} | {s.get('en', 0):.0%} | "
                     f"{s['de_en_gap']:+.0%} | {s['avg_position']} |")
    lines += ["", f"_Share of voice excludes vendors named in the question itself. n per language: "
                  f"{next(iter(sov.values()))['n'] if sov else '-'}. Cells under {MIN_N} answers are flagged._"]
    lines += ["", "## Most-cited sources", ""] + ([f"- {d}: {n}" for d, n in res["cited_domains"]]
                                                   or ["- none returned by these providers"])
    if res["untracked_vendors"]:
        lines += ["", "## Named by assistants but not tracked yet", ""] + \
                 [f"- {n}: {c} answers" for n, c in res["untracked_vendors"]]
    lines += ["", "## Accounts with visibility gaps", ""] + \
             [f"- **{g['name']}** (Tier {g['tier']}): {g['detail']}" for g in gaps] + \
             ["", f"Accuracy review queue: `aeo/reports/{run_id}-accuracy-review.csv` ({n_queue} sentences)."]
    (out_dir / f"{run_id}.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / f"{run_id}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--emit-signals", action="store_true")
    ap.add_argument("--discover", action="store_true", help="find vendors the assistants name that we don't track")
    a = ap.parse_args()
    rid = a.run_id or latest_run()
    if not rid:
        raise SystemExit("no AEO runs yet: python -m kompass.aeo.run")
    r = report(rid, a.emit_signals, a.discover)
    print(json.dumps({k: v for k, v in r.items() if k != "share_of_voice"}, indent=2))
    print(f"report: aeo/reports/{rid}.md")
