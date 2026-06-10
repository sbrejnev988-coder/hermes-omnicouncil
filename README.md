# Hermes OmniCouncil v4

Multi-model agentic council plugin for Hermes Agent with shared blackboard, message rounds, safe memory/web/file tools, and professional deep web research.

## Features

- **Multi-model**: run councils with different models per agent (`deepseek-v4-pro`, `gpt-5.5`, mixed)
- **Shared blackboard**: agents publish facts, questions, and objections on a common board
- **Message rounds**: agents exchange directed messages (questions, challenges, clarifications)
- **Safe agent tools**: read-only access to `memory_wiki_*`, `read_file`, `search_files`, `web_search`, `web_extract`
- **No patch/write/terminal** for agents — read-only safety by design
- **web_research_brief**: composite search→extract→summarise tool
- **deep_web_crawl**: multi-engine crawler with SQLite source DB, HTTP cache, Markdown/HTML reports
- **Model presets**: `deepseek`, `gpt55`, `mixed`
- **Preset modes**: `fast`, `balanced`, `deep`, `audit`, `max`, `omni_blackboard`
- Judge synthesis with evidence ledger and decision policies

## Installation

```bash
cp -r hermes-omnicouncil ~/.hermes/plugins/
```

Enable in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-omnicouncil
  disabled:
    - gpt55-consilium   # old name, keep disabled
```

Restart Hermes.

## Usage

### Basic call

```json
{
  "task": "Analyze the security of this authentication flow",
  "context": "...",
  "preset": "omni_blackboard"
}
```

### Model switching

```json
{
  "task": "Design a caching strategy",
  "model_preset": "mixed",
  "member_models": ["deepseek-v4-pro", "gpt-5.5", "deepseek-v4-pro", "gpt-5.5"],
  "judge_model": "gpt-5.5"
}
```

### Available model presets

| Preset | Members | Judge | Research |
|--------|---------|-------|----------|
| `deepseek` | deepseek-v4-pro | deepseek-v4-pro | deepseek-v4-pro |
| `gpt55` | gpt-5.5 | gpt-5.5 | gpt-5.5 |
| `mixed` | deepseek-v4-pro, gpt-5.5 (×2 each) | gpt-5.5 | deepseek-v4-pro |

### Available omnicouncil presets

| Preset | Councils | Members/council | Collab rounds | Message rounds | Research |
|--------|----------|-----------------|---------------|----------------|----------|
| `fast` | 2 | 3 | 0 | 0 | No |
| `balanced` | 3 | 4 | 1 | 0 | No |
| `deep` | 5 | 4 | 2 | 1 | Yes |
| `audit` | 4 | 5 | 2 | 1 | Yes |
| `max` | 8 | 8 | 4 | 2 | Yes |
| `omni_blackboard` | 5 | 4 | 4 | 2 | Yes |

### deep_web_crawl

```json
{
  "query": "Latest developments in quantum computing",
  "preset": "deep",
  "search_engines": ["duckduckgo", "bing", "wikipedia"],
  "export_formats": ["markdown", "html"]
}
```

## Agent tools (safe)

Agents have access to:
- `memory_wiki_query` — search durable memory
- `memory_wiki_pack_context` — pack relevant memory context
- `read_file` — read project files
- `search_files` — search file contents
- `web_search` — search the web
- `web_extract` — extract page content
- `skills_list` / `skill_view` — browse skill library

Blocked for agents: `patch`, `write_file`, `terminal`, `process`, `cronjob`.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Main omnicouncil orchestration (1785 lines) |
| `deep_web_research.py` | Deep web crawler & research reports |
| `plugin.yaml` | Hermes plugin manifest |
| `scripts/smoke_test.py` | Stability smoke tests |

## Migration from gpt55-consilium

Old calls:
```json
{ "tool": "gpt55_consilium", "task": "...", "preset": "max_agentic_blackboard" }
```

New calls:
```json
{ "tool": "hermes_omnicouncil", "task": "...", "preset": "omni_blackboard" }
```

Key differences:
- `max_agentic_blackboard` → `omni_blackboard`
- `gpt55_consilium` → `hermes_omnicouncil`
- Added `model_preset` / `member_models` / `judge_model`
- Added `message_rounds` parameter
- Agent tools are now real safe tools, not pseudo-requests
- Blackboard includes message exchange infrastructure

## Requirements

- Hermes Agent with plugin support
- Access to model APIs via Hermes providers (deepseekproxy, OpenAI-compatible proxy)
- Python 3.11+ (stdlib only, no external dependencies)

## Version

4.0.0-omni-blackboard
