#!/usr/bin/env python3
"""Verify OmniCouncil tools registration in plugin.yaml."""
import yaml
import sys

with open("plugin.yaml") as f:
    p = yaml.safe_load(f)

tools = p.get("provides_tools", [])
print(f"Registered tools: {len(tools)}")
print(f"Version: {p.get('version')}")

if not tools:
    print("WARNING: no tools registered!")
    sys.exit(1)

print("OK: " + ", ".join(tools[:5]) + ("..." if len(tools) > 5 else ""))
