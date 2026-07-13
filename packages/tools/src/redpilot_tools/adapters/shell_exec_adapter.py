"""Shell execution adapter — runs arbitrary commands inside the sandbox.

**Security properties** (mandated by architecture doc §9):
- ``dangerous: true`` — this tool can execute arbitrary system commands
- ``requires_approval: true`` — every invocation requires human approval
- argv is always ``list[str]``, never a shell string (same as NmapAdapter)
- Runs inside the existing Docker sandbox with ``--cap-drop=ALL``
- Approval prompt MUST display the FULL literal command being requested

The input schema accepts ``command`` as a **list of strings** (argv) for
maximum safety. Each element is validated to be a string and then passed
directly to ``subprocess.run()`` in the sandbox — no shell interpolation,
no concatenation, no string formatting of LLM-supplied content.

If a real shell is truly necessary (pipes, redirects, env vars), the
LLM should construct the command as ``["/bin/sh", "-c", "..."]``, which
is explicitly documented and still safer than naive string interpolation.
"""

from __future__ import annotations

import shlex
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter

SHELL_EXEC_MANIFEST = ToolManifest(
    name="shell_exec",
    category="general",
    binary="sh",
    version_pinned=None,
    input_schema={
        "command": {
            "type": "list",
            "required": True,
        },
        "description": {
            "type": "string",
            "required": False,
        },
        "timeout": {
            "type": "int",
            "required": False,
        },
    },
    output_parser="raw_output_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=True,
    dangerous=True,
    rate_limit=None,
    description=(
        "Execute arbitrary shell commands inside the isolated sandbox. "
        "The command is provided as a list of strings (argv). "
        "For shell features (pipes, redirects), use [\"/bin/sh\", \"-c\", \"...\"]."
    ),
)


class ShellExecAdapter(ToolAdapter):
    """Adapter for arbitrary command execution inside the sandbox.

    Every invocation requires human approval. The approval prompt displays
    the full literal command (via ``build_command_representation``) so there
    is no ambiguity about what is being approved.
    """

    manifest = SHELL_EXEC_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build the argv for sandbox execution.

        The ``command`` argument is expected to be a list of strings.
        Each element is validated to be a string. No shell interpolation
        is performed — this is a straight pass-through.

        Args:
            args: Must contain ``command`` (list[str]).
            scratch_dir: Host-visible scratch directory path.

        Returns:
            The argv list to execute inside the sandbox.

        Raises:
            ValueError: If ``command`` is missing, not a list, or contains
                non-string elements.
        """
        command = args.get("command")
        if command is None:
            msg = "Missing required argument: 'command'"
            raise ValueError(msg)
        if not isinstance(command, list):
            msg = f"'command' must be a list of strings, got {type(command).__name__}"
            raise ValueError(msg)
        if len(command) == 0:
            msg = "'command' must not be empty"
            raise ValueError(msg)

        # Validate every element is a string
        for i, arg in enumerate(command):
            if not isinstance(arg, str):
                msg = (
                    f"Element {i} of 'command' must be a string, "
                    f"got {type(arg).__name__}"
                )
                raise ValueError(msg)

        return list(command)  # Return a copy

    def build_command_representation(self, args: dict[str, Any]) -> str:
        """Build a human-readable representation of the command for approval.

        Uses ``shlex.join()`` to produce a safe, readable command string
        that the human operator can verify before approving.

        Args:
            args: The validated tool arguments.

        Returns:
            A shell-safe command string representation.
        """
        command = args.get("command", [])
        if isinstance(command, list) and all(isinstance(c, str) for c in command):
            return shlex.join(command)
        return str(command)

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Return raw stdout/stderr as structured output.

        Args:
            stdout: Captured standard output.
            stderr: Captured standard error.
            exit_code: Process exit code.
            scratch_dir: Path to scratch directory.

        Returns:
            A dict with keys ``stdout``, ``stderr``, ``exit_code``.
        """
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
