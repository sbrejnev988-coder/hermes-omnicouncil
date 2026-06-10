"""hermes-omnicouncil v4.0 — multi-model agentic council with blackboard + message rounds.

Features:
- Swappable models (model/member_models/judge_model/model_preset)
- Shared blackboard with message rounds for inter-agent communication
- Safe agent tools: memory (query/pack), file read/search, web_search, web_extract, web_research_brief
- NO patch/write significant tools for agents (read-only safety)
- Presets (fast/balanced/deep/audit/max/omni_blackboard)
- Evidence ledger, tool-request protocol, collaboration rounds, judge synthesis
- deep_web_crawl for professional research reports
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util as _iu
import json
import logging
import os as _os
import random
import re
import time
from pathlib import Path
from typing import Any

_spec = _iu.spec_from_file_location(
    "evey_utils",
    _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "evey_utils.py"),
)
_eu = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_eu)
call_model = _eu.call_model

logger = logging.getLogger("hermes.omnicouncil")
_RUNTIME_CTX: Any = None

# ── deep_web_research (copied/imported companion tool) ──────────────────
_deep_spec = _iu.spec_from_file_location(
    "omnicouncil_deep_web_research",
    _os.path.join(_os.path.dirname(__file__), "deep_web_research.py"),
)
_deep_web_research = _iu.module_from_spec(_deep_spec)
_deep_spec.loader.exec_module(_deep_web_research)

# ═══════════════════════════════════════════════════════════════════════
#  Configurable model defaults
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_MODEL = "deepseek-v4-pro"
REASONING_EFFORT = "xhigh"
VERSION = "4.0.0-omni-blackboard"

MODEL_PRESETS = {
    "deepseek": {
        "member_models": ["deepseek-v4-pro"],
        "judge_model": "deepseek-v4-pro",
        "research_model": "deepseek-v4-pro",
    },
    "gpt55": {
        "member_models": ["gpt-5.5"],
        "judge_model": "gpt-5.5",
        "research_model": "gpt-5.5",
    },
    "mixed": {
        "member_models": ["deepseek-v4-pro", "gpt-5.5", "deepseek-v4-pro", "gpt-5.5"],
        "judge_model": "gpt-5.5",
        "research_model": "deepseek-v4-pro",
    },
}

# ═══════════════════════════════════════════════════════════════════════
#  Scalars
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_COUNCILS = 5
DEFAULT_MEMBERS_PER_COUNCIL = 4
MAX_COUNCILS = 8
MAX_MEMBERS_PER_COUNCIL = 8
DEFAULT_MAX_TOKENS = 128000
DEFAULT_JUDGE_MAX_TOKENS = 128000
DEFAULT_COLLABORATION_ROUNDS = 2
DEFAULT_MESSAGE_ROUNDS = 1
DEFAULT_MEMBER_RETRIES = 1
DEFAULT_MODEL_TIMEOUT = 900
DEFAULT_JUDGE_TIMEOUT = 1200
CACHE_DIR = Path.home() / ".hermes" / "cache" / "hermes-omnicouncil"
CACHE_TTL = 24 * 60 * 60
MAX_PROMPT_CONTEXT_CHARS = 1_000_000
MAX_CONTEXT_CHARS = 1_000_000
MAX_MANIFEST_CHARS = 120_000
MAX_SKILL_INDEX_CHARS = 80_000
MAX_PLUGIN_INDEX_CHARS = 60_000
MAX_MCP_INDEX_CHARS = 40_000
MAX_EVIDENCE_CHARS = 80_000
MAX_INITIAL_ANSWER_CHARS_FOR_COLLAB = 24_000
MAX_PREVIOUS_ROUND_CHARS_FOR_COLLAB = 8_000
MAX_INITIAL_ANSWER_CHARS_FOR_JUDGE = 24_000
MAX_DISCUSSION_CHARS_FOR_JUDGE = 6_000
MAX_RESEARCH_REPORT_CHARS_FOR_JUDGE = 16_000
MAX_MESSAGE_CHARS = 4_000
MAX_MESSAGE_HISTORY_CHARS = 16_000
MAX_TOOL_REQUESTS_DEFAULT = 20
MAX_AGENTIC_TOOL_REQUESTS = 200
AGENTIC_ACTIVE_TOOL_AGENTS = 4
AGENTIC_MUTATING_AGENTS = 0
DEFAULT_MEMORY_CONTEXT_CHARS = 12_000
MAX_MEMORY_CONTEXT_CHARS = 30_000
DEFAULT_MAX_MEMBER_WORKERS = 8
DEFAULT_MAX_COLLABORATION_WORKERS = 6
DEFAULT_MAX_RESEARCH_WORKERS = 4
DEFAULT_MIN_SUCCESSFUL_MEMBERS = 1
DEFAULT_REQUEST_JITTER_MS = 5500
MAX_REQUEST_JITTER_MS = 30_000

# ═══════════════════════════════════════════════════════════════════════
#  Safe agent tools — read-only, no patch/write/terminal
# ═══════════════════════════════════════════════════════════════════════
SAFE_AGENT_TOOLS = [
    "memory_wiki_query",
    "memory_wiki_pack_context",
    "read_file",
    "search_files",
    "web_search",
    "web_extract",
    "skill_view",
    "skills_list",
]

SAFE_AGENT_TOOLSET_NAMES = ["memory", "file_read", "web", "skills_read"]

PERSPECTIVES = [
    "Архитектор: найди самый простой и устойчивый дизайн решения.",
    "Имплементатор: думай о конкретных правках, командах, тестах и edge cases.",
    "Ревьюер/безопасник: ищи риски, регрессии, секреты, опасные действия и ложные допущения.",
    "Оптимизатор: сократи путь, устрани лишнее, предложи быстрые проверки и rollback.",
    "SRE/Надёжность: думай о таймаутах, retries, деградации, observability и стабильности связи.",
    "Memory/Knowledge curator: думай о durable memory, task capsules, evidence, дедупликации и будущей воспроизводимости.",
    "UX/Оператор: сделай результат удобным для следующего действия пользователя и минимизируй ручные шаги.",
    "QA/Тестировщик: формулируй acceptance criteria, regression tests, negative tests и smoke сценарии.",
    "Исследователь: используй web_search, web_extract, read_file для фактов; собирай веб-данные через web_research_brief.",
]

OMNI_BLACKBOARD_ROLES = [
    "planner: строит план, декомпозирует задачу, определяет stop conditions; tools=memory/file_read/web/skills_read; mutating=false.",
    "researcher_1: ищет факты через web_search + web_extract + memory_wiki_query; tools=memory_read/web/file_read; mutating=false.",
    "researcher_2: ищет альтернативные подходы и tradeoffs; tools=memory_read/web/file_read; mutating=false.",
    "architect: проектирует решение, опираясь на факты и memory; tools=memory_read/file_read/web; mutating=false.",
    "reviewer_1: проверяет корректность, архитектуру, regression risks; tools=file_read/search; mutating=false.",
    "reviewer_2: ищет edge cases, hidden constraints, ложные допущения; tools=file_read/search; mutating=false.",
    "red_team: ломает план, ищет контрпримеры, falsification tests; tools=file_read/search; mutating=false.",
    "qa_tester: формулирует acceptance criteria и тест-план; tools=file_read/search; mutating=false.",
    "judge: синтезирует финальное решение, взвешивает evidence/dissent; tools=normally_none; mutating=false.",
]

OMNI_BLACKBOARD_ROUNDS = [
    "Round 0: Orchestrator формулирует задачу и общий blackboard.",
    "Round 1: независимые первичные мнения с использованием safe tools.",
    "Round 2: peer collaboration — агенты видят находки коллег и спорят через blackboard.",
    "Round 3: message rounds — агенты обмениваются вопросами и ответами.",
    "Round 4: red-team critique ломает решение.",
    "Round 5: judge synthesis с учётом всех evidence и messages.",
    "Round 6: финальный отчёт.",
]

CONSILIUM_PRESETS = {
    "auto": {"councils": None, "members_per_council": None, "collaboration_rounds": None, "message_rounds": 0, "research_missions": None},
    "fast": {"councils": 2, "members_per_council": 3, "collaboration_rounds": 0, "message_rounds": 0, "research_missions": False},
    "balanced": {"councils": 3, "members_per_council": 4, "collaboration_rounds": 1, "message_rounds": 0, "research_missions": False},
    "deep": {"councils": 5, "members_per_council": 4, "collaboration_rounds": 2, "message_rounds": 1, "research_missions": True},
    "audit": {"councils": 4, "members_per_council": 5, "collaboration_rounds": 2, "message_rounds": 1, "research_missions": True, "red_team": True},
    "max": {"councils": MAX_COUNCILS, "members_per_council": MAX_MEMBERS_PER_COUNCIL, "collaboration_rounds": 4, "message_rounds": 2, "research_missions": True, "red_team": True},
    "omni_blackboard": {
        "councils": 5,
        "members_per_council": 4,
        "collaboration_rounds": 4,
        "message_rounds": 2,
        "research_missions": True,
        "red_team": True,
        "tool_mode": "safe_agent",
        "capability_profile": "omni",
        "max_research_agents": AGENTIC_ACTIVE_TOOL_AGENTS,
        "max_member_workers": DEFAULT_MAX_MEMBER_WORKERS,
        "max_research_workers": DEFAULT_MAX_RESEARCH_WORKERS,
        "max_collaboration_workers": DEFAULT_MAX_COLLABORATION_WORKERS,
        "max_tool_requests": MAX_AGENTIC_TOOL_REQUESTS,
        "agentic_blackboard": True,
        "minimum_tools": True,
        "brokered_tools": True,
        "active_tool_agents": AGENTIC_ACTIVE_TOOL_AGENTS,
        "mutating_agents": AGENTIC_MUTATING_AGENTS,
    },
}

CAPABILITY_PROFILES = {
    "minimal": ["file_read", "web"],
    "dev": ["file_read", "web", "skills_read", "memory"],
    "research": ["web", "skills_read", "memory"],
    "omni": ["memory", "file_read", "web", "skills_read", "search"],
}

STATIC_TOOLSETS = {
    "file_read": ["read_file", "search_files"],
    "web": ["web_search", "web_extract"],
    "skills_read": ["skills_list", "skill_view"],
    "memory": ["memory_wiki_query", "memory_wiki_pack_context"],
    "search": ["search_files"],
    "delegation": ["delegate_task", "cached_delegate", "hermes_omnicouncil", "council_decide"],
}

SCHEMA = {
    "name": "hermes_omnicouncil",
    "description": (
        "Hermes OmniCouncil v4: multi-model agentic council with shared blackboard, message rounds, "
        "safe memory/web/file tools, swappable models, web_research_brief, and deep_web_crawl. "
        "Agents collaborate via blackboard notes, peer review, and directed messages. "
        "judge synthesises the final result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Задача/вопрос для OmniCouncil."},
            "context": {"type": "string", "description": "Дополнительный контекст."},
            "mode": {"type": "string", "enum": ["advise", "edit_plan", "review", "debug"], "default": "edit_plan"},
            "preset": {"type": "string", "enum": list(CONSILIUM_PRESETS), "default": "deep"},
            "model": {"type": "string", "default": "", "description": "Модель по умолчанию для всех агентов (переопределяет model_preset)."},
            "model_preset": {"type": "string", "enum": list(MODEL_PRESETS), "default": "", "description": "Пресет моделей: deepseek/gpt55/mixed."},
            "member_models": {"type": "array", "items": {"type": "string"}, "default": [], "description": "Модели участников."},
            "judge_model": {"type": "string", "default": "", "description": "Модель для judge."},
            "research_model": {"type": "string", "default": "", "description": "Модель для research missions."},
            "councils": {"type": "integer", "default": DEFAULT_COUNCILS},
            "members_per_council": {"type": "integer", "default": DEFAULT_MEMBERS_PER_COUNCIL},
            "perspectives": {"type": "array", "items": {"type": "string"}, "default": []},
            "decision_policy": {"type": "string", "enum": ["judge", "majority", "consensus", "risk_weighted"], "default": "judge"},
            "red_team": {"type": "boolean", "default": False},
            "auto_scale": {"type": "boolean", "default": False},
            "max_tokens": {"type": "integer", "default": DEFAULT_MAX_TOKENS},
            "judge_max_tokens": {"type": "integer", "default": DEFAULT_JUDGE_MAX_TOKENS},
            "use_cache": {"type": "boolean", "default": True},
            "cache_ttl_seconds": {"type": "integer", "default": CACHE_TTL},
            "force_refresh": {"type": "boolean", "default": False},
            "collaborate": {"type": "boolean", "default": True},
            "collaboration_rounds": {"type": "integer", "default": DEFAULT_COLLABORATION_ROUNDS},
            "message_rounds": {"type": "integer", "default": 1, "description": "Раунды обмена сообщениями между агентами."},
            "return_transcript": {"type": "boolean", "default": False},
            "tool_mode": {
                "type": "string",
                "enum": ["off", "safe_agent"],
                "default": "safe_agent",
            },
            "capability_profile": {"type": "string", "enum": list(CAPABILITY_PROFILES), "default": "omni"},
            "auto_capability_scan": {"type": "boolean", "default": True},
            "auto_skills": {"type": "boolean", "default": True},
            "skills": {"type": "array", "items": {"type": "string"}, "default": []},
            "auto_memory_context": {"type": "boolean", "default": True},
            "memory_context_chars": {"type": "integer", "default": DEFAULT_MEMORY_CONTEXT_CHARS},
            "mcp_mode": {"type": "string", "enum": ["off", "manifest"], "default": "manifest"},
            "research_missions": {"type": "boolean", "default": False},
            "max_research_agents": {"type": "integer", "default": 3},
            "max_member_workers": {"type": "integer", "default": DEFAULT_MAX_MEMBER_WORKERS},
            "max_collaboration_workers": {"type": "integer", "default": DEFAULT_MAX_COLLABORATION_WORKERS},
            "max_research_workers": {"type": "integer", "default": DEFAULT_MAX_RESEARCH_WORKERS},
            "min_successful_members": {"type": "integer", "default": DEFAULT_MIN_SUCCESSFUL_MEMBERS},
            "enabled_toolsets": {"type": "array", "items": {"type": "string"}, "default": []},
            "max_tool_requests": {"type": "integer", "default": MAX_TOOL_REQUESTS_DEFAULT},
            "agentic_blackboard": {"type": "boolean", "default": False},
            "minimum_tools": {"type": "boolean", "default": True},
            "brokered_tools": {"type": "boolean", "default": True},
            "active_tool_agents": {"type": "integer", "default": AGENTIC_ACTIVE_TOOL_AGENTS},
            "mutating_agents": {"type": "integer", "default": AGENTIC_MUTATING_AGENTS},
            "return_blackboard": {"type": "boolean", "default": False},
            "return_evidence": {"type": "boolean", "default": True},
            "output_format": {"type": "string", "enum": ["prose", "structured", "patch_plan", "json"], "default": "structured"},
            "save_task_capsule": {"type": "boolean", "default": False},
            "member_retries": {"type": "integer", "default": DEFAULT_MEMBER_RETRIES},
            "model_timeout": {"type": "integer", "default": DEFAULT_MODEL_TIMEOUT},
            "judge_timeout": {"type": "integer", "default": DEFAULT_JUDGE_TIMEOUT},
            "request_jitter_ms": {"type": "integer", "default": DEFAULT_REQUEST_JITTER_MS},
            "strict_json": {"type": "boolean", "default": False},
        },
        "required": ["task"],
    },
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{12,})\b"),
]


# ═══════════════════════════════════════════════════════════════
#  helpers
# ═══════════════════════════════════════════════════════════════
def _redact(text: Any) -> str:
    s = str(text or "")
    for pat in SECRET_PATTERNS:
        if pat.pattern.startswith("(?i)(bearer"):
            s = pat.sub(r"\1[REDACTED]", s)
        elif "api" in pat.pattern.lower() or "password" in pat.pattern.lower():
            s = pat.sub(r"\1\2[REDACTED]", s)
        else:
            s = pat.sub("[REDACTED]", s)
    return s


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _truncate_text(text: Any, max_chars: int, suffix: str = "…[truncated]") -> str:
    text = _redact(text)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(suffix))
    return text[:keep] + suffix


def _normalise_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on", "да", "истина"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", "нет", "ложь"}:
            return False
    return default


def _bounded_context(context: str) -> str:
    return _truncate_text(context, MAX_CONTEXT_CHARS, "…[context truncated]")


def _prompt_too_large(prompt: str) -> bool:
    return len(prompt) > MAX_PROMPT_CONTEXT_CHARS


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, n))


def _request_jitter(jitter_ms: int = DEFAULT_REQUEST_JITTER_MS) -> float:
    try:
        limit_ms = max(0, min(MAX_REQUEST_JITTER_MS, int(jitter_ms or 0)))
    except Exception:
        limit_ms = DEFAULT_REQUEST_JITTER_MS
    if limit_ms <= 0:
        return 0.0
    delay = random.uniform(0.0, limit_ms / 1000.0)
    time.sleep(delay)
    return delay


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _add_evidence(ledger: list[dict[str, Any]], source: str, summary: str, **extra: Any) -> str:
    eid = f"E{len(ledger) + 1}"
    item = {"id": eid, "source": source, "summary": _truncate_text(summary, 1200)}
    for k, v in extra.items():
        item[k] = _truncate_text(v, 2000) if isinstance(v, str) else v
    ledger.append(item)
    return eid


def _read_text_safe(path: Path, max_chars: int = 8000) -> str:
    try:
        return _redact(path.read_text(encoding="utf-8", errors="replace")[:max_chars])
    except Exception:
        return ""


def _extract_yaml_field(text: str, field: str) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*[\"']?([^\n\"']+)[\"']?\s*$", text)
    return _redact(m.group(1).strip()) if m else ""


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{_os.getpid()}.{int(time.time() * 1000)}.tmp")
    tmp.write_text(_json(obj), encoding="utf-8")
    tmp.replace(path)


# ═══════════════════════════════════════════════════════════════
#  Model routing
# ═══════════════════════════════════════════════════════════════
def _resolve_models(args: dict[str, Any]) -> tuple[str, list[str], str, str]:
    preset_name = str(args.get("model_preset") or "").strip().lower()
    if preset_name in MODEL_PRESETS:
        mp = MODEL_PRESETS[preset_name]
        member_models = args.get("member_models") or mp.get("member_models", [DEFAULT_MODEL])
        judge_model = args.get("judge_model") or mp.get("judge_model", DEFAULT_MODEL)
        research_model = args.get("research_model") or mp.get("research_model", DEFAULT_MODEL)
        default_model = args.get("model") or member_models[0] if member_models else DEFAULT_MODEL
    else:
        default_model = args.get("model") or DEFAULT_MODEL
        member_models = args.get("member_models") or [default_model]
        judge_model = args.get("judge_model") or default_model
        research_model = args.get("research_model") or default_model
    member_models = [m for m in member_models if m]
    if not member_models:
        member_models = [DEFAULT_MODEL]
    return default_model, member_models, judge_model, research_model


def _call_model_text(
    prompt: str,
    max_tokens: int,
    temperature: float,
    model: str | None = None,
    timeout: int = DEFAULT_MODEL_TIMEOUT,
    retries: int = DEFAULT_MEMBER_RETRIES,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
) -> str:
    effective_model = model or DEFAULT_MODEL
    last_error: Exception | None = None
    attempts = max(1, int(retries or 0) + 1)
    for attempt in range(attempts):
        try:
            _request_jitter(jitter_ms)
            result = call_model(
                effective_model,
                _truncate_text(prompt, MAX_PROMPT_CONTEXT_CHARS, "…[prompt truncated]"),
                max_tokens=max_tokens,
                temperature=temperature,
                retries=1,
                timeout=timeout,
                reasoning_effort=REASONING_EFFORT,
            )
            if not result or not result.get("content"):
                raise RuntimeError("empty model response")
            return str(result.get("content", ""))
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            delay = min(2**attempt, 8) + min(0.25 * attempt, 0.75)
            time.sleep(delay)
    raise RuntimeError(str(last_error or "model call failed"))


def _is_retryable_error_text(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("timeout", "reset", "connection", "refused", "503", "502", "429"))


# ═══════════════════════════════════════════════════════════════
#  Safe tool execution (read-only)
# ═══════════════════════════════════════════════════════════════
def _execute_safe_tool(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    ctx = _RUNTIME_CTX
    if ctx is not None:
        for method_name in ("call_tool", "invoke_tool", "run_tool", "execute_tool"):
            method = getattr(ctx, method_name, None)
            if not callable(method):
                continue
            try:
                result = method(tool_name, tool_args)
                return _redact(str(result)) if not isinstance(result, dict) else result
            except TypeError:
                try:
                    result = method(name=tool_name, arguments=tool_args)
                    return _redact(str(result)) if not isinstance(result, dict) else result
                except TypeError:
                    try:
                        result = method({"name": tool_name, "arguments": tool_args})
                        return _redact(str(result)) if not isinstance(result, dict) else result
                    except Exception:
                        continue
                except Exception:
                    continue
            except Exception:
                continue
    return {"ok": False, "error": "tool_invoker_unavailable"}


# ═══════════════════════════════════════════════════════════════
#  Blackboard & message infrastructure
# ═══════════════════════════════════════════════════════════════
def _build_blackboard_policy(
    max_tool_requests: int,
    active_tool_agents: int,
    mutating_agents: int,
    minimum_tools: bool = True,
    brokered_tools: bool = True,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "name": "omni_blackboard",
        "roles": list(OMNI_BLACKBOARD_ROLES),
        "rounds": list(OMNI_BLACKBOARD_ROUNDS),
        "topology": {
            "parallel_primary_workers": DEFAULT_MAX_MEMBER_WORKERS,
            "active_tool_agents_target": active_tool_agents,
            "mutating_agents_target": mutating_agents,
            "all_agents_see_capabilities": True,
            "peer_collaboration_via_blackboard": True,
            "message_rounds_enabled": True,
            "judge_synthesizes": True,
        },
        "tool_policy": {
            "enabled": brokered_tools,
            "safe_tools_only": True,
            "allowed_tools": SAFE_AGENT_TOOLS,
            "denied_tools": ["patch", "write_file", "terminal", "process", "cronjob"],
            "max_tool_requests_cap": max_tool_requests,
            "minimum_tools": minimum_tools,
        },
        "message_policy": {
            "enabled": True,
            "max_chars": MAX_MESSAGE_CHARS,
            "history_chars": MAX_MESSAGE_HISTORY_CHARS,
            "allowed_types": ["question", "answer", "challenge", "clarification", "evidence_share"],
        },
        "minimum_tools_policy": {
            "enabled": minimum_tools,
            "primary_rule": "reasoning + blackboard first, tool request only for concrete information gain",
        },
    }


def _blackboard_text(manifest: dict[str, Any]) -> str:
    policy = manifest.get("blackboard") or {}
    if not policy:
        return ""
    return _truncate_text(_json(policy), 60_000, "…[blackboard policy truncated]")


def _messages_text(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    return _truncate_text(_json(messages), MAX_MESSAGE_HISTORY_CHARS)


# ═══════════════════════════════════════════════════════════════
#  capability manifest
# ═══════════════════════════════════════════════════════════════
def _scan_plugins(ledger: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    root = Path.home() / ".hermes" / "plugins"
    plugins: list[dict[str, Any]] = []
    if root.exists():
        for yaml_path in sorted(root.glob("*/plugin.yaml"))[:limit]:
            text = _read_text_safe(yaml_path, 6000)
            name = _extract_yaml_field(text, "name") or yaml_path.parent.name
            version = _extract_yaml_field(text, "version")
            description = _extract_yaml_field(text, "description")
            tools = re.findall(r"(?m)^\s*-\s*([A-Za-z0-9_\-]+)\s*$", text)
            plugins.append({"name": name, "version": version, "description": description, "tools": tools, "path": str(yaml_path)})
    _add_evidence(ledger, "plugin_scan", f"Scanned {len(plugins)} Hermes plugin manifests.", count=len(plugins))
    return plugins


def _scan_skills(ledger: list[dict[str, Any]], selected: list[str] | None = None, limit: int = 260) -> list[dict[str, Any]]:
    root = Path.home() / ".hermes" / "skills"
    skills: list[dict[str, Any]] = []
    if root.exists():
        for skill_path in sorted(root.glob("**/SKILL.md")):
            text = _read_text_safe(skill_path, 10000)
            desc = _extract_yaml_field(text, "description")
            rel_parts = skill_path.relative_to(root).parts
            name = rel_parts[-2] if len(rel_parts) >= 2 else skill_path.parent.name
            if not desc:
                lines = [ln.strip("# ").strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("---")]
                desc = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
            skills.append({"name": name, "description": _truncate_text(desc, 500), "path": str(skill_path)})
            if len(skills) >= limit:
                break
    _add_evidence(ledger, "skill_scan", f"Indexed {len(skills)} Hermes skills.", count=len(skills))
    return skills


def _scan_mcp(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [Path.home() / ".hermes" / "config.yaml", Path("/root/.hermes/config.yaml")]
    found: list[dict[str, Any]] = []
    for cfg in candidates:
        if not cfg.exists():
            continue
        text = _read_text_safe(cfg, 120_000)
        if "mcp_servers" not in text:
            continue
        block = text[text.find("mcp_servers"):]
        names = re.findall(r"(?m)^\s{2}([A-Za-z0-9_.\-]+)\s*:\s*$", block)
        for name in names[:80]:
            found.append({"name": name, "config": str(cfg), "transport": "stdio/http", "details": "redacted manifest only"})
    _add_evidence(ledger, "mcp_scan", f"Discovered {len(found)} configured MCP server entries.", count=len(found))
    return {"servers": found, "note": "Native MCP tools are available to Hermes after startup."}


def _tool_manifest(profile: str, enabled_toolsets: list[str]) -> dict[str, Any]:
    toolsets = enabled_toolsets or CAPABILITY_PROFILES.get(profile, CAPABILITY_PROFILES["omni"])
    result = {name: STATIC_TOOLSETS.get(name, [f"unknown toolset: {name}"]) for name in toolsets}
    return {"profile": profile, "toolsets": result, "safe_agent_tools": SAFE_AGENT_TOOLS}


def _build_capability_manifest(args: dict[str, Any], ledger: list[dict[str, Any]]) -> dict[str, Any]:
    profile = args.get("capability_profile") or "omni"
    if profile not in CAPABILITY_PROFILES:
        profile = "omni"
    enabled_toolsets = _as_str_list(args.get("enabled_toolsets"))
    agentic_blackboard = _normalise_bool(args.get("agentic_blackboard"), False)
    minimum_tools = _normalise_bool(args.get("minimum_tools"), True)
    brokered_tools = _normalise_bool(args.get("brokered_tools"), True)
    manifest = {
        "tool_mode": args.get("tool_mode", "safe_agent"),
        "capability_profile": profile,
        "tools": _tool_manifest(profile, enabled_toolsets),
        "plugins": [],
        "skills": [],
        "mcp": {"servers": []},
        "protocols": {
            "safe_agent_note": f"Agents have access to safe read-only tools: {', '.join(SAFE_AGENT_TOOLS[:8])}... No patch/write/terminal.",
            "evidence_rule": "Cite evidence ids for claims; mark unsupported as assumptions.",
            "minimum_tools_rule": "Use reasoning/blackboard first; request tools only for concrete information gain.",
        },
    }
    if agentic_blackboard or preset_active(args):
        manifest["blackboard"] = _build_blackboard_policy(
            max_tool_requests=_clamp_int(args.get("max_tool_requests"), MAX_AGENTIC_TOOL_REQUESTS, 0, MAX_AGENTIC_TOOL_REQUESTS),
            active_tool_agents=_clamp_int(args.get("active_tool_agents"), AGENTIC_ACTIVE_TOOL_AGENTS, 1, 20),
            mutating_agents=_clamp_int(args.get("mutating_agents"), AGENTIC_MUTATING_AGENTS, 0, 0),
            minimum_tools=minimum_tools,
            brokered_tools=brokered_tools,
        )
    if _normalise_bool(args.get("auto_capability_scan"), True):
        manifest["plugins"] = _scan_plugins(ledger)
    if _normalise_bool(args.get("auto_skills"), True) or _as_str_list(args.get("skills")):
        manifest["skills"] = _scan_skills(ledger, _as_str_list(args.get("skills")))
    if args.get("mcp_mode", "manifest") != "off":
        manifest["mcp"] = _scan_mcp(ledger)
    _add_evidence(ledger, "capability_manifest", "Built bounded capability manifest for OmniCouncil prompts.", profile=profile, blackboard=agentic_blackboard)
    return manifest


def preset_active(args: dict[str, Any]) -> bool:
    p = str(args.get("preset") or "").lower()
    return p in {"omni_blackboard", "audit", "max", "deep"}


def _manifest_text(manifest: dict[str, Any]) -> str:
    compact = {
        "tool_mode": manifest.get("tool_mode"),
        "capability_profile": manifest.get("capability_profile"),
        "tools": manifest.get("tools"),
        "plugins": manifest.get("plugins", [])[:120],
        "skills": manifest.get("skills", [])[:260],
        "mcp": manifest.get("mcp"),
        "protocols": manifest.get("protocols"),
        "blackboard": manifest.get("blackboard"),
    }
    return _truncate_text(_json(compact), MAX_MANIFEST_CHARS, "…[capability manifest truncated]")


def _evidence_text(ledger: list[dict[str, Any]]) -> str:
    return _truncate_text(_json(ledger), MAX_EVIDENCE_CHARS, "…[evidence truncated]")


# ═══════════════════════════════════════════════════════════════
#  Memory prefetch
# ═══════════════════════════════════════════════════════════════
def _prefetch_memory_context(task: str, context: str, max_chars: int, ledger: list[dict[str, Any]]) -> str:
    query = (task + "\n" + context[:4000]).strip()
    if not query:
        return ""
    result = _execute_safe_tool("memory_wiki_pack_context", {"query": query, "max_chars": max_chars})
    text = ""
    if isinstance(result, dict):
        if result.get("success") is False:
            return ""
        for key in ("context", "packed_context", "text", "markdown", "result"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                text = val.strip()
                break
    elif isinstance(result, str):
        text = result.strip()
    if not text:
        _add_evidence(ledger, "memory_context", "memory_wiki_pack_context returned no usable context.", available=False)
        return ""
    text = _truncate_text(_redact(text), max_chars)
    _add_evidence(ledger, "memory_context", f"Prefetched {len(text)} chars from memory_wiki_pack_context.", chars=len(text))
    return text


# ═══════════════════════════════════════════════════════════════
#  web_research_brief (composite web search + extract summarisation)
# ═══════════════════════════════════════════════════════════════
def _web_research_brief(query: str, max_sources: int = 5, ledger: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    brief: dict[str, Any] = {"query": query, "sources": [], "summary": ""}
    search_result = _execute_safe_tool("web_search", {"query": query, "limit": max_sources})
    urls: list[str] = []
    if isinstance(search_result, dict) and search_result.get("results"):
        for r in search_result["results"]:
            if isinstance(r, dict):
                urls.append(r.get("url", ""))
    elif isinstance(search_result, str):
        try:
            data = json.loads(search_result)
            if isinstance(data, dict) and data.get("results"):
                for r in data["results"]:
                    if isinstance(r, dict):
                        urls.append(r.get("url", ""))
        except Exception:
            pass
    urls = [u for u in urls if u][:max_sources]
    for url in urls:
        try:
            extract_result = _execute_safe_tool("web_extract", {"urls": [url]})
            brief["sources"].append({"url": url, "extract": _truncate_text(str(extract_result), 2000)})
        except Exception:
            brief["sources"].append({"url": url, "extract": "extraction_failed"})
    if ledger is not None:
        _add_evidence(ledger, "web_research_brief", f"Brief for '{query}': {len(urls)} sources.", sources=len(urls), query=query)
    return brief


# ═══════════════════════════════════════════════════════════════
#  Member prompt
# ═══════════════════════════════════════════════════════════════
def _member_perspectives(custom: Any = None) -> list[str]:
    custom_list = _as_str_list(custom)
    if not custom_list:
        return list(PERSPECTIVES)
    seen: set[str] = set()
    merged: list[str] = []
    for item in custom_list + list(PERSPECTIVES):
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(item.strip())
    return merged or list(PERSPECTIVES)


def _agentic_perspectives(custom: Any = None) -> list[str]:
    custom_list = _as_str_list(custom)
    base = custom_list + list(OMNI_BLACKBOARD_ROLES) if custom_list else list(OMNI_BLACKBOARD_ROLES)
    base += list(PERSPECTIVES)
    seen: set[str] = set()
    out: list[str] = []
    for item in base:
        key = item.split(":", 1)[0].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _member_identity(council_i: int, member_i: int, perspectives: list[str] | None = None) -> tuple[str, str]:
    label = f"C{council_i + 1}M{member_i + 1}"
    roles = perspectives or PERSPECTIVES
    perspective = roles[member_i % len(roles)].split(":", 1)[0]
    return label, perspective


def _member_prompt(
    task: str, context: str, mode: str, council_i: int, member_i: int,
    manifest: dict[str, Any], ledger: list[dict[str, Any]], output_format: str,
    max_tool_requests: int, perspectives: list[str] | None = None,
    councils: int = DEFAULT_COUNCILS, decision_policy: str = "judge", red_team: bool = False,
    blackboard: dict[str, Any] | None = None, messages: list[dict[str, Any]] | None = None,
    member_model: str = DEFAULT_MODEL,
) -> str:
    roles = perspectives or PERSPECTIVES
    perspective = roles[member_i % len(roles)]
    role_rules = ""
    if red_team and member_i == 0:
        role_rules += "\nRed-team duty: deliberately attack the proposed plan, look for hidden failures, cheapest falsification tests."
    if decision_policy != "judge":
        role_rules += f"\nDecision policy hint: prepare explicit votes/objections suitable for `{decision_policy}` synthesis."

    blackboard_block = ""
    if blackboard:
        blackboard_block = f"""
