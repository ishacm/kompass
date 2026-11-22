"""Data-quality and cost report for the context layer. Numbers here go into the case study.

Usage: python -m kompass.report
"""
from kompass.db import connect
from kompass.llm import cost_summary

FIELDS = ["country", "employees", "founded", "segment", "ats_provider"]


def coverage() -> dict:
    con = connect(read_only=True)
    total = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
    out = {"accounts": total}
    if total:
        for f in FIELDS:
            n = con.execute(f"SELECT count(*) FROM accounts WHERE {f} IS NOT NULL").fetchone()[0]
            out[f"fill_{f}"] = round(n / total, 3)
    out["tiers"] = dict(con.execute("SELECT tier, count(*) FROM account_scores GROUP BY 1").fetchall())
    out["needs_review"] = con.execute(
        "SELECT count(*) FROM account_scores WHERE json_extract(breakdown, '$.needs_review')::BOOLEAN"
    ).fetchone()[0]
    out["confidence"] = dict(con.execute(
        "SELECT coalesce(segment_confidence, 'unclassified'), count(*) FROM accounts GROUP BY 1").fetchall())
    log = con.execute("SELECT sum(rows_in), sum(rows_merged), sum(rows_new) FROM ingest_log").fetchone()
    out["ingest"] = {"rows_in": log[0], "duplicates_merged": log[1], "new": log[2]}
    con.close()
    return out


if __name__ == "__main__":
    import json
    print(json.dumps({"coverage": coverage(), "llm_cost": cost_summary()}, indent=2, default=str))
