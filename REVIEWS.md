# Build reviews

After each module, the build is reviewed as a senior GTM engineer / operator would review it before letting it near a real pipeline. Gaps found are fixed before moving on. This file is the log.

The bar: **Would a founder trust this system with their market and their brand?** That means grounded in evidence, safe by default, measurable, and runnable by someone other than the builder.

---

## Module 1 — Context layer

**First version verdict: not yet.** It worked, but a senior reviewer would push back on five points:

| # | Gap | Why it matters to an operator | Fix |
|---|---|---|---|
| 1 | Classified from company name + domain only | The model relies on memory, so obscure startups get confident made-up labels | Classifier now reads the company's homepage text and must quote it; no page = low confidence + manual review, never a guess |
| 2 | No offline mode | Can't demo, test or run in CI without spending API credit | Shared `llm.py` with `KOMPASS_LLM=mock` deterministic handlers, clearly labelled as not-a-model |
| 3 | No cost logging | "Cost per account" was promised but unmeasurable | Every LLM call logged (tokens, latency, success); `report.py` turns it into cost once real prices are added in `config.yaml` |
| 4 | Low-confidence labels could produce Tier A | Reps would waste calls on accounts the system wasn't sure about | Low confidence caps at Tier B and sets `needs_review` |
| 5 | No tests, no coverage report | Nobody else could trust or extend it | 8 tests; `python -m kompass.report` prints fill rates, tiers, review queue, dedup counts |

**After fixes: passes.** Evidence-grounded, guarded, measurable, testable.
**Still open (honest):** account list is 9 hand-entered seeds; real numbers require ~150 verified accounts and 50 hand labels.

---

## Module 2 — Signal agent with human approval

**First version verdict: not yet.** The pipeline ran end to end (4 ATS formats → classifier → compounding activation → cited draft → review queue), but an operator reading the output would object:

| # | Gap | Why it matters to an operator | Fix |
|---|---|---|---|
| 1 | Draft said "Testbot Robotics GmbH is hiring a Founding Account Executive (m/w/d)" | Legal suffixes and German gender tags are an instant "a bot wrote this" tell | `signals/text.py` cleans titles (m/w/d, all genders, Remote) and company names before prompting |
| 2 | No recipient | A message without a "who" is half a play | Each signal maps to a persona (`personas_by_signal`); review card says who to send to. No personal contact data is stored; the reviewer finds the person |
| 3 | Channel ignored DACH rules | Cold B2B email in DE/AT is legally risky (UWG §7 / TKG) | `channel_policy` per country on every draft (operational default, flagged as not legal advice) |
| 4 | Filled roles kept triggering outreach | Writing about a role that's already filled burns credibility | Postings that disappear from a board close their signal; closed signals no longer activate accounts |
| 5 | No funnel metrics | Can't prove precision, approval or edit rates | `signals/report.py` funnel + `eval/signal_check.py` precision/recall vs hand labels |

**Also built in from the start:** keyword prefilter so irrelevant roles never cost an LLM call; only new postings are classified; guard blocks uncited claims, unknown sources, banned phrases and numbers not present in evidence; blocked drafts cannot be approved; Slack requests are signature-verified with replay protection.

**After fixes: passes.** 15 Module 2 tests.
**Still open (honest):** live job boards and Slack untested from this sandbox (no outbound network); 100 hand-labelled postings needed for a real precision number.

---

## Module 3 — GTM CI/CD lab

**First version verdict: close, not yet.** Versioned prompts, a golden set, a CI gate that blocks a deliberately broken prompt, A/B with significance testing, and an edit-learning loop that ranks by impact and proposes a PR were all working. An operator would still push on:

| # | Gap | Why it matters to an operator | Fix |
|---|---|---|---|
| 1 | Golden set synthetic, no way to grow it | Evals on made-up cases prove the harness, not the system | `eval/golden/promote.py` turns approved/edited real drafts into golden cases, with the human's final text as reference |
| 2 | CI passed silently without an API key | A green check that tested nothing is worse than red | Workflow now fails loudly if prompts changed and the live gate can't run |
| 3 | No cost per draft per version | A 10% better prompt at 3x tokens is not automatically a win | Eval table now includes tokens per draft per version/model |
| 4 | Judge could grade its own model | Self-grading bias | `--judge-model` flag; warning if judge = candidate |
| 5 | Learned rules would pile up | Prompt bloat and contradictions over time | Known rules are never re-added; max 5 learned rules, oldest drop off |

