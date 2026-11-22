"""Daily signal pipeline: fetch postings -> classify -> signals -> activate -> draft -> review queue.

Usage:
  python -m kompass.signals.run                       # live job boards
  python -m kompass.signals.run --fixtures tests/fixtures/ats   # offline demo from saved boards
  python -m kompass.signals.run --detect              # try to find each account's ATS first
"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from kompass.db import connect
from kompass.review import slack
from kompass.signals import ats
from kompass.signals.activate import active_accounts
from kompass.signals.classify_signals import classify_posting
from kompass.signals.draft import make_draft, save_draft


def _load_fixture(fdir: Path, provider: str, slug: str):
    for ext in (".xml", ".json"):
        f = fdir / f"{provider}_{slug}{ext}"
        if f.exists():
            raw = f.read_text(encoding="utf-8")
            if provider == "personio":
                return ats.parse_personio(raw, slug)
            data = json.loads(raw)
            return {"greenhouse": ats.parse_greenhouse, "lever": ats.parse_lever,
                    "ashby": ats.parse_ashby}[provider](data)
    return None


def collect(fixtures: Path | None = None, detect: bool = False) -> dict:
    stats = {"boards_ok": 0, "boards_failed": 0, "new_postings": 0, "llm_calls": 0, "signals": 0}
    con = connect()
    accounts = con.execute("SELECT account_id, domain, ats_provider, ats_slug FROM accounts").fetchall()
    con.close()
    for account_id, domain, provider, slug in accounts:
        if not provider and detect and not fixtures:
            found = ats.detect(domain)
            if found:
                provider, slug = found
                con = connect()
                con.execute("UPDATE accounts SET ats_provider=?, ats_slug=? WHERE account_id=?",
                            [provider, slug, account_id])
                con.close()
        if not provider:
            continue
        posts = _load_fixture(fixtures, provider, slug) if fixtures else ats.fetch(provider, slug)
        if posts is None:
            stats["boards_failed"] += 1
            continue
        stats["boards_ok"] += 1
        con = connect()
        seen = [f"{provider}:{slug}:{p['id']}" for p in posts]
        # postings that disappeared from the board: role likely filled, so the signal is closed
        closed = con.execute(f"""SELECT posting_id FROM postings WHERE account_id = ? AND closed_at IS NULL
                                 {'AND posting_id NOT IN (' + ','.join('?' * len(seen)) + ')' if seen else ''}""",
                             [account_id, *seen]).fetchall()
        for (cid,) in closed:
            con.execute("UPDATE postings SET closed_at = now() WHERE posting_id = ?", [cid])
            con.execute("UPDATE signals SET closed_at = now() WHERE signal_id = ?",
                        [hashlib.sha1(cid.encode()).hexdigest()[:12]])
            stats["closed"] = stats.get("closed", 0) + 1
        for p in posts:
            pid = f"{provider}:{slug}:{p['id']}"
            if con.execute("SELECT 1 FROM postings WHERE posting_id=?", [pid]).fetchone():
                con.execute("UPDATE postings SET last_seen = now() WHERE posting_id = ?", [pid])
                continue                                   # only new postings cost money
            stats["new_postings"] += 1
            con.execute("INSERT INTO postings (posting_id, account_id, title, location, url, description) "
                        "VALUES (?, ?, ?, ?, ?, ?)", [pid, account_id, p["title"], p["location"], p["url"],
                                                      p["description"]])
            res = classify_posting(p)
            stats["llm_calls"] += int(res["llm_used"])
            con.execute("UPDATE postings SET classified=true WHERE posting_id=?", [pid])
            if res["signal_type"] != "none":
                stats["signals"] += 1
                posted = p.get("posted_at")
                try:
                    observed = datetime.fromisoformat(posted.replace("Z", "+00:00")).replace(tzinfo=None) \
                        if posted else datetime.now()
                except ValueError:
                    observed = datetime.now()
                con.execute("INSERT OR REPLACE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ats', NULL)",
                            [hashlib.sha1(pid.encode()).hexdigest()[:12], account_id, res["signal_type"],
                             p["title"], p["url"], (p.get("description") or "")[:500], observed,
                             res["confidence"]])
        con.close()
    return stats


def draft_for_active(now: datetime | None = None) -> dict:
    stats = {"active_accounts": 0, "drafts": 0, "blocked": 0, "posted_to_slack": 0}
    con = connect(read_only=True)
    already = {r[0] for r in con.execute(
        "SELECT account_id FROM drafts WHERE status IN ('pending','approved','edited')").fetchall()}
    con.close()
    for acc in active_accounts(now):
        stats["active_accounts"] += 1
        if acc["account_id"] in already:
            continue                                       # one open draft per account
        d = make_draft(acc)
        save_draft(d)
        stats["drafts"] += 1
        if not d["guard_ok"]:
            stats["blocked"] += 1
            continue
        if slack.post_for_review({**d, "name": acc["name"], "domain": acc["domain"]}):
            stats["posted_to_slack"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path)
    ap.add_argument("--detect", action="store_true")
    args = ap.parse_args()
    print("collect:", collect(args.fixtures, args.detect))
    print("drafts: ", draft_for_active())
    print("Review queue: python -m kompass.review.cli   (or in Slack, if configured)")


if __name__ == "__main__":
    main()
