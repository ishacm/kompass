# SPEC 04 — AEO Visibility Radar (DACH industrial B2B)

**Status:** v1 built + reviewed (see REVIEWS.md). **Sprint day:** 5 (morning). **Depends on:** 01 (vendor list).

## Problem
Buyers increasingly ask AI assistants for vendor shortlists. Industrial companies rarely know whether they appear, how they are described, or whether German and English answers differ.

## Goal
Measure which vendors AI assistants recommend for real buyer questions, in German and English, and turn gaps into a prospect list and a public report.

## Inputs
- `aeo/questions.yaml`: 40 buyer questions (20 DE + 20 EN translations), tagged by persona and segment.
  Example: "Welcher Cobot-Anbieter eignet sich für mittelständische Fertigung?"
- Vendor list + aliases from the context layer.
- 3+ assistants via API (each model's API answer, noted as such — not the consumer app).

## Logic
1. Run every question × model × language; store raw answer, model id, timestamp.
2. Extract vendor mentions (alias matching + LLM extraction), rank position, cited URLs, and description accuracy vs `accounts` facts.
3. Compute share of voice per vendor, citation sources, DE-vs-EN gap, run-to-run stability (repeat 3×).
4. Prospects: tier A/B accounts with low share of voice or inaccurate descriptions → feed into 02 as `aeo_gap` signal.

## Acceptance tests
- [ ] Re-running the same question 3× reports a stability score
- [ ] Every "inaccurate description" finding shows the model's sentence and the source fact

## Metrics to publish
Share of voice top 10 · DE vs EN difference · most-cited source domains · stability · accounts with visibility gaps.
Label v1 as a single snapshot with date; weekly trend added later.