Shared blackboard:
{_truncate_text(_json(blackboard), 20_000)}

Agentic collaboration contract:
- Используй safe tools (read-only): memory_wiki_query, read_file, search_files, web_search, web_extract.
- НЕ запрашивай patch, write_file, terminal, process — они запрещены для агентов.
- При необходимости фактов — выполни tool request в блоке TOOL_REQUESTS_JSON.
- Всегда добавляй секцию Blackboard update: Facts/Assumptions/Open questions/Actions/Objections.
- Отвечай на сообщения других агентов, если они к тебе обращаются.
"""

    message_block = ""
    if messages:
        my_label = f"C{council_i + 1}M{member_i + 1}"
        relevant = [
            m for m in messages
            if m.get("to") in (None, my_label, "all") or m.get("from") == my_label
        ]
        if relevant:
            message_block = f"""
Message board (сообщения, адресованные тебе или всем):
{_truncate_text(_json(relevant), MAX_MESSAGE_HISTORY_CHARS)}

Ты можешь ответить другим агентам через секцию Messages: в формате:
[{{"to":"C2M1","type":"question","content":"..."}}]
"""

    capability_block = f"""
Доступные safe tools (read-only):
{_truncate_text(_json(SAFE_AGENT_TOOLS), 3000)}

Tool request protocol:
- Для запроса фактов используй блок TOOL_REQUESTS_JSON: с JSON-массивом до {max_tool_requests} запросов.
- Каждый запрос: {{"tool":"memory_wiki_query|read_file|web_search|web_extract|...", "args":{{}}, "reason":"...", "priority":1-5}}
- Ты не вызываешь tools напрямую, но можешь запросить их выполнение.
"""

    return f"""Ты участник {council_i + 1}/{councils} OmniCouncil (Hermes OmniCouncil v4).