**Design choices a reviewer should notice:**
- Deterministic checks (citations, invented numbers, forbidden phrases) decide the gate; the LLM judge is optional and versioned.
- Edits are ranked by impact (edit distance; reject = 1.0), not frequency. A test proves 3 costly edits outrank 5 cheap ones.
- Vague hypotheses (tone, wrong persona, factual errors) are routed to a human, never automated.
- A/B refuses to declare a winner below 30 reviews per arm; promotion requires p < 0.05 *and* no extra editing.
- Every production change is a PR a human merges; rollback = revert the PR.

**After fixes: passes.** 15 Module 3 tests.
**Still open (honest):** needs 25 real golden cases and live runs for publishable numbers; the learning loop needs a few weeks of real reviews to produce a meaningful proposal.

---

## Module 4 — AEO visibility radar

**First version verdict: not yet.** 20 buyer questions in German and English, multi-provider runner (Anthropic + any OpenAI-compatible API: OpenAI, Gemini, Perplexity), mention extraction, share of voice, DE/EN gap, stability across repeats and `aeo_gap` signals into Module 2 all worked. An AEO specialist would still challenge the numbers:

| # | Gap | Why it matters to an operator | Fix |
|---|---|---|---|
| 1 | Leading questions counted as mentions | "Alternatives to Universal Robots?" inflates Universal Robots' share of voice | Vendors named in the question are excluded from that answer and recorded as `excluded_vendors` |
| 2 | No citation sources | "Which sites do assistants cite?" tells a company where to get coverage, the most actionable AEO output | Provider citation fields (e.g. Perplexity) + URLs in answers stored; report lists most-cited domains |
| 3 | Blind to untracked competitors | The vendors you don't track are the ones a founder most needs to hear about | `--discover` lists brands assistants name that aren't in the tracking list |
| 4 | Percentages without sample sizes | 33% from 3 answers isn't a finding | n per language on every vendor; cells under 10 answers flagged in the report |

**Also built in:** case-sensitive matching for short or ambiguous aliases (MiR, ABB), so "mirror" or "abbey" don't count; providers without keys or model ids are skipped and listed, never silently dropped; every report states it is an API snapshot, which can differ from consumer apps; accuracy of how assistants describe each account goes to a human review CSV rather than being auto-scored.

**After fixes: passes.** 7 Module 4 tests.
**Still open (honest):** first real run needs API keys and current model ids per provider; weekly trend needs repeated runs.

---

## Module 5 — Compliant inbound agent

**First version verdict: not yet.** The form (AI notice, consent, privacy note), qualification through the context layer, a 120-second time budget, failure paths to a human, instant booking link for hot leads, 90-day retention and a 50-lead test set (98% routing accuracy in mock mode; the one miss is a German job application read as buying intent, which still lands with a human) all worked. An operator would push on:

| # | Gap | Why it matters to an operator | Fix |
|---|---|---|---|
| 1 | Hot-lead Slack alert had no context | "Hot lead at X" makes the founder research before replying, which kills speed-to-lead | Alert carries a brief from the context layer: tier, segment, open signals with links |
| 2 | Founders using Gmail were treated as generic | Many early founders use personal email | If the company field matches a Tier A/B account, it's flagged as a possible hot lead and alerted |
| 3 | Prompt injection and abuse | "Ignore your instructions…" in a form, or bots running up LLM cost | Visitor text is fenced as data and tag-stripped; tier always comes from our own data (a test proves a fooled classifier still can't create a hot lead); per-IP rate limit and field length limits |
| 4 | No CRM | Leads living only in a local DB don't get worked | Optional HubSpot contact upsert with the route and reason; failures never block routing |
| 5 | No inbound metrics | Can't show speed-to-lead | `inbound/report.py`: route mix, median and p95 seconds, possible-hot count, human-request rate (test leads excluded by default) |

**After fixes: passes.** 15 Module 5 tests.
**Still open (honest):** routing accuracy is on synthetic test leads with mock classification; real accuracy needs real (or realistic, labelled) leads in live mode. The privacy note is a template to have checked.

---

## Whole-system check

- **55 tests** across all five modules, all running offline in mock mode (`KOMPASS_LLM=mock pytest`).
- **Nothing reaches a prospect without a human:** outbound drafts need approval; blocked drafts can't be approved; prompt changes need a merged PR; inbound hot leads get a booking link but every handoff is read by a person.
- **Every claim is traceable:** segments cite the homepage, signals cite the posting, drafts cite signals, AEO findings keep the model's sentence.
- **Every number has a script:** `kompass.report`, `signals.report`, `eval/run_eval.py`, `aeo.analyze`, `inbound.report`, plus hand-label checks for segments, signals and routing.
- **Not yet real:** no published number exists until it comes from a live run on real, verified data. Mock output and synthetic cases are labelled everywhere they appear.
