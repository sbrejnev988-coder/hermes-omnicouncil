# Hermes OmniCouncil v5.3.2

**Multi-model agentic council for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — structured debates, evidence-led verifications, and AI-powered deep web research.**

OmniCouncil turns a single Hermes question into a structured deliberation among multiple AI models. Agents collaborate on a shared blackboard, request read-only evidence from safe tools, cross-examine each other's claims, and a judge compiles the final verdict. Think of it as a built-in peer review system for every important decision.

**13 tools. DeepSeek/GPT/mixed presets. Auto-Debate mode with prosecutor audit. Zero external API dependencies — runs on any Hermes provider.**

---

## What It Does

| Feature | Description |
|---|---|
| **Multi-model councils** | 2–8 councils, 3–8 members each, swappable models (DeepSeek, GPT-5.5, mixed) |
| **Shared blackboard** | Agents post facts, objections, questions, actions; judge synthesizes |
| **Brokered safe tools** | Agents request read-only tools (`web_search`, `read_file`, `memory_wiki_query`); orchestrator executes and injects results |
| **Evidence ledger** | Every claim tracked with supporting/contradicting evidence refs |
| **Plan→Probe→Decide** | Preflight: model plans unknowns, requests safe probes, then council decides |
| **Prosecutor audit** | Post-judge adversarial review flags unsupported claims, contradictions, overconfidence |
| **Forced dissent** | Even at consensus, judge must list objections and alternative views |
| **Judge compiler** | Final output includes canonical `JUDGE_COMPILED_JSON` for downstream automation |
| **Auto-Debate/VerifyChain** | One flag turns a task into full proponent/skeptic/prosecutor/verifier/judge debate |
| **Deep web crawler** | Multi-engine discovery, crawling, SQLite source DB, ranked Markdown/HTML/JSON reports |

---

## Quick Start

### Requirements

- **Hermes Agent** 0.14.0 or later
- **Python** 3.10+
- Any configured LLM provider (OpenRouter, DeepSeek proxy, custom endpoint)

### Windows Installation

**Step 1 — Install Hermes Agent** (if not already installed)

Open PowerShell as Administrator and run:

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

