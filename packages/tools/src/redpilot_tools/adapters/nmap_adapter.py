"""Nmap adapter — the reference ``ToolAdapter`` implementation.

Translates logical arguments into an nmap argv, parses XML output
into ``PortScanResult``, and enforces safe defaults.

**Key safety properties** (see spec §3.2):
- Always emits ``-oX -`` (XML to stdout) — never parses human-readable output.
- ``scan_type`` mapped from a fixed allowlist (``-sS`` / ``-sT`` / ``-sU``).
- ``timing_template`` mapped from a fixed allowlist (``-T2`` / ``-T3`` / ``-T4``).
- ``--max-rate`` always appended from the manifest's rate limit, agent cannot override.
- No ``-oN``, ``-oG``, ``--script`` flags ever emitted in v1 (NSE is a separate tool).
- Target validated syntactically before being placed in argv.
"""

from __future__ import annotations

import ipaddress
import re
import xml.etree.ElementTree as ET
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter

# Fixed allowlists — no agent-supplied string is ever passed directly to -s or -T.
_SCAN_TYPE_FLAGS: dict[str, str] = {
    "syn": "-sS",
    "connect": "-sT",
    "udp": "-sU",
}

_TIMING_FLAGS: dict[str, str] = {
    "T2": "-T2",
    "T3": "-T3",
    "T4": "-T4",
}

_VALID_TARGET_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$"
)

NMAP_MANIFEST = ToolManifest(
    name="nmap",
    category="port_scan",
    binary="nmap",
    version_pinned=">=7.90,<8.0",
    input_schema={
        "target": {"type": "string", "required": True},
        "ports": {"type": "string", "required": False},
        "scan_type": {
            "type": "enum",
            "required": False,
            "values": ["syn", "connect", "udp"],
        },
        "service_detection": {"type": "bool", "required": False},
        "timing_template": {
            "type": "enum",
            "required": False,
            "values": ["T2", "T3", "T4"],
        },
    },
    output_parser="nmap_xml_parser",
    sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD,
    requires_approval=False,
    dangerous=False,
    rate_limit={"requests_per_sec": 100},
    description="Network exploration tool and security / port scanner",
)


