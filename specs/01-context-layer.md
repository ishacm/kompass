# SPEC 01 — GTM Context Layer ("the brain")

**Status:** v1 built + reviewed (see REVIEWS.md). **Sprint day:** 1–2.

## Problem
GTM agents produce generic or wrong output because they read stale lists and strategy that lives in slide decks. Agents need governed, current context they can query.

## Goal
One warehouse holding accounts, signals and machine-readable strategy, exposed read-only to agents over MCP.

## Scope (v1)
- ~150 DACH robotics / industrial-AI accounts in DuckDB (`data/kompass.duckdb`)
- Dedup by normalised domain, then by legal name with suffixes stripped (GmbH, AG, SE, …)
- LLM segment classification constrained to `context/icp.yaml` segments; off-list labels rejected
- Rule-based ICP score + tier from weights in `icp.yaml`; missing fields flagged, not penalised silently
- MCP server with 4 tools: `get_strategy`, `search_accounts`, `get_account`, `recent_signals`

## Out of scope (v2)
500+ accounts, Northdata / Handelsregister / trade-fair ingestion, contact data, write tools.

## Guardrails
- Read-only DB connection inside the MCP server; no raw-SQL tool
- No person or contact data in the schema
- Every signal must carry an `evidence_url`

## Acceptance tests
- [ ] Ingesting the same company under two spellings creates one account (seed CSV includes a duplicate test row)
- [ ] Segment accuracy ≥ 85% vs 50 hand labels (`python eval/label_check.py`)
- [ ] Claude Desktop / Claude Code can answer "Which Tier A accounts had signals in the last 14 days?" via MCP
- [ ] An unknown domain returns a clear error, not an empty object

## Metrics to publish
Rows in → accounts after dedup · duplicates merged · field fill rate before/after · label accuracy + top confusions · cost per classified account.
