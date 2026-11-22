"""Routing accuracy on labelled test leads (SYNTHETIC, marked is_test).

Usage: python eval/inbound_check.py [tests/fixtures/test_leads.csv]
Needs the matching accounts in the context layer (the test suite seeds them).
"""
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kompass.inbound.qualify import process_lead  # noqa: E402


def evaluate(path) -> dict:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    results, confusion, times = [], Counter(), []
    for r in rows:
        res = process_lead({**r, "consent": r["consent"] == "yes"}, is_test=True)
        ok = res["route"] == r["expected_route"]
        results.append(ok)
        if not ok:
            confusion[(r["expected_route"], res["route"])] += 1
        if res.get("seconds") is not None:
            times.append(res["seconds"])
    times.sort()
    return {"n": len(rows), "routing_accuracy": round(sum(results) / len(rows), 3),
            "median_seconds": times[len(times) // 2] if times else None,
            "max_seconds": times[-1] if times else None,
            "errors": [f"{e} -> {g}: {n}" for (e, g), n in confusion.most_common()]}


if __name__ == "__main__":
    print(evaluate(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/test_leads.csv"))
