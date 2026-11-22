"""Rule-based ICP fit scoring. Weights and tiers come from context/icp.yaml.

Usage: python -m kompass.score
"""
import json

import yaml

from kompass.db import connect, ROOT

ICP = yaml.safe_load((ROOT / "context" / "icp.yaml").read_text())


def score(acc: dict) -> tuple[int, str, dict]:
    w, f = ICP["weights"], ICP["firmographics"]
    b = {}
    seg = acc.get("segment")
    if seg in ICP["core_segments"]:
        b["core_segment"] = w["core_segment"]
    elif seg in ICP["adjacent_segments"]:
        b["adjacent_segment"] = w["adjacent_segment"]
    if acc.get("country") in f["countries"]:
        b["country_match"] = w["country_match"]
    emp = acc.get("employees")
    if emp is not None and f["employees_min"] <= emp <= f["employees_max"]:
        b["size_in_range"] = w["size_in_range"]
    if (acc.get("founded") or 0) >= f["founded_after"]:
        b["founded_recently"] = w["founded_recently"]
    if acc.get("sells_b2b_industrial"):
        b["sells_b2b_industrial"] = w["sells_b2b_industrial"]

    total = sum(b.values())
    disqualified = seg == "not_a_fit" or (acc.get("country") and acc["country"] not in f["countries"])
    if disqualified:
        return 0, "DQ", {"disqualified": True, **b}
    tier = next(t for t, th in sorted(ICP["tiers"].items(), key=lambda x: -x[1]) if total >= th)
    # flag missing data so nobody mistakes "unknown" for "bad fit"
    b["missing"] = [k for k in ("segment", "country", "employees", "founded") if acc.get(k) is None]
    # an uncertain label must never produce a top-tier account on its own
    if acc.get("segment_confidence") == "low" and tier == "A":
        tier, b["capped"] = "B", "low-confidence segment; review before treating as Tier A"
    b["needs_review"] = acc.get("segment_confidence") == "low" or bool(b["missing"])
    return total, tier, b


def main():
    con = connect()
    cols = ["account_id", "segment", "segment_confidence", "country", "employees", "founded",
            "sells_b2b_industrial"]
    rows = con.execute(f"SELECT {', '.join(cols)} FROM accounts").fetchall()
    counts = {}
    for r in rows:
        acc = dict(zip(cols, r))
        s, tier, b = score(acc)
        counts[tier] = counts.get(tier, 0) + 1
        con.execute("INSERT OR REPLACE INTO account_scores (account_id, fit_score, tier, breakdown) "
                    "VALUES (?, ?, ?, ?)", [acc["account_id"], s, tier, json.dumps(b)])
    print("tier distribution:", counts)
    con.close()


if __name__ == "__main__":
    main()
