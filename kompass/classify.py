"""Segment classification grounded in each company's own homepage text.

The model may only use the page text it is given. If the page is unreachable, the
account is labelled with low confidence and flagged for review, never guessed.

Usage: python -m kompass.classify [--limit 50] [--redo]
"""
import argparse

import yaml

from kompass.db import connect, ROOT
from kompass.llm import complete_json, default_model
from kompass.web import homepage_text

ICP = yaml.safe_load((ROOT / "context" / "icp.yaml").read_text())

PROMPT = """You classify B2B companies for a go-to-market team, using ONLY the website text below.

Company: {name}
Domain: {domain}
Website text (may be German or English):
\"\"\"{text}\"\"\"

Choose exactly one segment from: {segments}
sells_b2b_industrial = true only if the text shows they sell to manufacturers, factories or logistics operators.
If the text is too thin to decide, use segment "other_industrial" and confidence "low".
"reason" must quote or closely paraphrase the website text.

Reply with JSON only:
{{"segment": "...", "sells_b2b_industrial": true, "confidence": "high|medium|low", "reason": "..."}}"""


def classify_one(name: str, domain: str, text: str | None) -> dict:
    if not text:
        return {"segment": "other_industrial", "sells_b2b_industrial": False,
                "confidence": "low", "reason": "homepage unreachable; needs manual review"}
    out = complete_json(PROMPT.format(name=name, domain=domain, text=text,
                                      segments=", ".join(ICP["segments"])),
                        purpose="segment_classify", max_tokens=300,
                        context={"text": text, "segments": ICP["segments"]})
    if out.get("segment") not in ICP["segments"]:      # guardrail: reject off-list labels
        out.update(segment="other_industrial", confidence="low",
                   reason=f"off-list label rejected: {out.get('segment')}")
    if out.get("confidence") not in ("high", "medium", "low"):
        out["confidence"] = "low"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()

    con = connect()
    where = "" if args.redo else "WHERE segment IS NULL"
    rows = con.execute(f"SELECT account_id, name, domain FROM accounts {where} LIMIT ?",
                       [args.limit]).fetchall()
    con.close()
    for account_id, name, domain in rows:
        text, url = homepage_text(domain)
        try:
            out = classify_one(name, domain, text)
        except Exception as e:
            print(f"FAILED {domain}: {e}")
            continue
        con = connect()
        con.execute("""UPDATE accounts SET segment=?, segment_confidence=?, segment_evidence_url=?,
                         sells_b2b_industrial=?, segment_reason=?, updated_at=now()
                       WHERE account_id=?""",
                    [out["segment"], out["confidence"], url if text else None,
                     bool(out.get("sells_b2b_industrial")), out.get("reason", ""), account_id])
        con.close()
        print(f"{domain:28} -> {out['segment']:30} ({out['confidence']}) [{default_model()}]")


if __name__ == "__main__":
    main()
