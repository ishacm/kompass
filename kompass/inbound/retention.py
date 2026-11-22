"""Delete inbound personal data after the retention period, unless the lead converted.

Run daily (cron / scheduled job): python -m kompass.inbound.retention
"""
from datetime import datetime, timedelta

import yaml

from kompass.db import connect, ROOT

DAYS = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["inbound"]["retention_days"]


def purge(now: datetime | None = None, days: int = DAYS) -> int:
    cutoff = (now or datetime.now()) - timedelta(days=days)
    con = connect()
    ids = [r[0] for r in con.execute("SELECT lead_id FROM leads WHERE received_at < ? AND NOT converted",
                                     [cutoff]).fetchall()]
    for lid in ids:
        con.execute("DELETE FROM lead_decisions WHERE lead_id = ?", [lid])
        con.execute("DELETE FROM leads WHERE lead_id = ?", [lid])
    con.close()
    return len(ids)


if __name__ == "__main__":
    print(f"deleted {purge()} leads older than {DAYS} days")
