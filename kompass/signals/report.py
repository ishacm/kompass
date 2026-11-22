"""Signal-agent funnel: the numbers for the Module 2 case study.

Usage: python -m kompass.signals.report
"""
import json

from kompass.db import connect


def funnel() -> dict:
    con = connect(read_only=True)
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    out = {
        "postings_scanned": q("SELECT count(*) FROM postings"),
        "postings_closed": q("SELECT count(*) FROM postings WHERE closed_at IS NOT NULL"),
        "signals_open": q("SELECT count(*) FROM signals WHERE closed_at IS NULL AND source='ats'"),
        "signals_by_type": dict(con.execute(
            "SELECT signal_type, count(*) FROM signals WHERE closed_at IS NULL GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "llm_calls_signal_classify": q("SELECT count(*) FROM llm_calls WHERE purpose='signal_classify'"),
        "drafts_total": q("SELECT count(*) FROM drafts"),
        "drafts_blocked_by_guard": q("SELECT count(*) FROM drafts WHERE status='blocked'"),
        "reviews": dict(con.execute("SELECT decision, count(*) FROM reviews GROUP BY 1").fetchall()),
        "avg_edit_distance": q("SELECT round(avg(edit_distance), 3) FROM reviews WHERE edit_distance IS NOT NULL"),
    }
    n = sum(out["reviews"].values())
    if n:
        out["approval_rate_unchanged"] = round(out["reviews"].get("approve", 0) / n, 3)
        out["acceptance_rate_incl_edits"] = round((out["reviews"].get("approve", 0) + out["reviews"].get("edit", 0)) / n, 3)
    blocked = con.execute("SELECT guard_issues FROM drafts WHERE status='blocked'").fetchall()
    reasons = {}
    for (issues,) in blocked:
        for i in json.loads(issues or "[]"):
            key = i.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    out["guard_block_reasons"] = reasons
    con.close()
    return out


if __name__ == "__main__":
    print(json.dumps(funnel(), indent=2, default=str))