Модель: {member_model}
Перспектива: {perspective}
Режим: {mode}
Decision policy: {decision_policy}
{role_rules}

Правила:
- Дай практически применимый результат, не философию.
- Используй доступные safe tools для поиска фактов (web_search, read_file, memory_wiki_query).
- При agentic blackboard режиме добавляй Blackboard update: секцию.
- Ты можешь общаться с другими агентами через Messages: секцию.
- После ответа других агентов укажи, изменилось ли твоё мнение.
- Сохраняй возможность для главного ассистента сразу выполнить правки.
{capability_block}
{blackboard_block}
{message_block}
Контекст:
{_bounded_context(context) or "(нет дополнительного контекста)"}

Задача:
{task}
"""


# ═══════════════════════════════════════════════════════════════
#  Parse tool requests / messages from agent answer
# ═══════════════════════════════════════════════════════════════
def _json_array_after_marker(text: str, marker: str = "TOOL_REQUESTS_JSON") -> str:
    m = re.search(rf"{re.escape(marker)}\s*:\s*", text, flags=re.IGNORECASE)
    if not m:
        return ""
    start = text.find("[", m.end())
    if start < 0:
        return ""
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return ""


def _safe_json_loads(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return json.loads(text)


def _extract_tool_requests(text: str, max_items: int) -> list[dict[str, Any]]:
    if not text or max_items <= 0:
        return []
    limit = min(max_items, MAX_AGENTIC_TOOL_REQUESTS)
    candidates = []
    balanced = _json_array_after_marker(text)
    if balanced:
        candidates.append(balanced)
    for fence in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        if fence.strip().startswith("["):
            candidates.append(fence.strip())
    for raw in candidates:
        try:
            data = _safe_json_loads(raw)
            if isinstance(data, dict):
                data = data.get("tool_requests") or data.get("requests") or []
            if isinstance(data, list):
                cleaned = []
                for item in data[:limit]:
                    if isinstance(item, dict):
                        tool = _truncate_text(item.get("tool", ""), 120).strip()
                        if not tool:
                            continue
                        # Block unsafe tools
                        if tool in ("patch", "write_file", "terminal", "process", "cronjob"):
                            continue
                        cleaned.append({
                            "tool": tool,
                            "args": item.get("args", {}) if isinstance(item.get("args", {}), dict) else {},
                            "reason": _truncate_text(item.get("reason", ""), 500),
                            "priority": _clamp_int(item.get("priority"), 3, 1, 5),
                        })
                return cleaned[:limit]
        except Exception:
            continue
    return []


def _extract_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    m = re.search(r"(?i)Messages\s*:\s*", text)
    if not m:
        m = re.search(r"(?i)MESSAGES_JSON\s*:\s*", text)
    if not m:
        return messages
    remainder = text[m.end():]
    arr = _json_array_after_marker("Messages:" + remainder.split("Messages:", 1)[-1] if "Messages:" in remainder else remainder, marker="")
    if not arr:
        arr = _json_array_after_marker("MESSAGES_JSON:" + remainder, marker="")
    if arr:
        try:
            data = _safe_json_loads(arr)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("to") and item.get("content"):
                        messages.append({
                            "to": str(item.get("to", "")),
                            "type": str(item.get("type", "question")),
                            "content": _truncate_text(item.get("content", ""), MAX_MESSAGE_CHARS),
                        })
        except Exception:
            pass
    return messages


def _dedupe_tool_requests(answers: list[dict[str, Any]], max_items: int, minimum_tools: bool = True) -> list[dict[str, Any]]:
    if max_items <= 0:
        return []
    limit = min(max_items, MAX_AGENTIC_TOOL_REQUESTS)
    seen = set()
    out = []
    for ans in answers:
        for req in ans.get("tool_requests", []) or []:
            key = json.dumps([req.get("tool"), req.get("args")], sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            req = dict(req)
            req["requested_by"] = ans.get("label")
            out.append(req)
    out.sort(key=lambda x: int(x.get("priority") or 3), reverse=True)
    return out[:limit]


# ═══════════════════════════════════════════════════════════════
#  Call member / collaboration / message rounds
# ═══════════════════════════════════════════════════════════════
def _call_member(
    task: str, context: str, mode: str, council_i: int, member_i: int,
    max_tokens: int, manifest: dict[str, Any], ledger: list[dict[str, Any]],
    output_format: str, max_tool_requests: int,
    perspectives: list[str] | None = None, councils: int = DEFAULT_COUNCILS,
    timeout: int = DEFAULT_MODEL_TIMEOUT, retries: int = DEFAULT_MEMBER_RETRIES,
    decision_policy: str = "judge", red_team: bool = False,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    blackboard: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    member_model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    label, perspective = _member_identity(council_i, member_i, perspectives)
    try:
        started = time.time()
        prompt = _member_prompt(
            task, context, mode, council_i, member_i, manifest, ledger,
            output_format, max_tool_requests, perspectives, councils,
            decision_policy, red_team, blackboard=blackboard, messages=messages,
            member_model=member_model,
        )
        answer = _call_model_text(prompt, max_tokens, 0.05 + (member_i * 0.05), model=member_model, timeout=timeout, retries=retries, jitter_ms=jitter_ms)
        return {
            "label": label, "council": council_i + 1, "member": member_i + 1,
            "perspective": perspective, "status": "success", "answer": answer,
            "tool_requests": _extract_tool_requests(answer, max_tool_requests),
            "messages_out": _extract_messages(answer),
            "model": member_model,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        logger.warning("%s failed: %s", label, exc)
        return {
            "label": label, "council": council_i + 1, "member": member_i + 1,
            "perspective": perspective, "status": "failed",
            "error": _truncate_text(str(exc), 500),
        }


def _format_answer(item: dict[str, Any], field: str = "answer", max_chars: int = 6000) -> str:
    label = item.get("label") or item.get("mission") or "UNKNOWN"
    perspective = item.get("perspective", "")
    if item.get("status") == "success":
        text = _truncate_text(item.get(field) or item.get("answer") or item.get("report") or "", max_chars)
        return f"## {label} / {perspective} (model={item.get('model','?')})\n{text}"
    return f"## {label} FAILED\n{_truncate_text(item.get('error') or item.get('reason') or '', 700)}"


def _format_answers(answers: list[dict[str, Any]], field: str = "answer", max_chars: int = 6000) -> str:
    if not answers:
        return "(нет ответов)"
    return "\n\n".join(_format_answer(item, field, max_chars) for item in answers)


def _collaboration_prompt(
    task: str, context: str, mode: str, member: dict[str, Any],
    initial_answers: list[dict[str, Any]], previous_rounds: list[dict[str, Any]],
    round_no: int, manifest: dict[str, Any], ledger: list[dict[str, Any]],
    research_reports: list[dict[str, Any]], tool_requests: list[dict[str, Any]],
    blackboard: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    member_model: str = DEFAULT_MODEL,
) -> str:
    previous = "\n\n".join(
        f"# Round {r.get('round')}\n{_format_answers(r.get('responses', []), field='response', max_chars=MAX_PREVIOUS_ROUND_CHARS_FOR_COLLAB)}"
        for r in previous_rounds
    ) or "(первый раунд обсуждения)"
    initial = _format_answers(initial_answers, max_chars=MAX_INITIAL_ANSWER_CHARS_FOR_COLLAB)
    research = _format_answers(research_reports, field="report", max_chars=8000) if research_reports else ""

    blackboard_block = ""
    if blackboard:
        blackboard_block = f"Shared blackboard:\n{_truncate_text(_json(blackboard), 20_000)}\n"

    message_block = ""
    if messages:
        my_label = member.get("label", "")
        relevant = [m for m in messages if m.get("to") in (None, my_label, "all")]
        if relevant:
            message_block = f"Messages для тебя:\n{_truncate_text(_json(relevant), MAX_MESSAGE_HISTORY_CHARS)}\n"

    prompt = f"""Ты {member.get('label')} / {member.get('perspective')} в OmniCouncil (модель: {member_model}).
