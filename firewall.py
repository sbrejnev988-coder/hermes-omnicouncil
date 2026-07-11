"""
OmniCouncil Firewall — File sandbox + SSRF protection.

- File reads/blocks: restricts to workspace, blocks .. traversal, symlinks, absolute paths
- SSRF: validates URLs/IPs after redirects, blocks localhost/private/link-local/DNS rebinding
- Minimal dependencies: stdlib only (urllib, ipaddress, socket, os.path)
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, List


# ═══════════════════════════════════════════════════════════════
#  FILE SANDBOX
# ═══════════════════════════════════════════════════════════════

# Default workspace — override via FIRESHIELD_WORKSPACE env
_DEFAULT_WORKSPACE = Path(os.environ.get("HERMES_WORKSPACE", os.path.expanduser("~/.hermes/workspace"))).resolve()

def set_workspace(path: str | Path) -> None:
    """Override the allowed workspace root."""
    global _DEFAULT_WORKSPACE
    _DEFAULT_WORKSPACE = Path(path).resolve()

def get_workspace() -> Path:
    return _DEFAULT_WORKSPACE

def resolve_safe(path: str | Path) -> Tuple[bool, Path, str]:
    """Resolve a file path and check it is inside the workspace.

    Returns (safe: bool, resolved_path: Path, reason: str).
    Blocks:
      - Absolute paths not under workspace
      - .. traversal escaping workspace
      - Symlinks pointing outside workspace
    """
    try:
        p = Path(str(path))
    except Exception:
        return False, Path("."), "invalid path"

    # Expand ~
    try:
        p = p.expanduser()
    except Exception:
        return False, Path("."), "path expansion failed"

    # Reject empty
    if str(p).strip() == "":
        return False, Path("."), "empty path"

    # If relative, resolve against workspace
    if not p.is_absolute():
        p = (_DEFAULT_WORKSPACE / p)

    # Resolve symlinks and ..
    try:
        resolved = p.resolve(strict=False)
    except Exception:
        return False, p, "path resolution failed"

    # Check inside workspace
    try:
        resolved.relative_to(_DEFAULT_WORKSPACE)
    except ValueError:
        return False, resolved, f"path outside workspace: {resolved}"

    # Check symlink target (if it exists)
    if p.exists() and p.is_symlink():
        try:
            target = p.readlink()
            target_resolved = (p.parent / target).resolve()
            target_resolved.relative_to(_DEFAULT_WORKSPACE)
        except ValueError:
            return False, resolved, f"symlink target outside workspace: {target}"
        except Exception:
            return False, resolved, "symlink resolution failed"

    return True, resolved, "ok"


def safe_read_file(path: str, offset: int = 1, limit: int = 500) -> dict:
    """Read file with workspace sandbox. Returns {ok, content/path/error}."""
    safe, resolved, reason = resolve_safe(path)
    if not safe:
        return {"ok": False, "error": f"firewall_blocked: {reason}", "path": str(resolved)}

    if not resolved.exists():
        return {"ok": False, "error": "file_not_found", "path": str(resolved)}
    if not resolved.is_file():
        return {"ok": False, "error": "not_a_file", "path": str(resolved)}

    try:
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        body = "\n".join(f"{offset + idx}|{line}" for idx, line in enumerate(selected))
        return {"ok": True, "source": "local_file", "path": str(resolved),
                "content": body[:100000], "total_lines": len(lines)}
    except Exception as e:
        return {"ok": False, "error": f"read_error: {e}", "path": str(resolved)}


def safe_search_files(pattern: str, path: str = ".") -> dict:
    """Search files with workspace sandbox. Returns {ok, matches/error}."""
    safe, resolved_dir, reason = resolve_safe(path)
    if not safe:
        return {"ok": False, "error": f"firewall_blocked: {reason}"}

    if not resolved_dir.exists():
        return {"ok": False, "error": "directory_not_found"}

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": f"invalid_regex: {e}"}

    matches = []
    search_dir = resolved_dir if resolved_dir.is_dir() else resolved_dir.parent
    for root, _, files in os.walk(str(search_dir)):
        for fname in files:
            full = Path(root) / fname
            # Re-check sandbox for every file
            f_safe, _, _ = resolve_safe(str(full))
            if not f_safe:
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                if regex.search(content):
                    matches.append(str(full.relative_to(_DEFAULT_WORKSPACE)))
            except Exception:
                continue

    return {"ok": True, "matches": matches[:50], "total": len(matches)}


# ═══════════════════════════════════════════════════════════════
#  SSRF PROTECTION
# ═══════════════════════════════════════════════════════════════

# Blocked networks
_BLOCKED_NETWORKS: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("127.0.0.0/8"),       # loopback
    ipaddress.IPv4Network("10.0.0.0/8"),         # private
    ipaddress.IPv4Network("172.16.0.0/12"),      # private
    ipaddress.IPv4Network("192.168.0.0/16"),     # private
    ipaddress.IPv4Network("169.254.0.0/16"),     # link-local
    ipaddress.IPv4Network("0.0.0.0/8"),          # "This" network
    ipaddress.IPv4Network("224.0.0.0/4"),        # multicast
    ipaddress.IPv4Network("240.0.0.0/4"),        # reserved
    ipaddress.IPv6Network("::1/128"),             # IPv6 loopback
    ipaddress.IPv6Network("fe80::/10"),           # link-local
    ipaddress.IPv6Network("fc00::/7"),            # unique local
]

# Blocked hostname suffixes
_BLOCKED_SUFFIXES = [".local", ".localhost", ".internal"]


def is_ip_blocked(ip_str: str) -> bool:
    """Check if IP is in blocked networks (localhost/private/link-local)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse → block
    return any(ip in net for net in _BLOCKED_NETWORKS)