class NmapAdapter(ToolAdapter):
    """Adapter for nmap port scanning."""

    manifest = NMAP_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build an nmap argv from logical arguments.

        The command is always built as a ``list[str]`` — never a shell string.
        Every flag is mapped from a fixed allowlist; no raw agent input is
        ever placed directly into argv as a flag name.
        """
        argv: list[str] = ["nmap"]

        # -- Scan type (default: connect scan -sT)
        scan_type = args.get("scan_type", "connect")
        flag = _SCAN_TYPE_FLAGS.get(scan_type)
        if flag:
            argv.append(flag)
        else:
            argv.append("-sT")

        # -- Always output XML to stdout
        argv.append("-oX")
        argv.append("-")

        # -- Ports (optional, default: top 1000)
        ports = args.get("ports")
        if ports:
            argv.append("-p")
            argv.append(str(ports))

        # -- Service detection (optional, slower but more accurate)
        if args.get("service_detection", False):
            argv.append("-sV")

        # -- Timing template (default T3)
        timing = args.get("timing_template", "T3")
        timing_flag = _TIMING_FLAGS.get(timing)
        if timing_flag:
            argv.append(timing_flag)
        else:
            argv.append("-T3")

        # -- Rate limit (always applied from manifest, agent cannot override)
        rate_limit = self.manifest.rate_limit
        if rate_limit and "requests_per_sec" in rate_limit:
            argv.append("--max-rate")
            argv.append(str(rate_limit["requests_per_sec"]))

        # -- Target (validated syntactically before insertion)
        target = args.get("target", "")
        self._validate_target(target)
        argv.append(target)

        return argv

    def parse_output(
        self,
        stdout: str,
        stderr: str,  # noqa: ARG002
        exit_code: int,
        scratch_dir: str,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Parse nmap XML output into a structured ``PortScanResult``.

        Args:
            stdout: nmap XML output (from ``-oX -``).
            stderr: nmap stderr (warnings, error messages).
            exit_code: Process exit code (0 = success).
            scratch_dir: Path to scratch directory (unused — nmap output
                         comes via stdout).

        Returns:
            A dict with keys ``ports``, ``total_hosts``, ``open_ports_count``,
            ``scan_stats``. Returns an empty result on parse failure.
        """
        result: dict[str, Any] = {
            "ports": [],
            "total_hosts": 0,
            "open_ports_count": 0,
            "scan_stats": {},
        }

        if not stdout.strip():
            return result

        try:
            root = ET.fromstring(stdout)
        except ET.ParseError:
            return result

        # Extract scan stats
        scanner_elem = root.find("scaninfo")
        if scanner_elem is not None:
            result["scan_stats"]["type"] = scanner_elem.get("type", "")
            result["scan_stats"]["protocol"] = scanner_elem.get("protocol", "")

        # Extract run stats
        run_stats = root.find("runstats")
        if run_stats is not None:
            hosts_elem = run_stats.find("hosts")
            if hosts_elem is not None:
                result["total_hosts"] = int(hosts_elem.get("total", "0"))
                result["open_ports_count"] = int(hosts_elem.get("up", "0"))

        # Extract open ports from each host (exclude filtered/closed)
        ports: list[dict[str, Any]] = []
        for host in root.findall("host"):
            host_status = host.find("status")
            if host_status is not None and host_status.get("state") != "up":
                continue

            for port_elem in host.findall(".//port"):
                port_state = port_elem.find("state")
                if port_state is None:
                    continue

                port_state_str = port_state.get("state", "unknown")
                # Only include open ports — filtered/closed are excluded (§3.3)
                if port_state_str != "open":
                    continue

                port_dict: dict[str, Any] = {
                    "port": int(port_elem.get("portid", "0")),
                    "protocol": port_elem.get("protocol", "tcp"),
                    "state": port_state_str,
                }

                service = port_elem.find("service")
                if service is not None:
                    port_dict["service"] = service.get("name", "")
                    port_dict["version"] = service.get("version", "")
                    if product := service.get("product", ""):
                        port_dict["service_product"] = product

                ports.append(port_dict)

        result["ports"] = ports
        result["open_ports_count"] = len(ports)

        return result

    def required_capabilities(self, args: dict[str, Any]) -> list[str]:
        """SYN scans require ``NET_RAW`` for raw socket access."""
        if args.get("scan_type") == "syn":
            return ["NET_RAW"]
        return []

    def check_version(self, detected_version: str) -> bool:
        """Check nmap version against ``>=7.90,<8.0``.

        Overrides the default equality check with range matching.
        """
        if self.manifest.version_pinned is None:
            return True
        return _satisfies_semver_range(detected_version, self.manifest.version_pinned)

    def _validate_target(self, target: str) -> None:
        """Validate that *target* is a syntactically valid host/CIDR/hostname.

        Raises ``ValueError`` if the target is malformed. This is defense-in-depth
        alongside the argv-list-not-shell-string rule.
        """
        if not target:
            msg = "Target is required"
            raise ValueError(msg)

        # Check if it's a valid IP or CIDR
        try:
            ipaddress.ip_network(target, strict=False)
            return
        except ValueError:
            pass

        # Check if it's a valid hostname (basic sanity)
        if not _VALID_TARGET_RE.match(target):
            msg = f"Target '{target}' is not a valid hostname, IP, or CIDR"
            raise ValueError(msg)

        if len(target) > 253:
            msg = f"Target '{target}' exceeds maximum hostname length"
            raise ValueError(msg)


def _satisfies_semver_range(version: str, range_spec: str) -> bool:
    """Check if *version* satisfies a simple semver range like ``>=7.90,<8.0``.

    Supports comma-separated constraints with ``>=``, ``<=``, ``>``, ``<``, ``==``.
    Only handles major.minor.patch with optional leading ``v``.
    """
    try:
        parsed = _parse_version(version)
    except ValueError:
        return False

    constraints = [c.strip() for c in range_spec.split(",")]
    return all(
        _check_constraint(parsed, constraint)
        for constraint in constraints
    )


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string like ``7.94`` or ``v7.94`` into a tuple of ints."""
    cleaned = version.lstrip("v")
    return tuple(int(p) for p in cleaned.split("."))


def _check_constraint(parsed: tuple[int, ...], constraint: str) -> bool:
    """Check a single constraint like ``>=7.90`` against a parsed version."""
    if constraint.startswith(">="):
        target = _parse_version(constraint[2:])
        return parsed >= target
    if constraint.startswith("<="):
        target = _parse_version(constraint[2:])
        return parsed <= target
    if constraint.startswith(">"):
        target = _parse_version(constraint[1:])
        return parsed > target
    if constraint.startswith("<"):
        target = _parse_version(constraint[1:])
        return parsed < target
    if constraint.startswith("=="):
        target = _parse_version(constraint[2:])
        return parsed == target
    if constraint.startswith("="):
        target = _parse_version(constraint[1:])
        return parsed == target
    # Bare version equality
    target = _parse_version(constraint)
    return parsed == target
