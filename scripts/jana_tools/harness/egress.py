"""In-process egress monitor for harness runs (EVL-16, D4).

A gate run must make no outbound connection. The offline CI job proves it at the operating-system level (strace in
a network namespace, `jana_tools.offline`); this monitor is the harness's own assertion inside every run, on every
machine: while it is active, a connect, send or name lookup to anything but loopback is refused and counted, and the
report of a run with any attempt is marked invalid.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


class EgressRefusedError(ConnectionRefusedError):
    """An outbound connection attempted during an offline run."""


@dataclass
class Egress:
    attempts: list[str] = field(default_factory=list)


def _loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _host(address: Any) -> Any:
    return address[0] if isinstance(address, tuple) and address else address


@contextmanager
def offline_run() -> Iterator[Egress]:
    """Refuse and record every non-loopback connect, sendto and lookup inside the block (AF_UNIX is local)."""
    seen = Egress()
    original = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
        "sendto": socket.socket.sendto,
        "getaddrinfo": socket.getaddrinfo,
    }

    def guard(kind: str, family: int, address: Any) -> None:
        if family == getattr(socket, "AF_UNIX", -1) or _loopback(_host(address)):
            return
        seen.attempts.append(f"{kind} {address}")
        raise EgressRefusedError(f"offline run: {kind} to {address} refused (EVL-16)")

    def connect(self: socket.socket, address: Any) -> None:
        guard("connect", self.family, address)
        original["connect"](self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        guard("connect", self.family, address)
        result: int = original["connect_ex"](self, address)
        return result

    def sendto(self: socket.socket, data: bytes, *args: Any) -> int:
        guard("sendto", self.family, args[-1])
        result: int = original["sendto"](self, data, *args)
        return result

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _loopback(host):
            seen.attempts.append(f"lookup {host}")
            raise EgressRefusedError(f"offline run: name lookup of {host} refused (EVL-16)")
        return original["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socket.sendto = sendto  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = getaddrinfo
    try:
        yield seen
    finally:
        socket.socket.connect = original["connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = original["connect_ex"]  # type: ignore[method-assign]
        socket.socket.sendto = original["sendto"]  # type: ignore[method-assign]
        socket.getaddrinfo = original["getaddrinfo"]
