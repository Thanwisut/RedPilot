"""Abstract base class for tool adapters.

Adapters are pure translators: logical args in, a concrete subprocess/container
command out, raw output parsed back into structured data. Adapters never touch
the network, the filesystem outside their scratch directory, or the security
guards directly — that is the ToolRunner's responsibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from redpilot_core.models.tool_manifest import ToolManifest


class ToolAdapter(ABC):
    """One per tool. Translates agent-provided arguments into execution
    commands and parses raw output into structured data.

    Subclasses must set ``manifest`` as a class-level attribute or
    override the ``manifest`` property.
    """

    manifest: ToolManifest

    @abstractmethod
    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Return the argv to execute inside the sandbox.

        **Must** return a list of strings — never a shell string — to prevent
        injection via agent-supplied arguments.

        Args:
            args: Validated agent-provided arguments (already checked against
                  ``manifest.input_schema`` by the runner).
            scratch_dir: Host-visible path for writing temporary output files.

        Returns:
            An argv list suitable for ``subprocess.run()`` or container execution.
        """

    @abstractmethod
    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Turn raw tool output into structured, typed data.

        The return value is stored in ``ToolResult.parsed_output``. It should
        contain only the data agents reason over — raw text is preserved
        separately as an evidence artifact.

        Args:
            stdout: Captured standard output from the tool.
            stderr: Captured standard error from the tool.
            exit_code: Process exit code.
            scratch_dir: Path to the scratch directory (may contain output
                         files the adapter wrote during execution).

        Returns:
            A dict with structured results (e.g., ``{"ports": [...], "stats": {...}}``).
            Can be empty on failure.
        """

    def required_capabilities(self, args: dict[str, Any]) -> list[str]:
        """Return Linux capabilities needed for this specific invocation.

        Override this to signal sandbox-level capability requirements
        (e.g., ``["NET_RAW"]`` for SYN scans). Default is empty list.

        Args:
            args: The validated agent-provided arguments for this invocation.

        Returns:
            A list of Linux capability names (without ``CAP_`` prefix).
        """
        return []

    def check_version(self, detected_version: str) -> bool:
        """Compare a detected tool version against ``manifest.version_pinned``.

        The default implementation returns True if no version is pinned, or
        performs simple equality matching. Adapters for tools with unusual
        versioning (e.g., nmap with ``>=7.90,<8.0``) should override this.

        Args:
            detected_version: Version string reported by the tool (e.g., "7.94").

        Returns:
            True if the version is compatible, False if version drift is detected.
        """
        if self.manifest.version_pinned is None:
            return True
        return detected_version == self.manifest.version_pinned
