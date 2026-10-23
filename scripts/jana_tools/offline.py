"""Connection monitor for the offline job (ARC-17; EVL-16 offline runs).

The offline job runs the test suite under `strace -f` inside a network namespace that has only
loopback. Any connect or send to a non-loopback address, and any DNS query (port 53, even to a
loopback stub resolver), is an egress attempt and fails the job, whether or not it succeeded.

Usage: python3 -m jana_tools.offline <strace-log>   (exit 1 and list attempts if any)
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

_INET = re.compile(r'sa_family=AF_INET, sin_port=htons\((\d+)\), sin_addr=inet_addr\("([^"]+)"\)')
_INET6 = re.compile(r'sa_family=AF_INET6, sin6_port=htons\((\d+)\),.*?inet_pton\(AF_INET6, "([^"]+)"')
_CALL = re.compile(r"^(?:\[pid\s+)?(\d+)\]?\s+(connect|sendto|sendmsg)\(")
DNS_PORT = 53


def egress_attempts(log: str) -> list[str]:
    """One line per egress attempt found in an strace log: '<pid> <call> <addr>:<port>'."""
    attempts = []
    for line in log.splitlines():
        call = _CALL.match(line)
        if not call:
            continue
        for pattern in (_INET, _INET6):
            for port_text, addr_text in pattern.findall(line):
                port = int(port_text)
                try:
                    addr = ipaddress.ip_address(addr_text)
                except ValueError:
                    attempts.append(f"{call[1]} {call[2]} {addr_text}:{port} (unparsed address)")
                    continue
                mapped = getattr(addr, "ipv4_mapped", None)
                loopback = addr.is_loopback or (mapped is not None and mapped.is_loopback)
                if not loopback or port == DNS_PORT:
                    attempts.append(f"{call[1]} {call[2]} {addr}:{port}")
    return attempts


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 -m jana_tools.offline <strace-log>", file=sys.stderr)
        return 2
    attempts = egress_attempts(Path(argv[0]).read_text(errors="replace"))
    for attempt in attempts:
        print(f"offline: egress attempt: {attempt}", file=sys.stderr)
    print(f"offline: {len(attempts)} egress attempt(s)")
    return 1 if attempts else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
