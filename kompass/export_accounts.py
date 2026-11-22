"""Export the scored account list (company-level public data only) so a free, stateless host can
load it at start-up without calling an LLM.

Usage: python -m kompass.export_accounts            -> data/accounts_public.csv (commit it)
"""
import csv

from kompass.db import connect, ROOT

COLS = ["name", "domain", "country", "employees", "founded", "ats_provider", "ats_slug",
        "segment", "segment_confidence", "sells_b2b_industrial"]


def export(path=ROOT / "data" / "accounts_public.csv") -> int:
    con = connect(read_only=True)
    rows = con.execute(f"SELECT {', '.join(COLS)} FROM accounts ORDER BY domain").fetchall()
    con.close()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS + ["source"])
        w.writerows([list(r) + ["export"] for r in rows])
    return len(rows)


if __name__ == "__main__":
    print(f"exported {export()} accounts to data/accounts_public.csv")