Раунд командного обсуждения: {round_no}

Задача: {task}
Режим: {mode}

{blackboard_block}
{message_block}

Первичные ответы команды:
{initial}

Предыдущие раунды:
{previous}

Research reports:
{research}

Aggregated tool requests:
{_truncate_text(_json(tool_requests), 20_000)}

Твоя цель:
- прямо ссылайся на идеи коллег по label;
- найди противоречия, скрытые риски, edge cases;
- улучши общий план;
- используй TOOL_REQUESTS_JSON: для safe tools;
- общайся с другими агентами через Messages: секцию;
- закончи блоками Blackboard update: и Мой обновлённый вклад:.

Safe tools: memory_wiki_query, read_file, search_files, web_search, web_extract.
"""
    if _prompt_too_large(prompt):
        prompt = prompt.replace(initial, _format_answers(initial_answers, max_chars=900)).replace(previous, _format_answers(initial_answers, max_chars=800))
    return _truncate_text(prompt, MAX_PROMPT_CONTEXT_CHARS, "…[prompt truncated]")


def _call_collaboration_member(
    task: str, context: str, mode: str, member: dict[str, Any],
    initial_answers: list[dict[str, Any]], previous_rounds: list[dict[str, Any]],
    round_no: int, max_tokens: int, manifest: dict[str, Any],
    ledger: list[dict[str, Any]], research_reports: list[dict[str, Any]],
    tool_requests: list[dict[str, Any]], max_tool_requests: int,
    timeout: int = DEFAULT_MODEL_TIMEOUT, retries: int = DEFAULT_MEMBER_RETRIES,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    blackboard: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    member_model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    try:
        started = time.time()
        prompt = _collaboration_prompt(
            task, context, mode, member, initial_answers, previous_rounds, round_no,
            manifest, ledger, research_reports, tool_requests,
            blackboard=blackboard, messages=messages, member_model=member_model,
        )
        member_no = int(member.get("member") or 1) - 1
        response = _call_model_text(prompt, max_tokens, 0.08 + (member_no * 0.04), model=member_model, timeout=timeout, retries=retries, jitter_ms=jitter_ms)
        return {
            "label": member.get("label"), "council": member.get("council"),
            "member": member.get("member"), "perspective": member.get("perspective"),
            "status": "success", "response": response,
            "tool_requests": _extract_tool_requests(response, max_tool_requests),
            "messages_out": _extract_messages(response),
            "model": member_model,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {
            "label": member.get("label"), "council": member.get("council"),
            "member": member.get("member"), "perspective": member.get("perspective"),
            "status": "failed", "error": _truncate_text(str(exc), 500),
        }


def _run_collaboration(
    task: str, context: str, mode: str, answers: list[dict[str, Any]], rounds: int,
    max_tokens: int, manifest: dict[str, Any], ledger: list[dict[str, Any]],
    research_reports: list[dict[str, Any]], tool_requests: list[dict[str, Any]],
    max_tool_requests: int, max_workers: int = DEFAULT_MAX_COLLABORATION_WORKERS,
    timeout: int = DEFAULT_MODEL_TIMEOUT, retries: int = DEFAULT_MEMBER_RETRIES,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    blackboard: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    member_models: list[str] | None = None,
) -> list[dict[str, Any]]:
    successful = [a for a in answers if a.get("status") == "success"]
    transcript: list[dict[str, Any]] = []
    if not successful or rounds <= 0:
        return transcript
    member_models = member_models or [DEFAULT_MODEL]
    for round_no in range(1, rounds + 1):
        worker_count = max(1, min(len(successful), max_workers or DEFAULT_MAX_COLLABORATION_WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            future_map = {
                pool.submit(
                    _call_collaboration_member, task, context, mode, member,
                    answers, transcript, round_no, max_tokens, manifest, ledger,
                    research_reports, tool_requests, max_tool_requests, timeout,
                    retries, jitter_ms, blackboard=blackboard, messages=messages,
                    member_model=member_models[(int(member.get("member") or 1) - 1) % len(member_models)],
                ): member
                for member in successful
            }
            responses = []
            for future in concurrent.futures.as_completed(future_map):
                member = future_map[future]
                try:
                    responses.append(future.result())
                except Exception as exc:
                    responses.append({
                        "label": member.get("label"), "council": member.get("council"),
                        "member": member.get("member"), "perspective": member.get("perspective"),
                        "status": "failed", "error": _truncate_text(str(exc), 500),
                    })
            responses.sort(key=lambda item: (int(item.get("council") or 0), int(item.get("member") or 0), str(item.get("label") or "")))
        tool_requests = _dedupe_tool_requests(answers + [r for t in transcript for r in t.get("responses", [])] + responses, max_tool_requests)
        transcript.append({"round": round_no, "responses": responses})
    return transcript


# ═══════════════════════════════════════════════════════════════
#  Message rounds (agents send messages to each other)
# ═══════════════════════════════════════════════════════════════
def _run_message_rounds(
    task: str, context: str, mode: str, answers: list[dict[str, Any]],
    rounds: int, max_tokens: int, manifest: dict[str, Any],
    ledger: list[dict[str, Any]], tool_requests: list[dict[str, Any]],
    max_tool_requests: int, max_workers: int = DEFAULT_MAX_COLLABORATION_WORKERS,
    timeout: int = DEFAULT_MODEL_TIMEOUT, retries: int = DEFAULT_MEMBER_RETRIES,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    blackboard: dict[str, Any] | None = None,
    member_models: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    successful = [a for a in answers if a.get("status") == "success"]
    if not successful or rounds <= 0:
        return [], []
    member_models = member_models or [DEFAULT_MODEL]
    all_messages: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []

    for round_no in range(rounds):
        # Каждый агент видит все предыдущие сообщения
        worker_count = max(1, min(len(successful), max_workers or DEFAULT_MAX_COLLABORATION_WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            future_map = {
                pool.submit(
                    _call_message_round_member, task, context, mode, member,
                    answers, all_messages, round_no, max_tokens, manifest, ledger,
                    tool_requests, max_tool_requests, timeout, retries, jitter_ms,
                    blackboard=blackboard,
                    member_model=member_models[(int(member.get("member") or 1) - 1) % len(member_models)],
                ): member
                for member in successful
            }
            responses = []
            for future in concurrent.futures.as_completed(future_map):
                member = future_map[future]
                try:
                    resp = future.result()
                    responses.append(resp)
                    for msg in resp.get("messages_out", []):
                        msg["from"] = member.get("label")
                        msg["round"] = round_no
                        all_messages.append(msg)
                except Exception as exc:
                    responses.append({
                        "label": member.get("label"), "status": "failed",
                        "error": _truncate_text(str(exc), 500),
                    })
        transcript.append({"message_round": round_no, "responses": responses})
    return transcript, all_messages


def _call_message_round_member(
    task: str, context: str, mode: str, member: dict[str, Any],
    initial_answers: list[dict[str, Any]], all_messages: list[dict[str, Any]],
    round_no: int, max_tokens: int, manifest: dict[str, Any],
    ledger: list[dict[str, Any]], tool_requests: list[dict[str, Any]],
    max_tool_requests: int, timeout: int = DEFAULT_MODEL_TIMEOUT,
    retries: int = DEFAULT_MEMBER_RETRIES, jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    blackboard: dict[str, Any] | None = None,
    member_model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    try:
        my_label = member.get("label", "")
        relevant = [m for m in all_messages if m.get("to") in (None, my_label, "all")]
        prompt = f"""Ты {my_label} / {member.get('perspective')} в OmniCouncil, message round {round_no}.

