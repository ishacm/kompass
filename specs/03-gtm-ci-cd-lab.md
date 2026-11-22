# SPEC 03 — GTM CI/CD Lab (signature module)

**Status:** v1 built + reviewed (see REVIEWS.md). **Sprint day:** 4. **Depends on:** 02 (`reviews` table).

## Problem
Prompts and models change silently. Teams ship prompt edits without knowing whether quality got better or worse, and human corrections to AI drafts are thrown away.

## Goal
Ship GTM prompts like software: versioned, tested on every change, A/B-tested, and improved from human edits — with a human approving every change.

## Components
1. **Versioned prompts:** `prompts/{name}/v{n}.md` in Git. Production version pinned in `prompts/registry.yaml`.
2. **Golden set:** `eval/golden/` — 25 accounts (v1) with hand-verified facts and an ideal "why now".
3. **Eval runner:** scores each draft on factual accuracy, unsupported claims (hallucinations), citation coverage, length/rule compliance, cost and latency. LLM-as-judge allowed only alongside the deterministic checks, with judge prompt also versioned.
4. **CI gate:** GitHub Actions runs the golden set on every PR touching `prompts/`; fails if accuracy drops > 3 pts or unsupported claims rise.
5. **A/B:** active accounts randomly routed to `production` or `experiment` prompt; outcome = approval and edit distance from 02.
6. **Edit-learning loop (v1.5):** cluster human edits from `reviews` into hypotheses, ranked by impact not frequency; agent opens a PR with a proposed prompt change; human merges or rejects.
7. **Drift check:** weekly scheduled run of the golden set on the pinned model; alert on change.

## Acceptance tests
- [ ] A deliberately worse prompt in a PR fails CI
- [ ] Eval report compares ≥2 prompt versions × ≥2 models in one table
- [ ] Every proposed change is a PR with cited evidence from `reviews`

## Metrics to publish
Accuracy & unsupported-claim rate per version/model · edit distance week over week · PRs proposed vs merged · cost per draft.
