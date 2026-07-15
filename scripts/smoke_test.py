#!/usr/bin/env python3
"""Smoke tests for hermes-omnicouncil v5.6.1 — council-safe multi-provider council."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location(
    "hermes_omnicouncil",
    PLUGIN,
    submodule_search_locations=[str(PLUGIN.parent)],
)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules["hermes_omnicouncil"] = mod
spec.loader.exec_module(mod)

# ═══════════════════════════════════════════════════════════════
# 1. Version & constants
# ═══════════════════════════════════════════════════════════════
assert mod.VERSION == "5.6.1-council-safe", f"VERSION={mod.VERSION}"
assert mod.DEFAULT_MAX_TOKENS == 384000
assert mod.DEFAULT_JUDGE_MAX_TOKENS == 384000
assert mod.MAX_CONTEXT_CHARS == 1_000_000
assert mod.MAX_BROKERED_TOOL_REQUESTS == mod.MAX_AGENTIC_TOOL_REQUESTS * 2

# ═══════════════════════════════════════════════════════════════
# 2. COUNCIL_PRESETS — sizing only, no model_preset
# ═══════════════════════════════════════════════════════════════
for name in ["fast", "balanced", "deep", "audit", "omni_blackboard", "ultra", "max"]:
    assert name in mod.COUNCIL_PRESETS, name
assert mod.COUNCIL_PRESETS["fast"]["members"] == 3
assert mod.COUNCIL_PRESETS["deep"]["members"] == 8
# model_preset MUST NOT be in schema
assert "model_preset" not in mod.SCHEMA["parameters"]["properties"], "model_preset should be removed!"

# ═══════════════════════════════════════════════════════════════
# 3. COUNCIL_ALLOWED_TOOLS — 20 tools (user's exact spec)
# ═══════════════════════════════════════════════════════════════
assert "memory_wiki_query" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_graph_query" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_why_believe" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_get_page" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_write_firewall" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_add_claim" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_add_evidence" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_add_decision" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_add_task_capsule" in mod.COUNCIL_ALLOWED_TOOLS
assert "memory_wiki_post_task" in mod.COUNCIL_ALLOWED_TOOLS
assert "read_file" in mod.COUNCIL_ALLOWED_TOOLS
assert "search_files" in mod.COUNCIL_ALLOWED_TOOLS
assert "web_search" in mod.COUNCIL_ALLOWED_TOOLS
assert "web_extract" in mod.COUNCIL_ALLOWED_TOOLS
assert "skills_list" in mod.COUNCIL_ALLOWED_TOOLS
assert "skill_view" in mod.COUNCIL_ALLOWED_TOOLS
# web_research_brief should NOT be in COUNCIL_ALLOWED_TOOLS
assert "web_research_brief" not in mod.COUNCIL_ALLOWED_TOOLS

# ═══════════════════════════════════════════════════════════════
# 4. COUNCIL_DENIED_TOOLS — 12 tools
# ═══════════════════════════════════════════════════════════════
denied_expected = {
    "write_file", "edit_file", "apply_patch", "terminal",
    "shell", "run_command", "delete_file", "move_file",
    "rename_file", "git_commit", "git_push", "patch",
}
assert mod.COUNCIL_DENIED_TOOLS == denied_expected

# ═══════════════════════════════════════════════════════════════
# 5. MUTATION_POLICY
# ═══════════════════════════════════════════════════════════════
assert mod.MUTATION_POLICY["propose_only"] == "Models may propose patches but cannot apply them."
assert mod.MUTATION_POLICY["judge_approved"] == "Judge may approve, but executor still requires explicit user/tool approval."
assert mod.MUTATION_POLICY["operator_only"] == "Only the outer Hermes agent/operator may execute mutations."

# ═══════════════════════════════════════════════════════════════
# 6. broker_tool_call — deny mutations, allow reads
# ═══════════════════════════════════════════════════════════════
denied = mod.broker_tool_call("critic", "write_file", {"path": "x"})
assert denied["error"] == "tool_denied", denied
assert denied["tool"] == "write_file"

denied = mod.broker_tool_call("critic", "terminal", {"cmd": "rm -rf /"})
assert denied["error"] == "tool_denied", denied

denied = mod.broker_tool_call("critic", "git_push", {})
assert denied["error"] == "tool_denied"

denied = mod.broker_tool_call("critic", "apply_patch", {})
assert denied["error"] == "tool_denied"

# All 12 denied tools
for tool in mod.COUNCIL_DENIED_TOOLS:
    r = mod.broker_tool_call("test", tool, {})
    assert r.get("error") == "tool_denied", f"{tool}: {r}"

# ═══════════════════════════════════════════════════════════════
# 7. force_blackboard_namespace (v5.6.1: CouncilRunContext required)
# ═══════════════════════════════════════════════════════════════
run_ctx = mod.CouncilRunContext(
    run_id="test_run_smoke",
    session_id="test_session_42",
    namespace="omnicouncil:blackboard:test_session_42",
    model_provider_map={"deepseek-v4-pro": "deepseekproxy"},
)
args = mod.force_blackboard_namespace(run_ctx, "critic", "memory_wiki_add_claim", {"claim": "test"})
assert args["topic"] == "omnicouncil:blackboard:test_session_42"
assert args["source"] == "omnicouncil:agent:critic"
assert args["require_firewall"] is True
# Verify model-supplied values are stripped
args2 = mod.force_blackboard_namespace(run_ctx, "attacker", "memory_wiki_add_claim",
    {"claim": "malicious", "session_id": "hijacked", "topic": "private:secrets", "source": "operator"})
assert args2["topic"] == "omnicouncil:blackboard:test_session_42"
assert args2["source"] == "omnicouncil:agent:attacker"
assert "session_id" not in args2  # stripped!

# ═══════════════════════════════════════════════════════════════
# 8. Ephemeral blackboard
# ═══════════════════════════════════════════════════════════════
bb = mod._init_ephemeral_blackboard("sess_001", "security audit")
assert bb["session_id"] == "sess_001"
assert bb["task"] == "security audit"
for key in ["notes", "claims", "evidence", "file_reads", "memory_reads", "proposed_patches", "risks", "decisions"]:
    assert key in bb and isinstance(bb[key], list), key

mod._blackboard_add_entry(bb, "claim", {
    "type": "claim", "author": "critic@claude",
    "content": "test claim", "evidence": ["E1"], "confidence": 0.95
})
mod._blackboard_add_entry(bb, "risk", {
    "type": "risk", "author": "security@gpt5",
    "content": "test risk", "severity": "high"
})
assert len(bb["claims"]) == 1
assert bb["claims"][0]["confidence"] == 0.95
assert len(bb["risks"]) == 1

# ═══════════════════════════════════════════════════════════════
# 9. parse_model_ref — multi-provider parsing
# ═══════════════════════════════════════════════════════════════
prov1, mod1 = mod.parse_model_ref("openrouter:anthropic/claude-sonnet-4")
assert prov1 == "openrouter"
assert mod1 == "anthropic/claude-sonnet-4"

prov2, mod2 = mod.parse_model_ref("deepseek-v4-pro")
assert prov2 is None
assert mod2 == "deepseek-v4-pro"

prov3, mod3 = mod.parse_model_ref("custom:myproxy:local-model")
assert prov3 == "custom"
assert mod3 == "myproxy:local-model"

# ═══════════════════════════════════════════════════════════════
# 10. _parse_member_spec
# ═══════════════════════════════════════════════════════════════
spec_dict = mod._parse_member_spec({"provider": "openrouter", "model": "gpt-5.5", "role": "architect"})
assert spec_dict["provider"] == "openrouter"
assert spec_dict["model"] == "gpt-5.5"
assert spec_dict["role"] == "architect"

spec_str = mod._parse_member_spec("openrouter:deepseek/deepseek-v4-pro")
assert spec_str["provider"] == "openrouter"
assert spec_str["model"] == "deepseek/deepseek-v4-pro"

# ═══════════════════════════════════════════════════════════════
# 11. Multi-provider model resolution
# ═══════════════════════════════════════════════════════════════
default_spec, member_specs, judge_spec, research_spec = mod._resolve_models({})
# No model_preset — default is DEFAULT_MODEL
assert default_spec["model"] == mod.DEFAULT_MODEL

multi_args = {
    "members": [
        {"provider": "openrouter", "model": "anthropic/claude-sonnet-4", "role": "architect"},
        {"provider": "openrouter", "model": "openai/gpt-5.5", "role": "critic"},
        {"provider": "deepseek", "model": "deepseek-v4-pro", "role": "implementer"},
    ],
    "judge": {"provider": "openrouter", "model": "openai/gpt-5.5"},
}
d2, m2, j2, r2 = mod._resolve_models(multi_args)
assert d2["model"] == "anthropic/claude-sonnet-4"
assert d2["provider"] == "openrouter"
assert len(m2) == 3
assert m2[0]["provider"] == "openrouter"
assert m2[2]["model"] == "deepseek-v4-pro"
assert j2["provider"] == "openrouter"
assert j2["model"] == "openai/gpt-5.5"

# ═══════════════════════════════════════════════════════════════
# 12. Multi-provider call_hermes_model with FakeLLM
# ═══════════════════════════════════════════════════════════════
class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        class Usage:
            input_tokens = 50
            output_tokens = 100
            total_tokens = 150
            cost_usd = 0.001

        class Result:
            text = "ok"
            provider = kwargs.get("provider")
            model = kwargs.get("model")
            usage = Usage()

        return Result()

fake_llm = FakeLLM()
old_ctx = mod._RUNTIME_CTX
mod._RUNTIME_CTX = type("Ctx", (), {"llm": fake_llm})()

out = mod.call_hermes_model(
    "ping",
    provider="openrouter",
    model="openai/gpt-5.5",
)

assert fake_llm.calls[0]["provider"] == "openrouter", fake_llm.calls[0]
assert fake_llm.calls[0]["model"] == "openai/gpt-5.5", fake_llm.calls[0]
assert out["content"] == "ok"
assert out["provider"] == "openrouter"
assert out["model"] == "openai/gpt-5.5"

# Test without provider (uses active Hermes provider)
out2 = mod.call_hermes_model("ping", model="mythos-nano-i1-IQ3_XS")
assert fake_llm.calls[1]["model"] == "mythos-nano-i1-IQ3_XS"
assert fake_llm.calls[1]["provider"] is None

mod._RUNTIME_CTX = old_ctx

# ═══════════════════════════════════════════════════════════════
# 13. Schema keys (no model_preset, has new v5.5 params)
# ═══════════════════════════════════════════════════════════════
schema_props = mod.SCHEMA["parameters"]["properties"]
for key in [
    "model", "fallback_models", "member_models", "judge_model", "research_model",
    "tool_mode", "capability_profile",
    "allow_file_mutations", "allow_code_mutations", "critical_change_policy",
    "agentic_blackboard", "minimum_tools", "brokered_tools",
    "return_blackboard", "return_evidence", "output_format", "save_task_capsule",
    "decision_policy", "red_team", "auto_scale", "request_jitter_ms", "dry_run", "json_schema",
    "dissent_required", "anti_slop", "self_review_round",
    "plan_probe_decide", "prosecutor_round", "minimum_objections", "compiler_judge",
    "save_council_lessons", "auto_debate", "verify_chain", "debate_rounds",
    "message_rounds", "auto_capability_scan", "auto_skills", "auto_memory_context",
]:
    assert key in schema_props, f"Missing schema key: {key}"

# model_preset MUST be absent
assert "model_preset" not in schema_props
# tool_mode has council_safe
assert "council_safe" in schema_props["tool_mode"]["enum"]
# critical_change_policy has all 3 modes
assert schema_props["critical_change_policy"]["default"] == "operator_only"
assert set(schema_props["critical_change_policy"]["enum"]) == {"propose_only", "judge_approved", "operator_only"}

# ═══════════════════════════════════════════════════════════════
# 14. Tool extraction — blocks unsafe tools
# ═══════════════════════════════════════════════════════════════
reqs = mod._extract_tool_requests(
    'TOOL_REQUESTS_JSON: [{"tool":"web_search","args":{"query":"x"},"reason":"test","priority":5},{"tool":"patch","args":{"path":"x"},"reason":"bad","priority":5}]',
    10,
)
assert len(reqs) == 1 and reqs[0]["tool"] == "web_search"
assert "expected_information_gain" in reqs[0]
assert reqs[0]["mutating"] is False

mutating_reqs = mod._extract_tool_requests(
    'TOOL_REQUESTS_JSON: [{"tool":"web_search","mutating":true,"args":{"query":"x"}}]', 10
)
assert mutating_reqs == []

# ═══════════════════════════════════════════════════════════════
# 15. Blackboard/vote/message parsing
# ═══════════════════════════════════════════════════════════════
bb = mod._extract_blackboard_update('BLACKBOARD_UPDATE_JSON: {"facts":["f"],"open_questions":["q"]}')
assert bb["facts"] == ["f"]

vote = mod._extract_vote('VOTE_JSON: {"vote":"approve","confidence":0.9,"risk":"low"}')
assert vote["vote"] == "approve" and vote["risk"] == "low"

msgs = mod._extract_messages('Messages: [{"to":"C2M1","type":"question","content":"What about X?"}]')
assert len(msgs) == 1 and msgs[0]["to"] == "C2M1"

# ═══════════════════════════════════════════════════════════════
# 16. Evidence/claims/probe/compiler helpers
# ═══════════════════════════════════════════════════════════════
claims_ledger = []
claims = mod._extract_claims(
    'CLAIMS_JSON: [{"claim":"supported fact","evidence_refs":["E1"],"confidence":0.8}]', "T"
)
assert claims and claims[0]["claim"] == "supported fact"

claim_id = mod._add_claim(claims_ledger, "T", "supported fact", evidence_refs=["E1"], confidence=0.8)
assert claim_id == "C1"
assert mod._claims_summary(claims_ledger)["by_status"]["supported"] == 1

probe = mod._extract_probe_plan(
    'PROBE_PLAN_JSON: {"unknowns":["u"],"tool_requests":[{"tool":"web_search","args":{"query":"x"},"priority":5}],"risk_points":["r"],"expected_evidence":["e"]}'
)
assert probe["unknowns"] == ["u"]

compiled = mod._compile_judge_output(
    'JUDGE_COMPILED_JSON: {"verdict":"ok","confirmed_findings":["C1"],"next_step":"ship"}',
    claims_ledger, {}, {}
)
assert compiled["verdict"] == "ok"

# ═══════════════════════════════════════════════════════════════
# 17. web_research_brief smoke
# ═══════════════════════════════════════════════════════════════
mod._RUNTIME_CTX = None
brief = mod._web_research_brief("test query", 2)
assert brief["query"] == "test query"

# ═══════════════════════════════════════════════════════════════
# 18. Register — all tools registered
# ═══════════════════════════════════════════════════════════════
class FakeCtx:
    def __init__(self):
        self.tools = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

ctx = FakeCtx()
mod.register(ctx)
registered = {tool["name"]: tool for tool in ctx.tools}
assert "hermes_omnicouncil" in registered
assert "deep_web_crawl" in registered
assert "omnicouncil_doctor" in registered
assert "omnicouncil_cache_list" in registered
assert "deep_web_status" in registered
for name in ["hermes_omnicouncil", "deep_web_crawl", "omnicouncil_doctor"]:
    assert registered[name]["toolset"] == "hermes_omnicouncil"
    assert callable(registered[name]["handler"])

assert "task is required" in mod.handler(task_id="smoke")

# ═══════════════════════════════════════════════════════════════
# 19. Handler smoke with monkeypatched model calls
# ═══════════════════════════════════════════════════════════════
call_hermes_calls = []

def fake_call_hermes(prompt, *, provider=None, model=None, max_tokens=128000, temperature=0.7, retries=2, timeout=60, purpose="test"):
    call_hermes_calls.append({"provider": provider, "model": model, "purpose": purpose})
    if "финальный судья" in (prompt or ""):
        raise RuntimeError("judge synthetic failure")
    return {
        "content": f"member answer from {model or '?'}\n"
        'TOOL_REQUESTS_JSON: [{"tool":"web_search","args":{"query":"x"},"priority":4}]\n'
        'BLACKBOARD_UPDATE_JSON: {"facts":["smoke fact"],"open_questions":[]}\n'
        'VOTE_JSON: {"vote":"approve","confidence":0.8,"risk":"low"}\n'
        f'Messages: [{{"to":"C2M1","type":"question","content":"Hello from {model}"}}]',
        "provider": provider or "hermes",
        "model": model or "test",
        "usage": {"input_tokens": 10, "output_tokens": 50, "total_tokens": 60},
    }

old_call_hermes = mod.call_hermes_model
old_cache = mod.CACHE_DIR
mod.call_hermes_model = fake_call_hermes
mod.CACHE_DIR = Path("/tmp/hermes-omnicouncil-smoke-cache")
mod._RUNTIME_CTX = None
try:
    raw = mod.handler({
        "task": "smoke test multi-model v5.5",
        "context": "",
        "preset": "omni_blackboard",
        "councils": 1,
        "members_per_council": 2,
        "collaboration_rounds": 0,
        "message_rounds": 1,
        "research_missions": False,
        "auto_memory_context": False,
        "use_cache": False,
        "return_evidence": False,
        "max_member_workers": 2,
        "min_successful_members": 1,
        "request_jitter_ms": 0,
        "save_council_lessons": False,
        "tool_mode": "council_safe",
        "critical_change_policy": "operator_only",
    })
    data = json.loads(raw)
    assert data["status"] in ("partial", "success"), data
    assert data["tool"] == "hermes_omnicouncil"
    assert data["tool_mode"] == "council_safe"
    assert data.get("critical_change_policy") == "operator_only"
    assert data.get("allow_file_mutations") is False
    assert data.get("allow_code_mutations") is False
    assert data.get("messages_exchanged", -1) >= 0
    assert "tool_requests_executed" in data.get("diagnostics", {})
    assert data.get("votes", {}).get("votes")
    assert data.get("dissent_required") is False
    assert data.get("plan_probe_decide") is True
    assert data.get("compiler_judge") is True
    assert "compiled_synthesis" in data
    assert "hermes-omnicouncil" in mod.CACHE_DIR.as_posix()

    # tool_mode=off
    raw_off = mod.handler({
        "task": "tool mode off test",
        "preset": "omni_blackboard",
        "councils": 1, "members_per_council": 1,
        "collaborate": False, "message_rounds": 0,
        "research_missions": False, "auto_memory_context": False,
        "use_cache": False, "return_evidence": False,
        "tool_mode": "off",
        "request_jitter_ms": 0, "prosecutor_round": False,
    })
    data_off = json.loads(raw_off)
    assert data_off["tool_mode"] == "off"
    assert data_off["tool_requests"] == []

    # auto_debate
    raw_auto = mod.handler({
        "task": "auto debate smoke",
        "auto_debate": True,
        "councils": 1, "members_per_council": 2,
        "collaboration_rounds": 0, "message_rounds": 0,
        "research_missions": False, "auto_memory_context": False,
        "use_cache": False, "return_evidence": False,
        "request_jitter_ms": 0, "prosecutor_round": False,
        "self_review_round": False, "min_successful_members": 1,
    })
    data_auto = json.loads(raw_auto)
    assert data_auto["auto_debate"] is True
    assert data_auto["verify_chain"] is True
    assert "verify_chain_report" in data_auto

    # dry_run
    dry = json.loads(mod.handler({
        "task": "dry", "dry_run": True,
        "auto_memory_context": False, "return_evidence": False,
        "request_jitter_ms": 0,
    }))
    assert dry["status"] == "dry_run"
    assert dry["estimate"]["model_calls"] >= 1
    assert dry.get("critical_change_policy") == "operator_only"

    # auto_scale
    tiny = mod._auto_scale("hi", "")
    assert tiny["councils"] == 2
    huge = mod._auto_scale(
        "production database security auth rollback incident outage migration " * 20,
        "x" * 7000,
    )
    assert huge.get("red_team") is True

    # doctor
    doctor = json.loads(registered["omnicouncil_doctor"]["handler"]({"live_model_check": False}))
    assert doctor["status"] in ("success", "partial")

    # fast preset without blackboard
    raw2 = mod.handler({
        "task": "fast test",
        "preset": "fast",
        "councils": 1, "members_per_council": 2,
        "collaborate": False, "message_rounds": 0,
        "research_missions": False, "auto_memory_context": False,
        "use_cache": False, "return_evidence": False,
        "max_member_workers": 1, "min_successful_members": 1,
        "request_jitter_ms": 0,
    })
    data2 = json.loads(raw2)
    assert data2["status"] in ("partial", "success"), data2

    # role scheduler
    roles = mod._agentic_perspectives([])
    assert mod._member_identity(1, 0, roles, 4)[1] != mod._member_identity(0, 0, roles, 4)[1]

    # safe agent tools cover our ALLOWED tools
    assert "memory_wiki_query" in mod.SAFE_AGENT_TOOLS
    assert "patch" not in mod.SAFE_AGENT_TOOLS
    assert "write_file" not in mod.SAFE_AGENT_TOOLS
    assert "terminal" not in mod.SAFE_AGENT_TOOLS

finally:
    mod.call_hermes_model = old_call_hermes
    mod.CACHE_DIR = old_cache

print(
    f"hermes-omnicouncil {mod.VERSION} smoke ok: "
    f"tools={len(registered)} "
    f"calls={len(call_hermes_calls)} "
    f"member_count={data.get('member_model_count')} "
    f"allow_file_mutations={data.get('allow_file_mutations')} "
    f"critical_change_policy={data.get('critical_change_policy')}"
)
