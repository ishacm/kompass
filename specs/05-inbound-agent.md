# SPEC 05 — Compliant Inbound Agent

**Status:** v1 built + reviewed (see REVIEWS.md). **Sprint day:** 5 (afternoon). **Depends on:** 01, 03 (eval runner).

## Problem
Inbound demo requests wait hours, and AI chat agents built in the US often ignore EU rules.

## Goal
Qualify and route inbound from the portfolio site in under two minutes, with AI disclosure, consent and a human handoff designed in.

## Flow
1. Visitor submits form (name, work email, company, need) with a GDPR consent checkbox and a link to the privacy note.
2. Clear notice: "An AI assistant will review your request; a human reads every handoff."
3. Enrich company from email domain → look up via context layer → classify need → ICP tier.
4. Route:
   - Tier A/B: Slack alert with brief (via 01 + 02 logic) + booking link reply
   - Tier C: helpful reply with the most relevant case study
   - Personal email / spam / unclear: polite fallback, flagged for human review
5. Log every decision with inputs and reason. Retention rule: delete lead data after 90 days unless converted.

## Guardrails
AI disclosure always shown (EU AI Act Art. 50). Visitor can ask for a human at any step. No processing without consent. Retries with backoff on enrichment/API failures; failures route to human, never silently dropped.

## Acceptance tests
- [ ] 50 labelled test leads (marked as test data) route with ≥90% accuracy
- [ ] Killing the enrichment API still produces a human-review route within 2 minutes
- [ ] Unchecked consent box stops processing

## Metrics to publish
Median time to route · routing accuracy on test set · handoff rate · failure-path coverage.
