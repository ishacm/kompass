"""Grow the golden set from real work: turn approved/edited drafts into golden cases.

The human-approved final text becomes the reference; the job titles become must_mention terms.
Review the YAML it prints, then append it to eval/golden/golden.yaml.

Usage: python eval/golden/promote.py [--limit 10]
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kompass.db import connect  # noqa: E402
from kompass.signals.text import clean_title  # noqa: E402


def candidates(limit: int = 10) -> list[dict]:
    con = connect(read_only=True)
    rows = con.execute("""
        SELECT d.draft_id, a.account_id, a.name, a.domain, s.tier, a.country, d.sources, r.final_body, r.decision
        FROM reviews r JOIN drafts d USING (draft_id) JOIN accounts a USING (account_id)
        LEFT JOIN account_scores s USING (account_id)
        WHERE r.decision IN ('approve', 'edit') ORDER BY r.reviewed_at DESC LIMIT ?""", [limit]).fetchall()
    cases = []
    for did, aid, name, domain, tier, country, sources, final, decision in rows:
        urls = list(json.loads(sources or "{}").values())
        sigs = con.execute(f"""SELECT signal_type, title, evidence_url, evidence_text FROM signals
                               WHERE evidence_url IN ({','.join('?' * len(urls)) or "''"})""", urls).fetchall() \
            if urls else []
        cases.append({
            "id": f"real-{did}", "synthetic": False, "from_decision": decision,
            "account": {"account_id": aid, "name": name, "domain": domain, "tier": tier or "B", "country": country},
            "signals": [{"signal_type": t, "title": ti, "url": u, "evidence_text": (e or "")[:300]}
                        for t, ti, u, e in sigs],
            "must_mention": [clean_title(sigs[0][1]).lower()] if sigs else [],
            "must_not": ["guarantee"],
            "reference_body": final,
        })
    con.close()
    return cases


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    print(yaml.safe_dump(candidates(ap.parse_args().limit), allow_unicode=True, sort_keys=False))
