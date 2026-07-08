# Hermes OmniCouncil v5.5.0

**Multi-model agentic council for Hermes Agent — assemble councils from ANY AI models.**

OmniCouncil runs structured multi-model debates: models from different providers (OpenRouter, Anthropic, OpenAI, DeepSeek, local/GGUF, custom endpoints) collaborate via a shared blackboard, propose evidence-backed claims, and reach high-quality decisions through adversarial peer review.

## Why OmniCouncil?

| Feature | OmniCouncil | Single-model chat |
|---|---|---|
| **Adversarial review** | Prosecutor challenges every claim | No self-critique |
| **Evidence ledger** | Every claim tracked with sources | No traceability |
| **Multi-provider** | Mix Claude + GPT + DeepSeek + local | One model |
| **Council-safe** | Models can only READ + propose; mutations require operator | Models can write directly |
| **Structured output** | Compiler-Judge synthesizes canonical JSON | Unstructured text |
| **Two-layer blackboard** | Ephemeral + Durable (Memory Wiki) | No persistent audit trail |

## Quick Start

### 1. Install

```bash
cp -r hermes-omnicouncil ~/.hermes/plugins/
```

### 2. Configure Hermes

Add to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-memory-wiki
    - hermes-omnicouncil

  entries:
    hermes-omnicouncil:
      llm:
        allow_provider_override: true
        allowed_providers:
          - "*"
        allow_model_override: true
        allowed_models:
          - "*"
        allow_agent_id_override: false
        allow_profile_override: false
```

### 3. Restart Hermes

```bash
hermes restart
```

### 4. Use

```
/hermes_omnicouncil task="Review the security of this codebase" member_models=["openrouter:anthropic/claude-sonnet-4", "openrouter:openai/gpt-5.5"] judge_model="openrouter:anthropic/claude-opus-4.8"
```

Or from code:

```json
{
  "task": "Audit the authentication module for vulnerabilities",
  "member_models": [
    "openrouter:anthropic/claude-sonnet-4",
    "openrouter:openai/gpt-5.5",
    "custom:deepseekproxy:deepseek-v4-pro"
  ],
  "judge_model": "openrouter:anthropic/claude-opus-4.8",
  "tool_mode": "council_safe",
  "critical_change_policy": "operator_only",
  "preset": "deep"
}
```

## Architecture

### Council Flow

```
User Task
    │
    ▼
Plan→Probe→Decide (preflight)
    │
    ▼
┌─ Primary Members ──────────────────────┐
│  Claude Opus    GPT-5.5    DeepSeek    │  ← ANY models, ANY providers
│      │             │          │        │
│      └──────┬──────┴──────────┘        │
│             ▼                          │
│      Ephemeral Blackboard              │
│      (notes, claims, evidence,         │
│       risks, proposed_patches)         │
└────────────────────────────────────────┘
    │
    ▼
Collaboration Rounds (models debate each other)
    │
    ▼
Message Rounds (direct peer messages)
    │
    ▼
Prosecutor Round (adversarial challenge)
    │
    ▼
Judge Compiler → Structured Synthesis
```

### Security Model

Models operate in **council-safe** mode:

**Allowed (20 tools):**
- Memory Wiki read: `query`, `pack_context`, `get_project_context`, `graph_query`, `why_believe`, `recent_changes`, `health`, `get_page`
- Memory Wiki write (blackboard namespace): `write_firewall`, `add_claim`, `add_evidence`, `add_decision`, `add_task_capsule`, `post_task`
- File read: `read_file`, `search_files`
- Web: `web_search`, `web_extract`
- Skills: `skills_list`, `skill_view`

**Denied (12 tools):** `write_file`, `edit_file`, `apply_patch`, `terminal`, `shell`, `run_command`, `delete_file`, `move_file`, `rename_file`, `git_commit`, `git_push`, `patch`

**Mutation Policy:**
| Mode | Behavior |
|---|---|
| `propose_only` | Models propose patches, cannot apply |
| `judge_approved` | Judge approves, executor requires user approval |
| `operator_only` | Only Hermes operator executes mutations (default) |

All tool requests go through a single `broker_tool_call()` entry point. Memory Wiki writes are force-namespaced to `omnicouncil:blackboard:{session_id}`.

### Two-Layer Blackboard

**Ephemeral** (in-session only):
```python
blackboard = {
    "session_id": "...",
    "task": "...",
    "notes": [], "claims": [], "evidence": [],
    "file_reads": [], "memory_reads": [],
    "proposed_patches": [], "risks": [], "decisions": []
}
```

**Durable** (via Memory Wiki):
- Namespace: `omnicouncil:blackboard:{session_id}`
- Pipeline: `write_firewall` → `add_claim` / `add_evidence` / `add_decision`
- Full audit trail, redaction, journal

### Multi-Provider Routing

Any model from any configured Hermes provider via `provider:model` syntax:

```
openrouter:anthropic/claude-sonnet-4     → OpenRouter → Anthropic Claude
openrouter:openai/gpt-5.5              → OpenRouter → OpenAI GPT
custom:deepseekproxy:deepseek-v4-pro   → Custom DeepSeek proxy
mythos-nano-i1-IQ3_XS                  → Local llama.cpp (active provider)
```

Primary routing through `ctx.llm.complete(provider=..., model=...)`. HTTP fallback only for standalone/smoke tests.

Default model overridable via env: `export OMNICOUNCIL_DEFAULT_MODEL="gpt-5.5"`

### Presets (Sizing Only)

Presets control member count and rounds — models come from your arguments:

| Preset | Members | Rounds | Use Case |
|---|---|---|---|
| `fast` | 3 | 1 | Quick questions |
| `balanced` | 5 | 2 | Daily reviews |
| `deep` | 8 | 3 | Architecture decisions |
| `audit` | 4 | 2 | Security audits |
| `max` | 8 | 4 | Critical systems |
| `omni_blackboard` | 6 | 3 | Research |
| `ultra` | 12 | 5 | Maximum coverage |

## Tools Provided

| Tool | Description |
|---|---|
| `hermes_omnicouncil` | Main council orchestration |
| `omnicouncil_doctor` | Health check & diagnostics |
| `omnicouncil_cache_*` | Cache management (list/get/clear/explain) |
| `deep_web_crawl` | Professional research crawler |
| `deep_web_status` | Crawl job status |
| `deep_web_*` | Research report management |

## Requirements

- **Hermes Agent** with wildcard provider/model allowlists (see config above)
- Python 3.11+ (stdlib only — zero external dependencies for core council)
- Configured providers: OpenRouter, Anthropic, OpenAI, DeepSeek, or any OpenAI-compatible endpoint

## Environment

```bash
# Optional: override default model
export OMNICOUNCIL_DEFAULT_MODEL="gpt-5.5"
```

## License

MIT — see [LICENSE](LICENSE)

---

Built for [Hermes Agent](https://hermes-agent.nousresearch.com) by Maxim (@sbrejnev988-coder)
