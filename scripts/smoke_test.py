#!/usr/bin/env python3
"""Smoke tests for hermes-omnicouncil v5.2.0 agentic tooling layer."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
spec = importlib.util.spec_from_file_location("hermes_omnicouncil_smoke", PLUGIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert mod.VERSION == "5.2.0-agentic-tools-deepseek-default"
assert mod.DEFAULT_MODEL == "deepseek-v4-pro"
assert mod.DEFAULT_MAX_TOKENS == 384000
assert mod.DEFAULT_JUDGE_MAX_TOKENS == 384000
assert mod.MAX_CONTEXT_CHARS == 1_000_000
assert mod.MAX_BROKERED_TOOL_REQUESTS == mod.MAX_AGENTIC_TOOL_REQUESTS * 2
assert "omni_blackboard" in mod.CONSILIUM_PRESETS
assert mod.SAFE_AGENT_TOOLS
assert "web_search" in mod.SAFE_AGENT_TOOLS
assert "patch" not in mod.SAFE_AGENT_TOOLS
assert "write_file" not in mod.SAFE_AGENT_TOOLS
assert "terminal" not in mod.SAFE_AGENT_TOOLS

# model presets
assert "deepseek" in mod.MODEL_PRESETS
assert "gpt55" in mod.MODEL_PRESETS
assert "mixed" in mod.MODEL_PRESETS

# v5 new presets
assert "ultra" in mod.CONSILIUM_PRESETS

# preset defaults
scaled = mod._apply_preset_defaults({"preset": "omni_blackboard", "task": "test", "context": ""})
assert scaled["agentic_blackboard"] is True
assert scaled["minimum_tools"] is True
assert scaled["capability_profile"] == "omni"
assert scaled["message_rounds"] == 2

# model resolution
default0, members0, judge0, research0 = mod._resolve_models({})
assert default0 == "deepseek-v4-pro"
assert members0 == ["deepseek-v4-pro"]
assert judge0 == "deepseek-v4-pro"
assert research0 == "deepseek-v4-pro"
assert mod.SCHEMA["parameters"]["properties"]["model"]["default"] == "deepseek-v4-pro"
assert mod.SCHEMA["parameters"]["properties"]["model_preset"]["default"] == "deepseek"

default, members, judge, research = mod._resolve_models({"model_preset": "mixed"})
assert default == "deepseek-v4-pro" or default
assert len(members) == 4
assert judge == "gpt-5.5"
assert research == "deepseek-v4-pro"

# schema keys
for key in [
    "model", "model_preset", "fallback_models", "member_models", "judge_model", "research_model",
    "message_rounds",
    "tool_mode", "capability_profile", "auto_capability_scan", "auto_skills",
    "agentic_blackboard", "minimum_tools", "brokered_tools",
    "return_blackboard", "return_evidence", "output_format", "save_task_capsule",
    "decision_policy", "red_team", "auto_scale", "request_jitter_ms", "dry_run", "json_schema",
    "dissent_required", "anti_slop", "self_review_round",
]:
    assert key in mod.SCHEMA["parameters"]["properties"], key

# tool extraction — blocks unsafe tools
reqs = mod._extract_tool_requests(
    'TOOL_REQUESTS_JSON: [{"tool":"web_search","args":{"query":"x"},"reason":"test","priority":5},{"tool":"patch","args":{"path":"x"},"reason":"bad","priority":5}]',
    10,
)
assert len(reqs) == 1 and reqs[0]["tool"] == "web_search"
assert "expected_information_gain" in reqs[0]
assert reqs[0]["mutating"] is False

mutating_reqs = mod._extract_tool_requests('TOOL_REQUESTS_JSON: [{"tool":"web_search","mutating":true,"args":{"query":"x"}}]', 10)
assert mutating_reqs == []

weak = mod._dedupe_tool_requests([{"label":"C1M1", "tool_requests":[{"tool":"web_search","args":{"query":"x"},"priority":1}]}], 10, minimum_tools=True)
assert weak and weak[0].get("weak_request") is True

# structured blackboard/vote parsing
bb = mod._extract_blackboard_update('BLACKBOARD_UPDATE_JSON: {"facts":["f"],"open_questions":["q"]}')
assert bb["facts"] == ["f"]
vote = mod._extract_vote('VOTE_JSON: {"vote":"approve","confidence":0.9,"risk":"low"}')
assert vote["vote"] == "approve" and vote["risk"] == "low"

# message extraction
msgs = mod._extract_messages('Messages: [{"to":"C2M1","type":"question","content":"What about X?"}]')
assert len(msgs) == 1 and msgs[0]["to"] == "C2M1"

# web_research_brief smoke (doesn't call real tools — safe)
# Just verify the function exists and handles empty results gracefully
mod._RUNTIME_CTX = None
brief = mod._web_research_brief("test query", 2)
assert brief["query"] == "test query"

# register check
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
assert registered["hermes_omnicouncil"]["toolset"] == "hermes_omnicouncil"
assert registered["deep_web_crawl"]["toolset"] == "hermes_omnicouncil"
assert registered["omnicouncil_doctor"]["toolset"] == "hermes_omnicouncil"
assert callable(registered["hermes_omnicouncil"]["handler"])
assert callable(registered["deep_web_crawl"]["handler"])
assert callable(registered["omnicouncil_doctor"]["handler"])
assert "task is required" in mod.handler(task_id="smoke")

# handler smoke with monkeypatched model calls
calls = []
def fake_call_model(model, prompt, max_tokens=128000, temperature=0.7, retries=2, timeout=60, reasoning_effort=None):
    calls.append((model, temperature, timeout))
    if "финальный судья" in (prompt or ""):
        raise RuntimeError("judge synthetic failure")
    return {"content": f"member answer from {model}\nTOOL_REQUESTS_JSON: [{{\"tool\":\"web_search\",\"args\":{{\"query\":\"x\"}},\"priority\":4}}]\nBLACKBOARD_UPDATE_JSON: {{\"facts\":[\"smoke fact\"],\"open_questions\":[]}}\nVOTE_JSON: {{\"vote\":\"approve\",\"confidence\":0.8,\"risk\":\"low\"}}\nMessages: [{{\"to\":\"C2M1\",\"type\":\"question\",\"content\":\"Hello from {model}\"}}]"}

old_call = mod.call_model
old_cache = mod.CACHE_DIR
mod.call_model = fake_call_model
mod.CACHE_DIR = Path("/tmp/hermes-omnicouncil-smoke-cache")
mod._RUNTIME_CTX = None
try:
    raw = mod.handler({
        "task": "smoke test multi-model",
        "context": "",
        "model_preset": "mixed",
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
    })
    data = json.loads(raw)
    assert data["status"] in ("partial", "success"), data
    assert data["tool"] == "hermes_omnicouncil"
    assert data.get("messages_exchanged", -1) >= 0
    assert data.get("message_rounds") == 1
    assert "tool_requests_executed" in data.get("diagnostics", {})
    assert data.get("votes", {}).get("votes")
    assert data.get("dissent_required") is False
    assert data.get("fallback_models") == []
    assert "hermes-omnicouncil" in mod.CACHE_DIR.as_posix()

    raw_off = mod.handler({
        "task": "tool mode off test",
        "context": "",
        "preset": "omni_blackboard",
        "councils": 1,
        "members_per_council": 1,
        "collaborate": False,
        "message_rounds": 0,
        "research_missions": False,
        "auto_memory_context": False,
        "use_cache": False,
        "return_evidence": False,
        "tool_mode": "off",
        "request_jitter_ms": 0,
    })
    data_off = json.loads(raw_off)
    assert data_off["tool_mode"] == "off"
    assert data_off["tool_requests"] == []

    # dry-run budget estimate
    dry = json.loads(mod.handler({"task":"dry", "dry_run": True, "auto_memory_context": False, "return_evidence": False, "request_jitter_ms": 0}))
    assert dry["status"] == "dry_run" and dry["estimate"]["model_calls"] >= 1

    # auto-scale reaches fast and red-team tiers
    tiny = mod._auto_scale("hi", "")
    assert tiny["councils"] == 2
    huge = mod._auto_scale("production database security auth rollback incident outage migration " * 20, "x" * 7000)
    assert huge.get("red_team") is True

    # role scheduler uses council offset, not only member index
    roles = mod._agentic_perspectives([])
    assert mod._member_identity(1, 0, roles, 4)[1] != mod._member_identity(0, 0, roles, 4)[1]

    # doctor smoke
    doctor = json.loads(registered["omnicouncil_doctor"]["handler"]({"live_model_check": False}))
    assert doctor["status"] in ("success", "partial")

    # presets without blackboard
    raw2 = mod.handler({
        "task": "fast test",
        "context": "",
        "preset": "fast",
        "councils": 1,
        "members_per_council": 2,
        "collaborate": False,
        "message_rounds": 0,
        "research_missions": False,
        "auto_memory_context": False,
        "use_cache": False,
        "return_evidence": False,
        "max_member_workers": 1,
        "min_successful_members": 1,
        "request_jitter_ms": 0,
    })
    data2 = json.loads(raw2)
    assert data2["status"] in ("partial", "success"), data2
finally:
    mod.call_model = old_call
    mod.CACHE_DIR = old_cache

print(f"hermes-omnicouncil v5.2.0 smoke ok: tools={len(registered)} calls={len(calls)} member_models={data.get('member_model_count')} messages_rounds={data.get('message_rounds')}")
