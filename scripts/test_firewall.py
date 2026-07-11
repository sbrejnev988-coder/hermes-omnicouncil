#!/usr/bin/env python3
"""OmniCouncil firewall tests for CI."""
import sys
sys.path.insert(0, ".")

from firewall import resolve_safe, validate_url, is_ip_blocked

# IP blocking
assert is_ip_blocked("127.0.0.1"), "localhost should be blocked"
assert is_ip_blocked("192.168.1.1"), "private IP should be blocked"
assert not is_ip_blocked("8.8.8.8"), "public IP should be allowed"

# Path sandbox
ok, _, _ = resolve_safe("test.txt")
assert ok, "relative path should be safe"

ok2, _, _ = resolve_safe("/etc/passwd")
assert not ok2, "absolute path should be blocked"

print("FIREWALL OK")
