# SPEC 02 — Signal Agent with human approval

**Status:** v1 built + reviewed (see REVIEWS.md). **Sprint day:** 3. **Depends on:** 01.

## Problem
Outbound to static lists gets ignored. Buyers respond when there is a real reason to talk *now*, and when a human has checked the message.

## Goal
Detect buying signals for accounts in the context layer, activate accounts only when signals compound, draft a short cited message, and send nothing without human approval in Slack.

## Inputs
Public ATS job boards for each account (try in order; store which one matched):
- Personio: `https://{slug}.jobs.personio.de/xml`
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
- Lever: `https://api.lever.co/v0/postings/{slug}?mode=json`
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{slug}`

## Signal types (LLM classifier, structured JSON output)
`first_sales_hire` · `sales_leadership_hire` · `revops_or_gtm_ops_hire` · `international_expansion` · `partner_or_channel_hire` · `customer_deployment_hire` · `none`

## Logic
1. Daily: fetch new postings → classify → insert into `signals` with posting URL as evidence.
2. Account becomes **active** when ≥2 signals within 30 days, or 1 high-confidence `first_sales_hire`, and tier is A/B.
3. For active accounts: agent calls MCP `get_account` + `get_strategy`, writes a "why now" (cited) and a 2–4 sentence draft per `positioning.yaml` rules.
4. Post to Slack with Approve / Edit / Reject. Log decision, final text and reason to `reviews` table.

## Guardrails
No auto-send. Every claim in a draft links to a signal URL. Rate limit fetchers; respect each board's terms.

## Acceptance tests
- [ ] Signal classifier precision ≥ 80% on 100 hand-labelled postings
- [ ] A draft containing a claim without a source is blocked before Slack
- [ ] Every Slack decision is written to `reviews` with the original and final draft

## Metrics to publish
Postings scanned/day · signal precision & recall · active accounts/week · approval rate · edit rate · cost per approved account.
