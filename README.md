# Kompass

[![tests](https://github.com/ishacm/kompass/actions/workflows/eval.yml/badge.svg)](https://github.com/ishacm/kompass/actions/workflows/eval.yml)

A self-learning GTM engine for DACH deep-tech (robotics, automation, industrial AI).
**Agents propose, evals check, humans approve.**

| Module | What it does | Run |
|---|---|---|
| [01 Context layer](specs/01-context-layer.md) | Accounts, signals and strategy in DuckDB; segments grounded in each company's homepage; served read-only to agents over MCP | `python -m kompass.ingest` · `classify` · `score` · `report` · `mcp_server` |
| [02 Signal agent](specs/02-signal-agent.md) | Public job boards (Personio, Greenhouse, Lever, Ashby) → signals → compounding activation → cited draft with persona + DACH channel policy → Slack/CLI approval | `python -m kompass.signals.run` · `review.cli` · `signals.report` |
| [03 GTM CI/CD lab](specs/03-gtm-ci-cd-lab.md) | Versioned prompts, golden set, CI gate, A/B with significance, learning loop that ranks reviewer edits by impact and proposes a PR, weekly drift check | `python eval/run_eval.py` · `eval/gate.py` · `kompass.learn.ab` · `kompass.learn.edits` |
| [04 AEO radar](specs/04-aeo-radar.md) | 20 buyer questions in German + English across Claude / OpenAI / Gemini / Perplexity: share of voice, DE–EN gap, stability, cited sources, untracked vendors, gap signals into Module 2 | `python -m kompass.aeo.run` · `kompass.aeo.analyze --emit-signals --discover` |
| [05 Inbound agent](specs/05-inbound-agent.md) | Portfolio contact form with AI disclosure + consent; qualifies via the context layer; hot leads get an instant booking link and a Slack brief; every failure goes to a human; 90-day retention; optional HubSpot | `uvicorn kompass.inbound.app:app` · `inbound.retention` · `inbound.report` |

**How each module was reviewed and hardened:** [REVIEWS.md](REVIEWS.md)

## Try it in 1 minute (offline, no API key)
```bash
pip install -r requirements.txt pytest
python scripts/demo.py           # all five modules end to end on fixtures (mock LLM)
KOMPASS_LLM=mock pytest -q       # 65 tests
```
Mock mode uses keyword rules instead of a model. It proves the system works; its numbers are never results.

## Free mode (default): runs at €0

| Piece | Free option used | Trade-off |
|---|---|---|
| AI for classification, signals, drafts, evals | **Groq** free tier (`openai/gpt-oss-120b`), set in `kompass/config.yaml` → `llm.provider` | Daily rate limits; draft quality below Claude. Switch any time: `KOMPASS_PROVIDER=anthropic` |
| Scheduled jobs + CI | **GitHub Actions**, free on public repos | none for this workload |
| AEO radar | **Gemini** free tier only (set a current model id in `config.yaml`) | Can't measure ChatGPT / Claude answers without their paid APIs; label reports "Gemini only" |
| Inbound form | **Render free** (`render.free.yaml`) + **HubSpot free CRM** as the lead store | Sleeps after 15 min (keep awake with a free pinger on `/healthz`); no disk, so the server rebuilds its account list from `data/accounts_public.csv` on start and leads live in HubSpot |

Privacy guard: inbound lead text is never sent to a provider whose free tier trains on prompts (Gemini free is marked so in `config.yaml`). If configured that way, leads route to a human instead.

Other free/local options already wired in: `ollama` (local models) and any OpenAI-compatible endpoint.

## Run it for real
```bash
export GROQ_API_KEY=...                      # free mode; or ANTHROPIC_API_KEY + KOMPASS_PROVIDER=anthropic
                                             # AEO: GEMINI_API_KEY (free) / OPENAI / PERPLEXITY / ANTHROPIC
python -m kompass.ingest data/seed_accounts.csv
python -m kompass.classify && python -m kompass.score && python -m kompass.report
python -m kompass.export_accounts            # public scored list for the free inbound host (commit it)
python -m kompass.signals.run --detect       # finds each account's job board, then runs the pipeline
python -m kompass.review.cli --reviewer you  # or Slack: SLACK_BOT_TOKEN, SLACK_CHANNEL, SLACK_SIGNING_SECRET
python eval/run_eval.py --versions v1 v2 --judge --judge-model <a different model>
python -m kompass.aeo.run && python -m kompass.aeo.analyze --emit-signals --discover
uvicorn kompass.inbound.app:app --port 8080
claude mcp add kompass -- python -m kompass.mcp_server   # let Claude query the context layer
```

## Configure
- `context/icp.yaml` — segments, firmographics, scoring weights, tiers
- `context/positioning.yaml` — personas, pains, value props, writing rules
- `kompass/config.yaml` — AI provider (free: Groq), models, prices (fill in for cost reports), activation thresholds, persona and channel policy, AEO providers, inbound settings (booking link, retention)
- `prompts/registry.yaml` — which prompt version is live and any A/B split (change only by PR)

## Before publishing any number
1. Replace the 9 seed accounts with ~150 verified ones; label 50 by hand → `eval/label_check.py`
2. Label ~100 real job postings → `eval/signal_check.py`
3. Replace synthetic golden cases with 25 real ones (`eval/golden/promote.py` builds them from reviewed drafts)
4. Run everything live, date the run, and state the method next to each number

## Layout
```
context/   strategy as code        kompass/   pipeline code (signals/, review/, learn/, aeo/, inbound/)
prompts/   versioned prompts       eval/      golden set, judge, gate, hand-label checks
aeo/       questions + vendors     specs/     one spec per module      tests/  65 tests + fixtures
```
