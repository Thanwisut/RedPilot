"""Shared structured output types produced by tool adapters.

These are the types that agents reason over — never raw tool output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenPort:
    """A single discovered open port on a scanned host.

    Attributes:
        port: Port number (1-65535).
        protocol: Transport protocol (tcp, udp).
        state: Port state (open, filtered, closed, unfiltered).
        service: Service name guessed by nmap (e.g., "http", "ssh").
        version: Version string from service detection, if available.
    """

    port: int
    protocol: str = "tcp"
    state: str = "open"
    service: str | None = None
    version: str | None = None


@dataclass
class PortScanResult:
    """Structured result from a port scan tool (nmap, masscan, etc.).

    Attributes:
        target: The scanned target (host/CIDR).
        ports: List of discovered open ports.
        total_hosts: Total hosts that responded to the scan.
        open_ports_count: Total number of open ports found.
        scan_stats: Arbitrary key-value metadata about the scan run.
    """

    target: str
    ports: list[OpenPort] = field(default_factory=list)
    total_hosts: int = 0
    open_ports_count: int = 0
    scan_stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestValidationError:
    """Details about a validation failure when parsing a tool manifest."""

    field: str
    reason: str
    value: object | None = None
