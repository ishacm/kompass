"""Offline end-to-end demo of all five modules (mock LLM, fixture data, temp database).

Run: python scripts/demo.py
Good for recording walkthroughs. Every number printed here is from MOCK mode and fixtures:
it shows the system working, it is not a result to publish.
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["KOMPASS_DB"] = str(tmp / "demo.duckdb")
os.environ["KOMPASS_LLM"] = "mock"

from kompass import ingest, score, report  # noqa: E402
from kompass.db import connect  # noqa: E402
from kompass.signals import run as signals  # noqa: E402
from kompass.signals.report import funnel  # noqa: E402
from kompass.review.store import pending, record_review  # noqa: E402
from kompass.learn import edits  # noqa: E402
from kompass.aeo import run as aeo, analyze  # noqa: E402

sys.path.insert(0, str(ROOT / "eval"))
from run_eval import run as run_eval, table  # noqa: E402
from inbound_check import evaluate as inbound_eval  # noqa: E402


def h(t):
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


h("MODULE 1 · Context layer: ingest, dedupe, score")
csv = tmp / "accounts.csv"
csv.write_text("name,domain,country,employees,founded,ats_provider,ats_slug,source\n"
               "Testbot Robotics GmbH,testbot.example,DE,80,2018,personio,testbot,fixture\n"
               "Testbot Robotics,https://www.testbot.example/,DE,,,,,fixture_dup\n"
               "Lagerfix AG,lagerfix.example,AT,300,2015,greenhouse,lagerfix,fixture\n"
               "Bigcorp Industrie SE,bigcorp.example,DE,9000,1950,,,fixture\n"
               "Valley Bots Inc,valleybots.example,US,40,2020,lever,valleybots,fixture\n")
ingest.ingest([str(csv)])
con = connect()
con.execute("UPDATE accounts SET segment='cobots_and_arms', segment_confidence='high', sells_b2b_industrial=true "
            "WHERE domain IN ('testbot.example','lagerfix.example')")
con.close()
score.main()
cov = report.coverage()
print({k: cov[k] for k in ("accounts", "tiers", "ingest", "needs_review")})

h("MODULE 2 · Signal agent: job boards -> signals -> cited draft -> human review")
print("collect:", signals.collect(ROOT / "tests" / "fixtures" / "ats"))
print("drafts: ", signals.draft_for_active(datetime(2026, 11, 20)))
d = pending()[0]
print(f"\nSend to: {d['play']['persona']} via {d['play']['channel']}\n  ({d['play']['channel_note']})")
for c in d["why_now"]:
    print(f"  why now: {c['claim']} [{c['source_id']}] -> {d['sources'][c['source_id']]}")
print(f"\n  DRAFT: {d['body']}")
r = record_review(d["draft_id"], "edit", reviewer="demo",
                  final_body="Saw the Founding Account Executive role [S1]. Happy to share the account list I'd hand them on day one.",
                  reason="shorter, no question")
print(f"\n  reviewer edited it: edit distance {r['edit_distance']}")
print("funnel:", {k: v for k, v in funnel().items() if k in ("postings_scanned", "signals_open", "drafts_total",
                                                              "reviews", "avg_edit_distance")})

h("MODULE 3 · GTM CI/CD: golden-set eval of prompt versions + edit ranking")
print(table(run_eval(["v1", "v2"], [None])))
ranked = edits.rank(edits.collect(days=30))
print("\nedit hypotheses ranked by impact:", [(g["hypothesis"], g["impact"], g["count"]) for g in ranked])

h("MODULE 4 · AEO radar: who do assistants recommend, DE vs EN")
st = aeo.run(repeats=2, question_ids=["q01", "q04", "q16"], provider_ids=["claude", "openai"])
res = analyze.report(st["run_id"], emit=True)
print({k: res[k] for k in ("answers", "providers", "stability", "signals_emitted")})
for v, s in list(res["share_of_voice"].items())[:5]:
    print(f"  {v:22} all {s.get('all', 0):.0%}  DE {s.get('de', 0):.0%}  EN {s.get('en', 0):.0%}"
          f"{'  (small n)' if s['small_sample'] else ''}")
for f in (ROOT / "aeo" / "reports").glob(f"{st['run_id']}*"):
    f.unlink()

h("MODULE 5 · Inbound agent: 50 labelled test leads")
print(inbound_eval(ROOT / "tests" / "fixtures" / "test_leads.csv"))

print("\nAll numbers above: mock mode + fixtures. Run live with real data before publishing anything.")
