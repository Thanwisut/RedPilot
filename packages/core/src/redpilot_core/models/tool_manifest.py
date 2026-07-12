"""Domain model for tool manifests — how tools are registered and discovered.

Each tool is defined by a manifest in the tools/ directory. The Tool
Execution Layer scans these manifests at startup to build a runtime
capability index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SandboxProfile(Enum):
    """Sandboxing constraints for tool execution.

    Each profile defines a set of resource limits, network egress policies,
    and filesystem access rules that the sandbox runner enforces.
    """

    NETWORK_SCAN_STANDARD = "network_scan_standard"
    """Standard network scanning tools (nmap, masscan). Network access
    scoped to declared targets only. Modest CPU/memory."""

    WEB_SCAN = "web_scan"
    """Web application scanners (nuclei, ffuf, sqlmap). HTTP/S access to
    web targets. Higher connection count than standard."""

    EXPLOIT = "exploit"
    """Exploitation frameworks (Metasploit, custom exploits). Network access
    to targets, elevated risk profile. Always requires approval gate."""

    CODE_ANALYSIS = "code_analysis"
    """Static analysis tools. No network access. Filesystem access to
    the provided source code only."""

    BROWSER = "browser"
    """Browser automation (Playwright). Full HTTPS access but executed
    in a container with no persistent storage access."""


@dataclass
class ToolManifest:
    """Declarative definition of a tool's capabilities and constraints.

    Attributes:
        name: Canonical tool name (e.g., "nmap", "nuclei", "sqlmap").
        category: Functional category (e.g., "vulnerability_scan", "recon").
        binary: Path or name of the system binary (None for pure-Python tools).
        version_pinned: Expected tool version string (matched at startup).
        input_schema: JSON Schema-like dict describing allowed arguments.
        output_parser: Name of the registered output parser class/adapter.
        sandbox_profile: Which sandbox constraints to apply.
        requires_approval: Whether this tool always needs human approval,
            regardless of permission level.
        rate_limit: Rate limiting policy (e.g., {"requests_per_sec": 50}).
        dangerous: Whether this tool is classified as dangerous (RCE-capable,
            AD attack tooling, Metasploit, etc.). Always requires approval.
        description: Human-readable description of what this tool does.
    """

    name: str
    category: str = "general"
    binary: str | None = None
    version_pinned: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_parser: str | None = None
    sandbox_profile: SandboxProfile = SandboxProfile.NETWORK_SCAN_STANDARD
    requires_approval: bool = False
    rate_limit: dict[str, Any] | None = None
    dangerous: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        """Enforce manifest invariants."""
        if self.dangerous:
            self.requires_approval = True

    @property
    def effective_permission_level(self) -> str:
        """The permission level required to use this tool.

        Dangerous tools always require DANGEROUS-level permission.
        Tools with requires_approval require WRITE-level or above.
        All other tools are READ_ONLY.
        """
        if self.dangerous:
            return "dangerous"
        if self.requires_approval:
            return "write"
        return "read_only"

    def to_manifest_entry(self) -> dict[str, Any]:
        """Serialize to a dict matching the YAML manifest format in the design doc."""
        return {
            "name": self.name,
            "category": self.category,
            "binary": self.binary,
            "version_pinned": self.version_pinned,
            "input_schema": self.input_schema,
            "output_parser": self.output_parser,
            "sandbox_profile": self.sandbox_profile.value,
            "requires_approval": self.requires_approval,
            "rate_limit": self.rate_limit,
            "dangerous": self.dangerous,
            "description": self.description,
        }

    @classmethod
    def from_manifest_entry(cls, data: dict[str, Any]) -> ToolManifest:
        """Create from a dict (deserialized from YAML/JSON manifest file)."""
        return cls(
            name=data["name"],
            category=data.get("category", "general"),
            binary=data.get("binary"),
            version_pinned=data.get("version_pinned"),
            input_schema=data.get("input_schema", {}),
            output_parser=data.get("output_parser"),
            sandbox_profile=SandboxProfile(
                data.get("sandbox_profile", "network_scan_standard")
            ),
            requires_approval=data.get("requires_approval", False),
            rate_limit=data.get("rate_limit"),
            dangerous=data.get("dangerous", False),
            description=data.get("description", ""),
        )
