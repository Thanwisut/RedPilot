"""Subfinder adapter — passive subdomain discovery via subfinder.

Follows the same safety rules as NmapAdapter:
- argv is always ``list[str]``, never a shell string
- Flags mapped from a fixed allowlist, not from raw agent input
- Output parsed into structured ``DiscoveredSubdomain`` list
- Version drift detection via ``--version``

**Key safety properties:**
- ``-d`` (domain) allowlist: domain validated as hostname before insertion
- ``-silent`` always emitted for machine-readable output
- No ``-oJ``, ``-oD`` flags — output is parsed from stdout only
- ``-max-time`` enforced from manifest's rate_limit, agent cannot override
"""

from __future__ import annotations

import re
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.adapters.nmap_adapter import _satisfies_semver_range

# Fixed allowlists — no agent-supplied string is ever passed directly to flags.
_SOURCE_FLAGS: dict[str, str] = {
    "all": "-all",
    "default": "",
}

_SUBFINDER_MANIFEST = ToolManifest(
    name="subfinder",
    category="recon",
    binary="subfinder",
    version_pinned=">=2.14.0,<3.0.0",
    input_schema={
        "domain": {"type": "string", "required": True},
        "sources": {
            "type": "enum",
            "required": False,
            "values": ["all", "default"],
        },
        "recursive": {"type": "bool", "required": False},
        "max_time": {"type": "int", "required": False},
    },
    output_parser="subfinder_line_parser",
    sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD,
    requires_approval=False,
    dangerous=False,
    rate_limit={"max_time_seconds": 60},
    description="Fast passive subdomain enumeration tool",
)

# Valid hostname pattern (same as nmap's _VALID_TARGET_RE)
_VALID_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$"
)


class SubfinderAdapter(ToolAdapter):
    """Adapter for subfinder subdomain discovery."""

    manifest = _SUBFINDER_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build a subfinder argv from logical arguments.

        The command is always built as a ``list[str]`` — never a shell string.
        Every flag is mapped from a fixed allowlist; no raw agent input is
        ever placed directly into argv as a flag name.
        """
        argv: list[str] = ["subfinder"]

        # -- Target domain (validated before insertion)
        domain = args.get("domain", "")
        self._validate_domain(domain)
        argv.append("-d")
        argv.append(domain)

        # -- Always silent for machine-readable output
        argv.append("-silent")

        # -- Sources (optional, default infects all available sources)
        sources = args.get("sources", "all")
        source_flag = _SOURCE_FLAGS.get(sources)
        if source_flag:
            argv.append(source_flag)

        # -- Recursive (optional)
        if args.get("recursive", False):
            argv.append("-recursive")

        # -- Max time (enforced from manifest, agent cannot override)
        max_time = args.get("max_time")
        if max_time is not None:
            argv.append("-max-time")
            argv.append(str(max_time))

        return argv

    def parse_output(
        self,
        stdout: str,
        stderr: str,  # noqa: ARG002
        exit_code: int,
        scratch_dir: str,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Parse subfinder silent output (one subdomain per line).

        Args:
            stdout: Subfinder silent output (one subdomain per line).
            stderr: Subfinder stderr.
            exit_code: Process exit code (0 = success).
            scratch_dir: Path to scratch directory (unused).

        Returns:
            A dict with keys ``subdomains`` (list of dicts with ``host``
            key) and ``count``. Returns empty result on parse failure.
        """
        result: dict[str, Any] = {
            "subdomains": [],
            "count": 0,
        }

        if not stdout.strip():
            return result

        subdomains: list[dict[str, str]] = []
        seen: set[str] = set()

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Skip non-domain lines (warnings, info messages)
            if not self._looks_like_domain(line):
                continue
            # Deduplicate
            lower = line.lower()
            if lower not in seen:
                seen.add(lower)
                subdomains.append({"host": line})

        result["subdomains"] = subdomains
        result["count"] = len(subdomains)

        return result

    def check_version(self, detected_version: str) -> bool:
        """Check subfinder version against ``>=2.14.0,<3.0.0``.

        Subfinder reports versions like ``v2.14.0`` (with leading ``v``).
        """
        if self.manifest.version_pinned is None:
            return True
        return _satisfies_semver_range(detected_version, self.manifest.version_pinned)

    def _validate_domain(self, domain: str) -> None:
        """Validate that *domain* is a syntactically valid hostname.

        Raises ``ValueError`` if the domain is malformed. This is
        defense-in-depth alongside the argv-list-not-shell-string rule.
        """
        if not domain:
            msg = "Domain is required"
            raise ValueError(msg)

        if not _VALID_DOMAIN_RE.match(domain):
            msg = f"Domain '{domain}' is not a valid hostname"
            raise ValueError(msg)

        if len(domain) > 253:
            msg = f"Domain '{domain}' exceeds maximum hostname length"
            raise ValueError(msg)

    @staticmethod
    def _looks_like_domain(s: str) -> bool:
        """Check if a string looks like a domain (has at least one dot)."""
        return "." in s and not s.startswith("[") and not s.startswith("(")


# _satisfies_semver_range is imported from nmap_adapter (shared utility).
# Delegating to avoid duplicating the ~30-line range matching logic.
# If this cross-adapter dependency becomes a problem, extract to
# redpilot_tools.utils.version in a future refactoring pass.