Другие агенты отправили тебе сообщения. Прочитай их и ответь.

Задача: {task}
Режим: {mode}

Сообщения:
{_truncate_text(_json(relevant), MAX_MESSAGE_HISTORY_CHARS)}

Ты можешь ответить другим агентам через секцию Messages: в формате JSON:
[{{"to":"C2M1","type":"question|answer|challenge|clarification","content":"твой ответ"}}]

Также можешь запрашивать safe tools через TOOL_REQUESTS_JSON.
"""
        answer = _call_model_text(prompt, max_tokens, 0.08, model=member_model, timeout=timeout, retries=retries, jitter_ms=jitter_ms)
        return {
            "label": my_label, "status": "success", "response": answer,
            "messages_out": _extract_messages(answer),
            "tool_requests": _extract_tool_requests(answer, max_tool_requests),
            "model": member_model,
        }
    except Exception as exc:
        return {"label": member.get("label"), "status": "failed", "error": _truncate_text(str(exc), 500)}


# ═══════════════════════════════════════════════════════════════
#  Judge
# ═══════════════════════════════════════════════════════════════
def _blackboard_summary(answers: list[dict[str, Any]], transcript: list[dict[str, Any]], tool_requests: list[dict[str, Any]], messages: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    if not (manifest.get("blackboard") or {}).get("enabled"):
        return {}
    responses = [a for a in answers if a.get("status") == "success"] + [
        r for t in transcript for r in t.get("responses", []) if r.get("status") == "success"
    ]
    return {
        "enabled": True,
        "responses_seen": len(responses),
        "message_count": len(messages),
        "tool_requests_total": len(tool_requests),
    }


def _judge_prompt(
    task: str, context: str, mode: str, answers: list[dict[str, Any]],
    transcript: list[dict[str, Any]], manifest: dict[str, Any],
    ledger: list[dict[str, Any]], research_reports: list[dict[str, Any]],
    tool_requests: list[dict[str, Any]], messages: list[dict[str, Any]],
    output_format: str, save_task_capsule: bool,
    decision_policy: str = "judge", red_team: bool = False,
    judge_model: str = DEFAULT_MODEL,
) -> str:
    blackboard_enabled = bool((manifest.get("blackboard") or {}).get("enabled"))
    discussion = "\n\n".join(
        f"# Round {r.get('round')}\n{_format_answers(r.get('responses', []), field='response', max_chars=MAX_DISCUSSION_CHARS_FOR_JUDGE)}"
        for r in transcript
    ) or "(обсуждение не включалось)"
    initial = _format_answers(answers, max_chars=MAX_INITIAL_ANSWER_CHARS_FOR_JUDGE)
    research = _format_answers(research_reports, field="report", max_chars=MAX_RESEARCH_REPORT_CHARS_FOR_JUDGE) if research_reports else ""

    msg_text = _truncate_text(_json(messages), MAX_MESSAGE_HISTORY_CHARS) if messages else ""

    decision_rule = {
        "judge": "Use best-evidence judgement; do not average weak arguments.",
        "majority": "Report the apparent majority view, override if evidence demands.",
        "consensus": "Prefer consensus; list unresolved disagreements and safest next experiment.",
        "risk_weighted": "Prefer lowest irreversible risk with strongest rollback path.",
    }.get(decision_policy, "Use best-evidence judgement.")

    format_rules = {
        "prose": "Верни связный практический отчёт.",
        "structured": "Верни Markdown с секциями: Verdict, Evidence, Decision, Implementation plan, Tests, Risks, Next step.",
        "patch_plan": "Верни конкретный план изменений: файлы, функции, old/new intent, команды проверки, rollback.",
        "json": "Верни валидный JSON: summary, evidence, decision, implementation_plan[], tests[], risks[], next_step.",
    }.get(output_format, "Верни структурированный отчёт.")

    prompt = f"""Ты финальный судья Hermes OmniCouncil v4 (модель: {judge_model}).
