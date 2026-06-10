# Hermes OmniCouncil v5.1.1

Multi-model agentic council plugin for Hermes Agent: shared blackboard, message rounds, safe read-only tool brokering, swappable model presets, and a companion `deep_web_crawl` research crawler.

## What it gives you

- **Agentic blackboard** — agents share facts, assumptions, objections, open questions, and verification notes.
- **Message rounds** — directed agent-to-agent messages: questions, challenges, clarifications, evidence shares.
- **Multi-model routing** — presets for `deepseek`, `gpt55`, and `mixed`; explicit `member_models`, `judge_model`, and `research_model` overrides.
- **DeepSeek-first default** — `model_preset=deepseek` and `deepseek-v4-pro` by default, matching local Hermes DeepSeek proxy deployments.
- **Safe brokered tools** — agents may request read-only tools; the orchestrator executes only allowlisted tools and injects bounded/redacted previews.
- **Research mode** — optional research subagents plus `web_research_brief` and standalone `deep_web_crawl`.
- **Judge controls** — `decision_policy`, `red_team`, `dissent_required`, `anti_slop`, and optional `self_review_round`.
- **Large-context defaults** — 384k output-token ceilings for member and judge calls when the provider supports it.

## Repository contents

| Path | Purpose |
|---|---|
| `__init__.py` | Main Hermes tool plugin: schema, model routing, blackboard orchestration, brokered safe tools, judge synthesis. |
| `deep_web_research.py` | Companion `deep_web_crawl` tool: multi-engine discovery, crawling, SQLite source DB, Markdown/HTML/JSON reports. |
| `plugin.yaml` | Hermes plugin manifest exposing `hermes_omnicouncil` and `deep_web_crawl`. |
| `scripts/smoke_test.py` | Import/registration/model-routing/tool-request smoke test with fake model calls. |

## Installation

Clone directly into a Hermes profile plugin directory:

```bash
mkdir -p ~/.hermes/plugins
git clone https://github.com/sbrejnev988-coder/hermes-omnicouncil.git ~/.hermes/plugins/hermes-omnicouncil
```

Enable the plugin in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-omnicouncil
  disabled:
    - gpt55-consilium   # optional: old plugin name, keep disabled if present
```

Restart Hermes after installing or updating the plugin so the tool registry reloads.

## Model routing

Default behavior is DeepSeek-first:

| Preset | Members | Judge | Research |
|---|---|---|---|
| `deepseek` *(default)* | `deepseek-v4-pro` | `deepseek-v4-pro` | `deepseek-v4-pro` |
| `gpt55` | `gpt-5.5` | `gpt-5.5` | `gpt-5.5` |
| `mixed` | `deepseek-v4-pro`, `gpt-5.5`, `deepseek-v4-pro`, `gpt-5.5` | `gpt-5.5` | `deepseek-v4-pro` |

Override only when the active delegate endpoint supports the model you request.

```json
{
  "task": "Design a resilient cache invalidation plan",
  "model_preset": "mixed",
  "member_models": ["deepseek-v4-pro", "gpt-5.5", "deepseek-v4-pro", "gpt-5.5"],
  "judge_model": "gpt-5.5",
  "research_model": "deepseek-v4-pro"
}
```

Outside a full Hermes plugin tree, `__init__.py` includes a small OpenAI-compatible fallback model caller. It reads:

- `EVEY_LITELLM_URL` / `HERMES_DELEGATE_BASE_URL` / `CODEX_BASE_URL`
- `EVEY_LITELLM_KEY` / `HERMES_DELEGATE_API_KEY` / `CODEX_API_KEY`

Hermes installs normally use the shared `plugins/evey_utils.py` helper instead.

## Council presets

| Preset | Councils | Members/council | Collaboration rounds | Message rounds | Research | Notes |
|---|---:|---:|---:|---:|---|---|
| `fast` | 2 | 3 | 0 | 0 | No | Cheap quick review. |
| `balanced` | 3 | 4 | 1 | 0 | No | Default balanced review. |
| `deep` | 5 | 4 | 2 | 1 | Yes | Thorough analysis. |
| `audit` | 4 | 5 | 2 | 1 | Yes | Adds red-team pressure. |
| `max` | 8 | 8 | 4 | 2 | Yes | Large council. |
| `omni_blackboard` | 5 | 4 | 4 | 2 | Yes | Main blackboard preset. |
| `ultra` | 8 | 8 | 6 | 3 | Yes | Up to 400 brokered read-only tool requests. |

## Basic calls

### Default blackboard council

```json
{
  "task": "Review this plugin architecture and propose concrete patches",
  "context": "Relevant code excerpts or links here",
  "preset": "omni_blackboard",
  "output_format": "structured"
}
```

### Patch-plan style output

```json
{
  "task": "Find small stability fixes for this Hermes plugin",
  "context": "...",
  "preset": "omni_blackboard",
  "output_format": "patch_plan",
  "dissent_required": true,
  "anti_slop": true,
  "self_review_round": true
}
```

### Disable brokered tool execution

```json
{
  "task": "Pure reasoning review, no tool execution",
  "preset": "omni_blackboard",
  "tool_mode": "off"
}
```

## Safe tool broker

Agents can request read-only tools through `TOOL_REQUESTS_JSON`. The orchestrator deduplicates requests, blocks mutating tools, executes allowlisted tools, and attaches bounded/redacted previews.

Allowed tools:

- `memory_wiki_query`
- `memory_wiki_pack_context`
- `read_file`
- `search_files`
- `web_search`
- `web_extract`
- `web_research_brief`
- `skill_view`
- `skills_list`

Blocked tools:

- `patch`
- `write_file`
- `terminal`
- `process`
- `cronjob`

Request shape:

```json
[
  {
    "tool": "search_files",
    "args": {"path": "/project", "pattern": "def handler", "target": "content"},
    "reason": "Find the plugin handler implementation before recommending a patch.",
    "priority": 5,
    "expected_information_gain": "Confirms whether schema and dispatch are in parity.",
    "mutating": false,
    "requires_lock": []
  }
]
```

`minimum_tools=true` annotates weak requests as `weak_request=true` when a request lacks both `reason` and `expected_information_gain`.

## `deep_web_crawl`

The companion tool performs keyless discovery/crawling and exports research reports.

```json
{
  "query": "Latest open source agent memory systems",
  "preset": "balanced",
  "search_engines": ["duckduckgo", "bing", "wikipedia"],
  "export_formats": ["markdown", "html", "json"],
  "max_pages": 40
}
```

## Verification

Run from the repository root:

```bash
python3 -m py_compile __init__.py deep_web_research.py scripts/smoke_test.py
python3 scripts/smoke_test.py
```

Expected smoke output:

```text
hermes-omnicouncil v5.1.1 smoke ok: tools=2 calls=13 member_models=4 messages_rounds=1
```

## Migration from `gpt55-consilium`

Old:

```json
{ "tool": "gpt55_consilium", "task": "...", "preset": "max_agentic_blackboard" }
```

New:

```json
{ "tool": "hermes_omnicouncil", "task": "...", "preset": "omni_blackboard" }
```

Key changes:

- `gpt55_consilium` → `hermes_omnicouncil`
- `max_agentic_blackboard` → `omni_blackboard`
- DeepSeek is now the default model preset for local proxy compatibility.
- Added `member_models`, `judge_model`, `research_model`.
- Added message rounds and blackboard summaries.
- Tool requests are brokered read-only with bounded/redacted result previews.
- Added `dissent_required`, `anti_slop`, and optional `self_review_round`.

## Version

`5.1.1-omni-blackboard-deepseek-default`
