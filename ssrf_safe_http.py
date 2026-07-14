"""
SSRF-protected HTTP client — DNS pinning, redirect checking, streaming limits.

Правила:
- Разрешать hostname ОДИН раз.
- Проверять ВСЕ полученные IP.
- Запрещать private, loopback, link-local, reserved ranges.
- Соединяться с КОНКРЕТНЫМ проверенным IP.
- Проверять фактический peer IP ПОСЛЕ соединения.
- Обрабатывать redirects ВРУЧНУЮ.
- Читать ответ ПОТОКОВО с лимитом байтов.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
import urllib.parse
from typing import Optional

# ── Blocked ranges ──────────────────────────────────────────────────
_PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("10.0.0.0/8"),         # private
    ipaddress.ip_network("172.16.0.0/12"),      # private
    ipaddress.ip_network("192.168.0.0/16"),     # private
    ipaddress.ip_network("169.254.0.0/16"),     # link-local
    ipaddress.ip_network("224.0.0.0/4"),        # multicast
    ipaddress.ip_network("240.0.0.0/4"),        # reserved
    ipaddress.ip_network("0.0.0.0/8"),          # current network
    ipaddress.ip_network("100.64.0.0/10"),      # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),      # benchmarking
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
]

def _is_private_ip(ip_str: str) -> bool:
    """Проверить, является ли IP приватным/запрещённым."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # IPv4-mapped IPv6 → извлечь IPv4
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        for net in _PRIVATE_RANGES:
            if ip in net:
                return True
        return False
    except ValueError:
        return True  # невалидный IP → блокируем


_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript", "jar", "ldap", "php", "dict"}


def safe_resolve_host(hostname: str) -> list[str]:
    """Разрешить hostname → список публичных IP. Блокировать приватные."""
    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"dns_resolution_failed: {hostname}")
    
    ips: list[str] = []
    for fam, _, _, _, sockaddr in addrs:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise ValueError(f"private_ip_blocked: {hostname} → {ip}")
        if ip not in ips:
            ips.append(ip)
    
    if not ips:
        raise ValueError(f"no_valid_ips: {hostname}")
    return ips


def validate_url(url: str) -> tuple[str, str, int, str, str]:
    """Проверить URL: схема, блокировка private IP, порт, путь.
    Возвращает (scheme, hostname, port, path, original_host).
    """
    parsed = urllib.parse.urlparse(url)
    
    # Схема
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"blocked_scheme: {scheme}")
    if scheme in _BLOCKED_SCHEMES:
        raise ValueError(f"blocked_scheme: {scheme}")
    
    # Hostname — не должен содержать credentials или неоднозначности
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("missing_hostname")
    if "@" in hostname:
        raise ValueError("credentials_in_hostname")
    # Запретить нестандартные представления IP
    if hostname.startswith("0x") or hostname.startswith("0"):
        try:
            ipaddress.ip_address(hostname)
            raise ValueError("nonstandard_ip_representation")
        except ValueError:
            pass
    
    # Проверить что это не IP из запрещённых диапазонов
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # не IP — это hostname, проверим при resolve
    else:
        if _is_private_ip(str(ip)):
            raise ValueError(f"private_ip_direct: {hostname}")
    
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    
    return scheme, hostname, port, path, parsed.netloc


def safe_http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
    max_body_bytes: int = 10 * 1024 * 1024,  # 10 MB
    max_redirects: int = 5,
) -> tuple[int, bytes, dict[str, str]]:
    """Выполнить HTTP-запрос с защитой от SSRF/DNS rebinding.
    
    Возвращает (status_code, body_bytes, response_headers).
    """
    if max_redirects < 0:
        raise ValueError("too_many_redirects")
    
    scheme, hostname, port, path, original_netloc = validate_url(url)
    headers = dict(headers or {})
    
    # 1. Разрешить hostname ОДИН раз
    ips = safe_resolve_host(hostname)
    connect_ip = ips[0]  # использовать первый публичный IP
    
    # 2. Создать соединение с КОНКРЕТНЫМ IP
    sock = socket.create_connection((connect_ip, port), timeout=timeout)
    
    # 3. Проверить фактический peer IP
    peer_ip = sock.getpeername()[0]
    if _is_private_ip(peer_ip):
        sock.close()
        raise ValueError(f"peer_ip_private: {peer_ip}")
    if peer_ip not in ips:
        sock.close()
        raise ValueError(f"peer_ip_mismatch: expected {ips}, got {peer_ip}")
    
    # 4. TLS для HTTPS (с проверкой SNI)
    if scheme == "https":
        context = ssl.create_default_context()
        # SNI = оригинальный hostname
        sock = context.wrap_socket(sock, server_hostname=hostname)
    
    # 5. Отправить запрос
    req_line = f"{method} {path} HTTP/1.1\r\n"
    req_headers = f"Host: {original_netloc}\r\n"
    req_headers += "Connection: close\r\n"
    req_headers += f"User-Agent: Hermes-OmniCouncil/5.5.0 (SSRF-safe)\r\n"
    for k, v in headers.items():
        req_headers += f"{k}: {v}\r\n"
    if body:
        req_headers += f"Content-Length: {len(body)}\r\n"
    req_headers += "\r\n"
    
    sock.sendall(req_line.encode() + req_headers.encode())
    if body:
        sock.sendall(body)
    
    # 6. Читать ответ ПОТОКОВО с лимитом
    response = b""
    header_end = b"\r\n\r\n"
    while header_end not in response and len(response) < 65536:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    
    hdr_end = response.find(header_end)
    if hdr_end == -1:
        sock.close()
        raise ValueError("malformed_response: no header end")
    
    header_bytes = response[:hdr_end]
    body_start = hdr_end + len(header_end)
    remaining = response[body_start:]
    
    # Парсить статус и заголовки
    header_text = header_bytes.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n")
    status_line = lines[0]
    status_code = int(status_line.split(" ")[1])
    
    resp_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()
    
    # Читать тело потоково
    body_data = remaining
    while len(body_data) < max_body_bytes:
        chunk = sock.recv(8192)
        if not chunk:
            break
        body_data += chunk
    
    sock.close()
    
    # Если превышен лимит
    if len(body_data) >= max_body_bytes:
        body_data = body_data[:max_body_bytes]
    
    # 7. Обработать redirect
    if status_code in (301, 302, 303, 307, 308):
        location = resp_headers.get("location", "")
        if location:
            # Рекурсивно с полной проверкой
            if not location.startswith("http"):
                # Относительный redirect
                location = urllib.parse.urljoin(url, location)
            return safe_http_request(
                location,
                method="GET" if status_code in (301, 302, 303) else method,
                headers=headers,
                timeout=timeout,
                max_body_bytes=max_body_bytes,
                max_redirects=max_redirects - 1,
            )
    
    return status_code, body_data, resp_headers


def safe_urlopen(
    url: str,
    timeout: float = 30.0,
    max_bytes: int = 10 * 1024 * 1024,
) -> bytes:
    """Упрощённый GET с SSRF-защитой. Возвращает тело ответа."""
    status, body, _ = safe_http_request(url, timeout=timeout, max_body_bytes=max_bytes)
    if status >= 400:
        raise ValueError(f"http_error_{status}")
    return body
