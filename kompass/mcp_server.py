"""Kompass MCP server: governed, read-only GTM context for Claude or any MCP client.

Design rules (see specs/01-context-layer.md):
- read-only database connection; agents can query, never write
- only the tools below are exposed; no raw SQL tool, no contact/person data
- every signal returned carries its evidence URL

Run: python -m kompass.mcp_server      (stdio transport)
"""
import json
from datetime import datetime, timedelta

try:                                   # mcp SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                    # mcp SDK v1
    from mcp.server.fastmcp import FastMCP as _Server

from kompass.db import connect, ROOT

mcp = _Server("kompass")


def _q(sql, params=()):
    con = connect(read_only=True)
    try:
        cur = con.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def _clean(rows):
    return json.loads(json.dumps(rows, default=str))


@mcp.tool()
def get_strategy() -> dict:
    """Return the current ICP and positioning files the team has approved."""
    return {
        "icp": (ROOT / "context" / "icp.yaml").read_text(),
        "positioning": (ROOT / "context" / "positioning.yaml").read_text(),
    }


@mcp.tool()
def search_accounts(tier: str | None = None, segment: str | None = None,
                    country: str | None = None, limit: int = 25) -> list[dict]:
    """Find accounts by ICP tier (A/B/C/DQ), segment and country. Max 100 rows."""
    sql = """SELECT a.name, a.domain, a.country, a.segment, a.employees, s.tier, s.fit_score
             FROM accounts a LEFT JOIN account_scores s USING (account_id) WHERE 1=1"""
    params = []
    for col, val in (("s.tier", tier), ("a.segment", segment), ("a.country", country)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY s.fit_score DESC NULLS LAST LIMIT ?"
    params.append(min(limit, 100))
    return _clean(_q(sql, params))


@mcp.tool()
def get_account(domain: str) -> dict:
    """Full context for one account: firmographics, score breakdown and all cited signals."""
    acc = _q("""SELECT a.*, s.tier, s.fit_score, s.breakdown
                FROM accounts a LEFT JOIN account_scores s USING (account_id)
                WHERE a.domain = ?""", [domain.lower().removeprefix("www.")])
    if not acc:
        return {"error": f"no account for {domain}"}
    sigs = _q("""SELECT signal_type, title, evidence_url, observed_at, confidence
                 FROM signals WHERE account_id = ? ORDER BY observed_at DESC""", [acc[0]["account_id"]])
    return _clean({**acc[0], "signals": sigs})


@mcp.tool()
def recent_signals(days: int = 14, min_tier: str = "B") -> list[dict]:
    """Accounts with signals in the last N days, at or above a tier (A best). Includes evidence URLs."""
    allowed = {"A": ["A"], "B": ["A", "B"], "C": ["A", "B", "C"]}.get(min_tier, ["A", "B"])
    since = datetime.now() - timedelta(days=days)
    rows = _q(f"""SELECT a.name, a.domain, s.tier, g.signal_type, g.title, g.evidence_url, g.observed_at
                  FROM signals g JOIN accounts a USING (account_id)
                  JOIN account_scores s USING (account_id)
                  WHERE g.observed_at >= ? AND g.closed_at IS NULL AND s.tier IN ({','.join('?' * len(allowed))})
                  ORDER BY g.observed_at DESC LIMIT 200""", [since, *allowed])
    return _clean(rows)


if __name__ == "__main__":
    mcp.run()