Синтезируй лучший проверяемый результат, опираясь на evidence и research.

Output format: {output_format}
{format_rules}
Decision policy: {decision_policy}
{decision_rule}

Задача:
{task}

Контекст:
{_bounded_context(context) or "(нет дополнительного контекста)"}

Режим: {mode}

Первичные ответы участников:
{initial}

Обсуждение:
{discussion}

Сообщения агентов:
{msg_text}

Aggregated tool requests:
{_truncate_text(_json(tool_requests), 20_000)}

Research reports:
{research}

Blackboard summary:
{_truncate_text(_json(_blackboard_summary(answers, transcript, tool_requests, messages, manifest)), 12_000)}

Evidence ledger:
{_evidence_text(ledger)}
"""
    if _prompt_too_large(prompt):
        prompt = prompt.replace(initial, _format_answers(answers, max_chars=1000))
    return _truncate_text(prompt, MAX_PROMPT_CONTEXT_CHARS)


def _judge(
    task: str, context: str, mode: str, answers: list[dict[str, Any]],
    judge_max_tokens: int, transcript: list[dict[str, Any]], manifest: dict[str, Any],
    ledger: list[dict[str, Any]], research_reports: list[dict[str, Any]],
    tool_requests: list[dict[str, Any]], messages: list[dict[str, Any]],
    output_format: str, save_task_capsule: bool,
    timeout: int = DEFAULT_JUDGE_TIMEOUT, retries: int = DEFAULT_MEMBER_RETRIES,
    strict_json: bool = False, decision_policy: str = "judge", red_team: bool = False,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    judge_model: str = DEFAULT_MODEL,
) -> str:
    prompt = _judge_prompt(task, context, mode, answers, transcript, manifest, ledger, research_reports, tool_requests, messages, output_format, save_task_capsule, decision_policy, red_team, judge_model=judge_model)
    if strict_json and output_format == "json":
        prompt += "\n\nSTRICT_JSON: Return only valid JSON, no markdown fences."
    try:
        content = _call_model_text(prompt, judge_max_tokens, 0.1, model=judge_model, timeout=timeout, retries=retries, jitter_ms=jitter_ms)
    except Exception as exc:
        raise RuntimeError(f"judge failed: {exc}")
    content = _redact(content)
    if strict_json and output_format == "json":
        try:
            parsed = _safe_json_loads(content)
            if isinstance(parsed, dict):
                return _json(parsed)
        except Exception:
            return _json({"status": "partial", "warning": "judge_output_was_not_valid_json", "synthesis_text": content})
    return content


# ═══════════════════════════════════════════════════════════════
#  Research missions
# ═══════════════════════════════════════════════════════════════
def _make_research_missions(task: str, mode: str, manifest: dict[str, Any], max_agents: int, enabled_toolsets: list[str]) -> list[dict[str, Any]]:
    base = [
        ("web_research", "Use web_search + web_extract + web_research_brief to find external facts and recent data relevant to the task."),
        ("file_inspection", "Use read_file + search_files to inspect relevant source files and configuration."),
        ("memory_lookup", "Use memory_wiki_query to search durable memory for past decisions and project context."),
        ("alternative_approaches", "Research alternative solutions, tradeoffs, and competing designs."),
        ("risk_analysis", "Identify risks, failure modes, edge cases, and security concerns."),
    ]
    missions = []
    for name, goal in base[:max_agents]:
        missions.append({"mission": name, "goal": goal, "task": task, "mode": mode, "enabled_toolsets": list(enabled_toolsets)})
    return missions


def _run_research_mission(mission: dict[str, Any], manifest: dict[str, Any], max_tokens: int, jitter_ms: int = DEFAULT_REQUEST_JITTER_MS, research_model: str = DEFAULT_MODEL) -> dict[str, Any]:
    try:
        prompt = f"""Ты research subagent в Hermes OmniCouncil v4.
