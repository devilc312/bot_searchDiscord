# Copyright (C) 2026 devilc312
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chặn SSRF: bot chỉ được tải URL công khai, không được chạm mạng nội bộ hay metadata cloud.

Giới hạn đã biết: kiểm tra DNS rồi mới tải nên vẫn có khe hở DNS rebinding.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"metadata.google.internal", "metadata.goog", "localhost"}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)
    )


def is_safe_url(url: str, resolver=socket.getaddrinfo) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    if p.username or p.password:  # chặn user:pass@host
        return False
    host = p.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not _ip_is_blocked(ip)
    except ValueError:
        pass
    try:
        infos = resolver(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    ips = {i[4][0] for i in infos}
    if not ips:
        return False
    return all(not _ip_is_blocked(ipaddress.ip_address(x.split("%")[0])) for x in ips)
