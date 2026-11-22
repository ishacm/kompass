"""Compounding activation: an account becomes 'active' only when signals stack up.

Rule (tunable in kompass/config.yaml -> activation):
  tier in allowed tiers AND (
      weighted signal score within window >= min_score
      OR one high-confidence strong trigger (first_sales_hire / sales_leadership_hire)
  )
Single weak signals never trigger outreach on their own.
"""
from datetime import datetime, timedelta

import yaml

from kompass.db import connect, ROOT
from kompass.signals.classify_signals import SIGNAL_WEIGHT

CFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["activation"]
STRONG = {"first_sales_hire", "sales_leadership_hire"}


def active_accounts(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    since = now - timedelta(days=CFG["window_days"])
    con = connect(read_only=True)
    rows = con.execute(f"""
        SELECT a.account_id, a.name, a.domain, s.tier, a.country, g.signal_id, g.signal_type, g.title,
               g.evidence_url, g.evidence_text, g.confidence, g.observed_at
        FROM signals g JOIN accounts a USING (account_id) JOIN account_scores s USING (account_id)
        WHERE g.observed_at >= ? AND g.signal_type <> 'none' AND g.closed_at IS NULL
          AND s.tier IN ({','.join('?' * len(CFG['tiers']))})
        ORDER BY g.observed_at DESC""", [since, *CFG["tiers"]]).fetchall()
    con.close()

    by_acc: dict[str, dict] = {}
    for r in rows:
        acc = by_acc.setdefault(r[0], {"account_id": r[0], "name": r[1], "domain": r[2], "tier": r[3],
                                       "country": r[4], "signals": []})
        acc["signals"].append({"signal_id": r[5], "signal_type": r[6], "title": r[7], "url": r[8],
                               "evidence_text": r[9] or "", "confidence": r[10], "observed_at": str(r[11])})
    out = []
    for acc in by_acc.values():
        sigs = [s for s in acc["signals"] if s["confidence"] >= CFG["min_confidence"]]
        score = sum(SIGNAL_WEIGHT.get(s["signal_type"], 0) for s in sigs)
        strong = any(s["signal_type"] in STRONG and s["confidence"] >= CFG["strong_confidence"] for s in sigs)
        if score >= CFG["min_score"] or strong:
            acc["signals"] = sorted(sigs, key=lambda s: -SIGNAL_WEIGHT.get(s["signal_type"], 0))
            acc["signal_score"] = score
            acc["trigger"] = "strong_single" if strong and score < CFG["min_score"] else "compounded"
            out.append(acc)
    return sorted(out, key=lambda a: (a["tier"], -a["signal_score"]))