def is_hostname_blocked(hostname: str) -> bool:
    """Check if hostname resolves to blocked IP, or has blocked suffix."""
    hostname_lower = hostname.lower()
    for suffix in _BLOCKED_SUFFIXES:
        if hostname_lower.endswith(suffix):
            return True

    # DNS rebinding check: resolve and verify
    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for addr in addrs:
            ip = addr[4][0]
            if is_ip_blocked(ip):
                return True
    except socket.gaierror:
        return True  # can't resolve → block
    except Exception:
        return True

    return False


def validate_url(url: str, allow_redirect: bool = True) -> Tuple[bool, str, str]:
    """Validate URL against SSRF firewall.

    Returns (safe: bool, normalized_url: str, reason: str).
    Checks:
      - scheme is http/https
      - hostname not blocked
      - IP not in blocked networks
      - DNS rebinding (hostname resolves to blocked IP)
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, url, "invalid URL"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, url, f"blocked scheme: {scheme}"

    hostname = parsed.hostname or ""
    if not hostname:
        return False, url, "missing hostname"

    # Check if it's a raw IP (not hostname like example.com)
    try:
        ipaddress.ip_address(hostname)
        # It IS an IP — block if private/local
        if is_ip_blocked(hostname):
            return False, url, f"blocked IP: {hostname}"
    except ValueError:
        # Not an IP — it's a hostname, check via DNS
        pass

    # Check hostname
    if is_hostname_blocked(hostname):
        return False, url, f"blocked hostname: {hostname}"

    return True, url, "ok"


def safe_urlopen(url: str, timeout: float = 30.0, max_redirects: int = 5) -> Tuple[bool, dict]:
    """Fetch URL with SSRF protection and redirect following.

    Returns (ok: bool, result: dict).
    Checks firewall on initial URL AND after every redirect.
    """
    import urllib.request
    import urllib.error

    current_url = url
    redirect_count = 0

    while redirect_count <= max_redirects:
        safe, _, reason = validate_url(current_url)
        if not safe:
            return False, {"error": f"firewall_blocked: {reason}", "url": current_url}

        try:
            req = urllib.request.Request(current_url, headers={
                "User-Agent": "OmniCouncil-Firewall/1.0"
            })

            # Don't follow redirects automatically — we validate each one
            opener = urllib.request.build_opener(
                urllib.request.HTTPRedirectHandler()
            )
            # Override to NOT follow redirects automatically
            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(NoRedirectHandler())

            with opener.open(req, timeout=timeout) as resp:
                # Handle redirects — validate each target URL
                if resp.status in (301, 302, 303, 307, 308):
                    new_url = resp.headers.get("Location", "")
                    if not new_url:
                        return False, {"error": "redirect without Location header"}
                    current_url = urllib.parse.urljoin(current_url, new_url)
                    safe_rd, _, reason_rd = validate_url(current_url)
                    if not safe_rd:
                        return False, {"error": f"SSRF blocked redirect: {reason_rd}", "url": current_url}
                    redirect_count += 1
                    continue

                data = resp.read().decode("utf-8", errors="replace")
                return True, {
                    "ok": True,
                    "status": resp.status,
                    "url": current_url,
                    "content": data[:50000],
                    "content_type": resp.headers.get("Content-Type", ""),
                }

        except urllib.error.HTTPError as e:
            return False, {"error": f"HTTP {e.code}: {e.reason}", "url": current_url}
        except urllib.error.URLError as e:
            return False, {"error": f"URL error: {e.reason}", "url": current_url}
        except Exception as e:
            return False, {"error": str(e), "url": current_url}

    return False, {"error": f"too many redirects ({max_redirects})", "url": current_url}


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION: require_firewall gate
# ═══════════════════════════════════════════════════════════════

class FirewallGate:
    """Central gate for all council file/network operations."""

    def __init__(self, require_firewall: bool = True, workspace: str | None = None):
        self.require_firewall = require_firewall
        if workspace:
            set_workspace(workspace)

    def file_read(self, path: str, offset: int = 1, limit: int = 500) -> dict:
        if not self.require_firewall:
            # Passthrough — legacy mode
            p = Path(path).expanduser()
            if not p.exists() or not p.is_file():
                return {"ok": False, "error": "file_not_found"}
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[offset - 1 : offset - 1 + limit]
            body = "\n".join(f"{offset + idx}|{line}" for idx, line in enumerate(selected))
            return {"ok": True, "path": str(p), "content": body[:100000], "total_lines": len(lines)}
        return safe_read_file(path, offset, limit)

    def fetch_url(self, url: str, timeout: float = 30.0) -> dict:
        if not self.require_firewall:
            # Legacy passthrough
            import urllib.request
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return {"ok": True, "content": r.read().decode("utf-8", errors="replace")[:50000]}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        ok, result = safe_urlopen(url, timeout)
        return result if ok else {"ok": False, **result}