Or download the [Hermes Desktop installer](https://hermes-agent.nousresearch.com/) for a GUI setup.

**Step 2 — Clone the plugin**

Open PowerShell (as your normal user):

```powershell
mkdir -p $env:USERPROFILE\.hermes\plugins
cd $env:USERPROFILE\.hermes\plugins
git clone https://github.com/sbrejnev988-coder/hermes-omnicouncil.git hermes-omnicouncil
```

Or download the ZIP from GitHub and extract into `%USERPROFILE%\.hermes\plugins\hermes-omnicouncil\`.

**Step 3 — Enable in Hermes config**

Edit `%USERPROFILE%\.hermes\config.yaml` (create if it doesn't exist):

```yaml
plugins:
  enabled:
    - hermes-omnicouncil
```

**Step 4 — Restart Hermes**

If using Hermes Desktop: close and reopen the app.

If using CLI:

```powershell
hermes gateway restart
```

**Step 5 — Verify**

In a Hermes conversation, the following tools should appear:

- `hermes_omnicouncil`
- `deep_web_crawl`
- `omnicouncil_doctor`

Or run the smoke test:

```powershell
cd $env:USERPROFILE\.hermes\plugins\hermes-omnicouncil
python -m py_compile __init__.py deep_web_research.py scripts\smoke_test.py
python scripts\smoke_test.py
```

### Linux / macOS / Android (Termux)

```bash
mkdir -p ~/.hermes/plugins
cd ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-omnicouncil.git hermes-omnicouncil
```

Add to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-omnicouncil
```

Restart:

```bash
hermes gateway restart
```

---

## Usage

### Basic Council

```
hermes_omnicouncil task="Should we use SQLite or PostgreSQL for this project?"
```

This runs a `balanced` preset: 3 councils × 4 members each, 1 collaboration round.

### Presets

| Preset | Councils | Members | Collab | Research | Use case |
|---|---|---|---:|---:|---|---|
| `fast` | 2 | 3 | 0 | No | Quick code review |
| `balanced` | 3 | 4 | 1 | No | General decisions |
| `deep` | 5 | 4 | 2 | Yes | Architecture choices |
| `audit` | 4 | 5 | 2 | Yes | Security review + red-team |
| `max` | 8 | 8 | 4 | Yes | Critical decisions |
| `ultra` | 8 | 8 | 6 | Yes | Research-grade, 400 tool requests |

### Auto-Debate (VerifyChain)

One flag activates full adversarial debate with prosecutor:

```
hermes_omnicouncil task="..." auto_debate=true model_preset=deepseek
```

This enables: blackboard, brokered tools, forced dissent (min 3 objections), prosecutor round, judge compiler, and self-review. The result includes a `verify_chain_report` with supported/unsupported claims, blocking objections, and brokered tool stats.

### Model Routing

| Preset | Default Model |
|---|---|
| `deepseek` (default) | `deepseek-v4-pro` for members + judge + research |
| `gpt55` | `gpt-5.5` for everything |
| `mixed` | `deepseek-v4-pro` ×2 + `gpt-5.5` ×2 members, `gpt-5.5` judge |

Override individual roles with `member_models`, `judge_model`, `research_model`.

### Deep Web Crawler

```
deep_web_crawl query="RustChain anti-VM-farm fingerprinting" preset=balanced
```

Multi-engine discovery (DuckDuckGo, Wikipedia, Google News) → crawl → score by relevance/credibility → Markdown/HTML/JSON report with citations.

Management tools: `deep_web_status`, `deep_web_open_report`, `deep_web_query_sources`, `deep_web_delete_job`, `deep_web_export`, `deep_web_resume`.

### Council Health

```
omnicouncil_doctor
```

Checks council health: model routing, broker availability, memory-wiki fallback, deep_web_crawl DB.

---

## Safe Tool Policy

Agents request tools via `TOOL_REQUESTS_JSON`. The orchestrator executes only these **read-only** tools:

- `memory_wiki_query`, `memory_wiki_pack_context`
- `read_file`, `search_files`
- `web_search`, `web_extract`, `web_research_brief`
- `skill_view`, `skills_list`

Mutating tools (`patch`, `write_file`, `terminal`, `process`, `cronjob`) are **hard-filtered** — agents can request them, orchestrator refuses.

---

## Environment Variables

OmniCouncil inherits the active Hermes provider configuration. No additional env vars required.

Optional overrides for standalone/smoke testing:

| Variable | Default | Description |
|---|---|---|
| `EVEY_LITELLM_URL` | `http://127.0.0.1:18089/v1` | LLM endpoint for model calls |
| `EVEY_LITELLM_KEY` | `noop` | API key for LLM endpoint |
| `OMNICOUNCIL_CACHE_TTL` | `3600` | Cache TTL in seconds |

---

## Repository Structure

```
hermes-omnicouncil/
├── __init__.py              # Main plugin — councils, blackboard, broker, judge
├── deep_web_research.py     # Deep web crawler — discovery, crawl, report
├── plugin.yaml              # Hermes plugin manifest — 13 tools
├── README.md                # This file
├── LICENSE                  # CC0-1.0
├── .gitignore
└── scripts/
    └── smoke_test.py        # Import/registration/routing smoke test
```

---

## Testing

```bash
cd ~/.hermes/plugins/hermes-omnicouncil
python3 -m py_compile __init__.py deep_web_research.py scripts/smoke_test.py
python3 scripts/smoke_test.py
```

Expected output:

```
hermes-omnicouncil 5.3.2 smoke ok
```

---

## Full Parameter Reference

### `hermes_omnicouncil`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task` | string | required | Question or task for the council |
| `context` | string | "" | Additional context |
| `mode` | enum | "advise" | advise, edit_plan, review, debug |
| `preset` | enum | "balanced" | fast, balanced, deep, audit, max, omni_blackboard, ultra |
| `model_preset` | enum | "deepseek" | deepseek, gpt55, mixed |
| `member_models` | list | — | Override member models |
| `judge_model` | string | — | Override judge model |
| `councils` | int | preset | Number of councils |
| `members_per_council` | int | preset | Members per council |
| `collaboration_rounds` | int | preset | Inter-agent collaboration rounds |
| `message_rounds` | int | 0 | Agent-to-agent message rounds |
| `auto_debate` | bool | false | Enable Auto-Debate/VerifyChain |
| `prosecutor_round` | bool | false | Run adversarial prosecutor |
| `compiler_judge` | bool | false | Judge emits JUDGE_COMPILED_JSON |
| `dissent_required` | bool | false | Force dissent listing |
| `minimum_objections` | int | 2 | Min objections when dissent_required |
| `return_blackboard` | bool | false | Return full blackboard |
| `return_evidence` | bool | false | Return evidence ledger |
| `save_task_capsule` | bool | false | Save to memory-wiki |
| `dry_run` | bool | false | Budget estimate only, no model calls |

---

## Troubleshooting

**"tool_invoker_unavailable" error?**

The broker couldn't dispatch a safe tool request. Verify:
- Hermes gateway is running
- `memory-wiki` plugin is enabled (if using `memory_wiki_query`)
- The tool being requested is in the allowlist

**Council returns empty or partial results?**

- Check model availability — all models must be reachable
- Reduce preset size (`fast` or `balanced`)
- Verify provider configuration in `config.yaml`

**Plugin not loading?**

```bash
python3 -m py_compile ~/.hermes/plugins/hermes-omnicouncil/__init__.py
# Fix any syntax errors, then:
hermes gateway restart
```

**Windows: tools not appearing after restart?**

- Confirm the plugin directory is exactly `%USERPROFILE%\.hermes\plugins\hermes-omnicouncil`
- Check `config.yaml` has `hermes-omnicouncil` under `plugins.enabled`
- Close and reopen Hermes Desktop completely (not just minimize)

---

## Version History

| Version | Date | Changes |
|---|---|---|
| **5.3.2** | 2026-06 | Auto-debate broker, real decision_policy, weak request filtering, recursive JSON schema validation, memory-wiki direct import fallback |
| 5.3.1 | 2026-06 | Brokered tool fix (tool_invoker_unavailable), registry dispatch, local fallbacks, memory-wiki provider bridge, auto_debate/verify_chain flags |
| 5.3.0 | 2026-06 | Evidence ledger, Plan→Probe→Decide, prosecutor audit, forced dissent, judge compiler, deep_web_crawl management |
| 5.2.0 | 2026-05 | Shared blackboard, message rounds, multi-model routing, deep web crawler |
| 5.0.0 | 2026-05 | Initial release — multi-model council with safe tools |

---

## License

CC0-1.0 — Public Domain Dedication. No attribution required.