Используй safe tools (web_search, web_extract, read_file, memory_wiki_query) для поиска фактов.
Отделяй Evidence от Assumption. Верни Findings, Risks, Acceptance tests.

Mission: {_json(mission)}
Capability manifest: {_manifest_text(manifest)}
"""
        report = _call_model_text(prompt, min(max_tokens, 32000), 0.1, model=research_model, timeout=900, jitter_ms=jitter_ms)
        return {"mission": mission.get("mission"), "status": "success", "kind": "model_research", "report": report, "model": research_model}
    except Exception as exc:
        return {"mission": mission.get("mission"), "status": "failed", "kind": "model_research", "error": _truncate_text(str(exc), 800)}


def _run_research_missions(
    task: str, mode: str, manifest: dict[str, Any], max_agents: int,
    enabled_toolsets: list[str], max_tokens: int, ledger: list[dict[str, Any]],
    max_workers: int = DEFAULT_MAX_RESEARCH_WORKERS,
    jitter_ms: int = DEFAULT_REQUEST_JITTER_MS,
    research_model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    missions = _make_research_missions(task, mode, manifest, max_agents, enabled_toolsets)
    _add_evidence(ledger, "research_missions", f"Prepared {len(missions)} research missions.", count=len(missions))
    if not missions:
        return []
    worker_count = max(1, min(len(missions), max_workers or DEFAULT_MAX_RESEARCH_WORKERS))
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_run_research_mission, m, manifest, max_tokens, jitter_ms, research_model): m for m in missions}
        for future in concurrent.futures.as_completed(future_map):
            mission = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"mission": mission.get("mission"), "status": "failed", "kind": "executor", "error": _truncate_text(str(exc), 800)})
    for r in results:
        if r.get("status") == "success":
            _add_evidence(ledger, "research_report", f"Research mission {r.get('mission')} completed.", mission=r.get("mission"))
    return results


# ═══════════════════════════════════════════════════════════════
#  Fallback synthesis
# ═══════════════════════════════════════════════════════════════
def _fallback_synthesis(
    task: str, mode: str, answers: list[dict[str, Any]],
    transcript: list[dict[str, Any]], research_reports: list[dict[str, Any]],
    tool_requests: list[dict[str, Any]], reason: str,
) -> str:
    successful = [a for a in answers if a.get("status") == "success"]
    if not successful and not research_reports:
        return f"## OmniCouncil fallback\nStatus: no_successful_members\nReason: {reason}"
    best = successful[0] if successful else None
    if best:
        return (
            f"## OmniCouncil fallback synthesis\n"
            f"Reason: {_truncate_text(reason, 800)}\n"
            f"Best response from {best.get('label')} ({best.get('model','?')}):\n\n"
            f"{_truncate_text(best.get('answer', ''), 30_000)}"
        )
    best_research = research_reports[0] if research_reports else None
    if best_research:
        return f"## OmniCouncil fallback (research only)\nReason: {_truncate_text(reason, 800)}\n\n{_truncate_text(best_research.get('report', ''), 30_000)}"
    return f"## OmniCouncil fallback\nReason: {_truncate_text(reason, 800)}\nNo usable member or research results."


# ═══════════════════════════════════════════════════════════════
#  Cache
# ═══════════════════════════════════════════════════════════════
def _cache_key(task: str, context: str, mode: str, options: dict[str, Any], manifest: dict[str, Any], default_model: str) -> str:
    payload = {
        "v": 4,
        "model": default_model,
        "task": task,
        "context": context,
        "mode": mode,
        "councils": options.get("councils", DEFAULT_COUNCILS),
        "members_per_council": options.get("members_per_council", DEFAULT_MEMBERS_PER_COUNCIL),
        "options": {k: v for k, v in options.items() if not str(k).startswith("_")},
        "manifest_hash": hashlib.sha256(_manifest_text(manifest).encode()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════
#  Preset defaults
# ═══════════════════════════════════════════════════════════════
def _complexity_score(task: str, context: str) -> int:
    combined = (task + " " + context).lower()
    score = 2
    for kw in ("migration", "deploy", "production", "database", "security", "auth", "race condition"):
        if kw in combined:
            score += 1
    if len(combined) > 600:
        score += 1
    return min(8, score)


def _auto_scale(task: str, context: str) -> dict[str, Any]:
    score = _complexity_score(task, context)
    if score <= 1:
        return {"councils": 2, "members_per_council": 3, "collaboration_rounds": 0, "message_rounds": 0, "research_missions": False}
    if score <= 4:
        return {"councils": 3, "members_per_council": 4, "collaboration_rounds": 1, "message_rounds": 0, "research_missions": False}
    if score <= 8:
        return {"councils": 5, "members_per_council": 4, "collaboration_rounds": 2, "message_rounds": 1, "research_missions": True}
    return {"councils": 6, "members_per_council": 5, "collaboration_rounds": 2, "message_rounds": 2, "research_missions": True, "red_team": True}


def _apply_preset_defaults(args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    preset_name = str(out.get("preset") or "deep").lower()
    if preset_name not in CONSILIUM_PRESETS:
        preset_name = "deep"
    if preset_name == "auto" or _normalise_bool(out.get("auto_scale"), False):
        scaled = _auto_scale(str(out.get("task", "")), str(out.get("context", "")))
        for key, value in scaled.items():
            out.setdefault(key, value)
        out["auto_scale"] = True
        return out
    preset = CONSILIUM_PRESETS[preset_name]
    for key, value in preset.items():
        if value is not None:
            out.setdefault(key, value)
    return out


# ═══════════════════════════════════════════════════════════════
#  MAIN HANDLER — omnicouncil orchestration
# ═══════════════════════════════════════════════════════════════
def handler(args=None, **_kw):
    if args is None:
        args = {k: v for k, v in _kw.items() if k not in {"task_id", "ctx"}}
    else:
        args = dict(args or {})
        for k, v in _kw.items():
            if k not in {"task_id", "ctx"} and k not in args:
                args[k] = v

    args = _apply_preset_defaults(args)
    task = str(args.get("task", "")).strip()
    context = str(args.get("context", "")).strip()
    mode = args.get("mode", "edit_plan") or "edit_plan"
    if mode not in {"advise", "edit_plan", "review", "debug"}:
        mode = "edit_plan"
    if not task:
        return _json({"status": "error", "error": "task is required"})

    # ── Model resolution
    default_model, member_models, judge_model, research_model = _resolve_models(args)

    # ── Parse args
    councils = _clamp_int(args.get("councils"), DEFAULT_COUNCILS, 1, MAX_COUNCILS)
    members_per_council = _clamp_int(args.get("members_per_council"), DEFAULT_MEMBERS_PER_COUNCIL, 1, MAX_MEMBERS_PER_COUNCIL)
    agentic_blackboard = _normalise_bool(args.get("agentic_blackboard"), False) or preset_active(args)
    minimum_tools = _normalise_bool(args.get("minimum_tools"), True)
    brokered_tools = _normalise_bool(args.get("brokered_tools"), True)
    active_tool_agents = _clamp_int(args.get("active_tool_agents"), AGENTIC_ACTIVE_TOOL_AGENTS, 1, 20)
    mutating_agents = _clamp_int(args.get("mutating_agents"), AGENTIC_MUTATING_AGENTS, 0, 0)
    return_blackboard = _normalise_bool(args.get("return_blackboard"), False)
    perspectives = _agentic_perspectives(args.get("perspectives")) if agentic_blackboard else _member_perspectives(args.get("perspectives"))
    decision_policy = str(args.get("decision_policy") or "judge").strip().lower()
    if decision_policy not in {"judge", "majority", "consensus", "risk_weighted"}:
        decision_policy = "judge"
    red_team = _normalise_bool(args.get("red_team"), False)
    max_tokens = _clamp_int(args.get("max_tokens"), DEFAULT_MAX_TOKENS, 1000, 128000)
    judge_max_tokens = _clamp_int(args.get("judge_max_tokens"), DEFAULT_JUDGE_MAX_TOKENS, 1000, 128000)
    use_cache = _normalise_bool(args.get("use_cache"), True) and not _normalise_bool(args.get("force_refresh"), False)
    cache_ttl_seconds = _clamp_int(args.get("cache_ttl_seconds"), CACHE_TTL, 0, 30 * 24 * 60 * 60)
    collaborate = _normalise_bool(args.get("collaborate"), True)
    collaboration_rounds = _clamp_int(args.get("collaboration_rounds"), DEFAULT_COLLABORATION_ROUNDS, 0, 4)
    message_rounds = _clamp_int(args.get("message_rounds"), DEFAULT_MESSAGE_ROUNDS, 0, 3)
    return_transcript = _normalise_bool(args.get("return_transcript"), False)
    return_evidence = _normalise_bool(args.get("return_evidence"), True)
    research_missions = _normalise_bool(args.get("research_missions"), False)
    max_research_agents = _clamp_int(args.get("max_research_agents"), 3, 0, 8)
    max_tool_requests = _clamp_int(args.get("max_tool_requests"), MAX_TOOL_REQUESTS_DEFAULT, 0, MAX_AGENTIC_TOOL_REQUESTS)
    tool_mode = args.get("tool_mode", "safe_agent") or "safe_agent"
    output_format = args.get("output_format", "structured") or "structured"
    if output_format not in {"prose", "structured", "patch_plan", "json"}:
        output_format = "structured"
    auto_memory_context = _normalise_bool(args.get("auto_memory_context"), True)
    memory_context_chars = _clamp_int(args.get("memory_context_chars"), DEFAULT_MEMORY_CONTEXT_CHARS, 0, MAX_MEMORY_CONTEXT_CHARS)
    save_task_capsule = _normalise_bool(args.get("save_task_capsule"), False)
    member_retries = _clamp_int(args.get("member_retries"), DEFAULT_MEMBER_RETRIES, 0, 3)
    model_timeout = _clamp_int(args.get("model_timeout"), DEFAULT_MODEL_TIMEOUT, 30, 3600)
    judge_timeout = _clamp_int(args.get("judge_timeout"), DEFAULT_JUDGE_TIMEOUT, 30, 3600)
    request_jitter_ms = _clamp_int(args.get("request_jitter_ms"), DEFAULT_REQUEST_JITTER_MS, 0, MAX_REQUEST_JITTER_MS)
    strict_json = _normalise_bool(args.get("strict_json"), False)
    enabled_toolsets = _as_str_list(args.get("enabled_toolsets"))
    total_members = councils * members_per_council
    max_member_workers = _clamp_int(args.get("max_member_workers"), DEFAULT_MAX_MEMBER_WORKERS, 1, MAX_COUNCILS * MAX_MEMBERS_PER_COUNCIL)
    max_collaboration_workers = _clamp_int(args.get("max_collaboration_workers"), DEFAULT_MAX_COLLABORATION_WORKERS, 1, MAX_COUNCILS * MAX_MEMBERS_PER_COUNCIL)
    max_research_workers = _clamp_int(args.get("max_research_workers"), DEFAULT_MAX_RESEARCH_WORKERS, 1, 16)
    min_successful_members = _clamp_int(args.get("min_successful_members"), DEFAULT_MIN_SUCCESSFUL_MEMBERS, 0, total_members)

    context = _bounded_context(context)
    started = time.time()
    ledger: list[dict[str, Any]] = []

    # ── Manifest
    manifest = _build_capability_manifest({**args, "tool_mode": tool_mode, "agentic_blackboard": agentic_blackboard, "minimum_tools": minimum_tools, "brokered_tools": brokered_tools, "active_tool_agents": active_tool_agents, "mutating_agents": mutating_agents, "max_tool_requests": max_tool_requests}, ledger)

    # ── Memory prefetch
    memory_context = ""
    if auto_memory_context and memory_context_chars > 0:
        memory_context = _prefetch_memory_context(task, context, memory_context_chars, ledger)
        if memory_context:
            context = context + "\n\n---\nRelevant durable memory:\n" + memory_context if context else "Relevant durable memory:\n" + memory_context

    # ── Cache
    key = _cache_key(task, context, mode, {
        "preset": args.get("preset"), "councils": councils, "members_per_council": members_per_council,
        "decision_policy": decision_policy, "red_team": red_team, "agentic_blackboard": agentic_blackboard,
        "tool_mode": tool_mode, "capability_profile": manifest.get("capability_profile"),
    }, manifest, default_model)
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists() and time.time() - cache_file.stat().st_mtime < cache_ttl_seconds:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached["cached"] = True
            return _json(cached)
        except Exception:
            pass

    # ── Research missions
    research_reports: list[dict[str, Any]] = []
    if research_missions and max_research_agents > 0:
        research_reports = _run_research_missions(task, mode, manifest, max_research_agents, enabled_toolsets, max_tokens, ledger, max_research_workers, request_jitter_ms, research_model=research_model)

    # ── Primary member calls
    answers: list[dict[str, Any]] = []
    primary_workers = max(1, min(total_members, max_member_workers))
    blackboard: dict[str, Any] = {"task": task, "round": 0, "facts": [], "open_questions": [], "notes": {}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=primary_workers) as pool:
        future_map = {
            pool.submit(
                _call_member, task, context, mode, ci, mi, max_tokens, manifest, ledger,
                output_format, max_tool_requests, perspectives, councils, model_timeout,
                member_retries, decision_policy, red_team, request_jitter_ms,
                blackboard=blackboard,
                member_model=member_models[(ci * members_per_council + mi) % len(member_models)],
            ): (ci, mi)
            for ci in range(councils) for mi in range(members_per_council)
        }
        for future in concurrent.futures.as_completed(future_map):
            ci, mi = future_map[future]
            try:
                answers.append(future.result())
            except Exception as exc:
                label, perspective = _member_identity(ci, mi, perspectives)
                answers.append({"label": label, "council": ci + 1, "member": mi + 1, "perspective": perspective, "status": "failed", "error": _truncate_text(str(exc), 500)})
    answers.sort(key=lambda item: (int(item.get("council") or 0), int(item.get("member") or 0), str(item.get("label") or "")))

    succeeded = sum(1 for a in answers if a.get("status") == "success")
    tool_requests = _dedupe_tool_requests(answers, max_tool_requests, minimum_tools=minimum_tools)
    if tool_requests:
        _add_evidence(ledger, "tool_requests", f"Collected {len(tool_requests)} unique tool requests from members.", count=len(tool_requests))

    if succeeded < min_successful_members:
        transcript = []
        message_transcript = []
        all_messages = []
        collaboration_responded = 0
        judge_error = f"primary quorum not met: {succeeded}/{min_successful_members}"
        synthesis = _fallback_synthesis(task, mode, answers, transcript, research_reports, tool_requests, judge_error)
        status = "partial" if succeeded or any(r.get("status") == "success" for r in research_reports) else "failed"
    else:
        # ── Collaboration rounds
        transcript = _run_collaboration(task, context, mode, answers, collaboration_rounds, max_tokens, manifest, ledger, research_reports, tool_requests, max_tool_requests, max_collaboration_workers, model_timeout, member_retries, request_jitter_ms, blackboard=blackboard, member_models=member_models) if collaborate else []

        # ── Message rounds (агенты общаются друг с другом)
        message_transcript, all_messages = _run_message_rounds(task, context, mode, answers, message_rounds, max_tokens, manifest, ledger, tool_requests, max_tool_requests, max_collaboration_workers, model_timeout, member_retries, request_jitter_ms, blackboard=blackboard, member_models=member_models)

        all_responses = answers + [r for t in transcript for r in t.get("responses", [])]
        tool_requests = _dedupe_tool_requests(all_responses, max_tool_requests, minimum_tools=minimum_tools)
        collaboration_responded = sum(1 for round_item in transcript for response in round_item.get("responses", []) if response.get("status") == "success")

        try:
            synthesis = _judge(task, context, mode, answers, judge_max_tokens, transcript, manifest, ledger, research_reports, tool_requests, all_messages, output_format, save_task_capsule, timeout=judge_timeout, retries=member_retries, strict_json=strict_json, decision_policy=decision_policy, red_team=red_team, jitter_ms=request_jitter_ms, judge_model=judge_model)
            status = "success"
            judge_error = ""
        except Exception as exc:
            judge_error = _truncate_text(str(exc), 1000)
            synthesis = _fallback_synthesis(task, mode, answers, transcript, research_reports, tool_requests, f"judge failed: {judge_error}")
            status = "partial" if succeeded else "failed"

    # ── Result
    diagnostics = {
        "primary_success": succeeded,
        "primary_failed": total_members - succeeded,
        "collaboration_success": collaboration_responded,
        "message_rounds": message_rounds,
        "messages_exchanged": len(all_messages),
        "research_success": sum(1 for r in research_reports if r.get("status") == "success"),
        "tool_requests": len(tool_requests),
        "judge_success": not bool(judge_error),
        "bounded_workers": {"primary": primary_workers, "collaboration": max_collaboration_workers, "research": max_research_workers},
        "agentic_blackboard": agentic_blackboard,
        "models": {"default": default_model, "member_count": len(member_models), "judge": judge_model, "research": research_model},
        "warnings": [],
    }

    if judge_error:
        diagnostics["warnings"].append("Judge failed; returned fallback synthesis.")

    result = {
        "status": status,
        "tool": "hermes_omnicouncil",
        "version": VERSION,
        "preset": args.get("preset"),
        "model": default_model,
        "judge_model": judge_model,
        "member_model_count": len(member_models),
        "councils": councils,
        "members_per_council": members_per_council,
        "total_members": total_members,
        "members_responded": succeeded,
        "collaborate": collaborate,
        "collaboration_rounds": collaboration_rounds,
        "message_rounds": message_rounds,
        "messages_exchanged": len(all_messages),
        "decision_policy": decision_policy,
        "red_team": red_team,
        "agentic_blackboard": agentic_blackboard,
        "tool_mode": tool_mode,
        "capability_profile": manifest.get("capability_profile"),
        "research_missions": research_missions,
        "output_format": output_format,
        "seconds": round(time.time() - started, 1),
        "synthesis": synthesis,
        "tool_requests": tool_requests,
        "diagnostics": diagnostics,
        "editable_after": True,
    }

    if agentic_blackboard or return_blackboard:
        result["blackboard"] = {
            "policy": manifest.get("blackboard", {}),
            "summary": _blackboard_summary(answers, transcript, tool_requests, all_messages, manifest),
        }
    if all_messages:
        result["messages"] = all_messages
    if return_evidence:
        result["evidence"] = ledger
    if research_reports:
        result["research_reports"] = research_reports
    if return_transcript:
        result["transcript"] = transcript
        result["message_transcript"] = message_transcript
    if judge_error:
        result["judge_error"] = judge_error
    if succeeded < total_members:
        result["member_errors"] = [{"label": a.get("label"), "error": a.get("error")} for a in answers if a.get("status") != "success"]

    try:
        _write_json_atomic(cache_file, result)
    except Exception:
        pass
    return _json(result)


def register(ctx):
    global _RUNTIME_CTX
    _RUNTIME_CTX = ctx
    ctx.register_tool(
        name="hermes_omnicouncil",
        toolset="hermes_omnicouncil",
        schema=SCHEMA,
        handler=handler,
    )
    ctx.register_tool(
        name="deep_web_crawl",
        toolset="hermes_omnicouncil",
        schema=_deep_web_research.SCHEMA,
        handler=_deep_web_research.handler,
    )
