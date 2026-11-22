"""Load account CSVs, normalise, and merge duplicates by domain (then by legal name).

Usage: python -m kompass.ingest data/seed_accounts.csv [more.csv ...]
"""
import csv
import re
import sys
from urllib.parse import urlparse

from kompass.db import connect

LEGAL_SUFFIXES = r"\b(gmbh|ag|se|kg|ug|mbh|co|ltd|inc|e\.?k\.?|haftungsbeschränkt|& co)\b"


def norm_domain(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    host = urlparse(raw).netloc or urlparse(raw).path
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def norm_name(raw: str) -> str:
    n = (raw or "").lower()
    n = re.sub(LEGAL_SUFFIXES, " ", n)
    n = re.sub(r"[^a-z0-9äöüß ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def ingest(paths):
    con = connect()
    rows_in = merged = new = 0
    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows_in += 1
                domain = norm_domain(row.get("domain"))
                lname = norm_name(row.get("name"))
                if not domain:
                    print(f"skip (no domain): {row.get('name')}")
                    continue
                existing = con.execute(
                    "SELECT account_id FROM accounts WHERE domain = ? OR legal_name_norm = ?",
                    [domain, lname],
                ).fetchone()
                src = row.get("source") or path
                if existing:
                    merged += 1
                    # fill gaps only; never overwrite a known value with an empty one
                    con.execute(
                        """UPDATE accounts SET
                             country   = COALESCE(country, NULLIF(?, '')),
                             employees = COALESCE(employees, ?),
                             founded   = COALESCE(founded, ?),
                             ats_provider = COALESCE(ats_provider, NULLIF(?, '')),
                             ats_slug  = COALESCE(ats_slug, NULLIF(?, '')),
                             sources   = list_distinct(list_append(sources, ?)),
                             updated_at = now()
                           WHERE account_id = ?""",
                        [row.get("country"), to_int(row.get("employees")),
                         to_int(row.get("founded")), row.get("ats_provider"), row.get("ats_slug"),
                         src, existing[0]],
                    )
                else:
                    new += 1
                    con.execute(
                        """INSERT INTO accounts (account_id, name, legal_name_norm, domain,
                               country, employees, founded, ats_provider, ats_slug, sources)
                           VALUES (?, ?, ?, ?, NULLIF(?, ''), ?, ?, NULLIF(?, ''), NULLIF(?, ''), [?])""",
                        [domain, row.get("name"), lname, domain, row.get("country"),
                         to_int(row.get("employees")), to_int(row.get("founded")),
                         row.get("ats_provider"), row.get("ats_slug"), src],
                    )
    con.execute("INSERT INTO ingest_log (rows_in, rows_merged, rows_new) VALUES (?, ?, ?)",
                [rows_in, merged, new])
    print(f"rows in: {rows_in} | new accounts: {new} | merged duplicates: {merged}")
    con.close()


if __name__ == "__main__":
    ingest(sys.argv[1:] or ["data/seed_accounts.csv"])
