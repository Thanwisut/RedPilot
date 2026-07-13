"""Filesystem tool adapters — list, read, write, edit operations scoped to
the engagement's scratch/evidence directory.

All four tools validate path containment via ``path_safety.py`` before
any operation. Path traversal attempts (``../``, absolute paths outside
root, symlink escapes) are rejected with the same default-deny principle
applied to out-of-scope network targets.

Security tiers:
- ``list_directory`` / ``read_file``: read_only (no approval needed)
- ``write_file`` / ``edit_file``: dangerous=True, requires_approval=True
"""

from __future__ import annotations

import os
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.utils.path_safety import (
    PathEscapeError,
    resolve_safe_path_allow_missing,
    resolve_safe_path_must_exist,
)

# ---------------------------------------------------------------------------
# LIST DIRECTORY
# ---------------------------------------------------------------------------

LIST_DIR_MANIFEST = ToolManifest(
    name="list_directory",
    category="filesystem",
    binary="ls",
    version_pinned=None,
    input_schema={
        "path": {
            "type": "string",
            "required": True,
        },
        "recursive": {
            "type": "bool",
            "required": False,
        },
    },
    output_parser="directory_listing_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=False,
    dangerous=False,
    rate_limit=None,
    description="List files and directories within the engagement scratch directory.",
)


class ListDirectoryAdapter(ToolAdapter):
    """Adapter for listing directory contents within the scratch root."""

    manifest = LIST_DIR_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build an ``ls`` argv with path containment validation.

        Args:
            args: Must contain ``path`` (relative path within scratch_dir).
            scratch_dir: The allowed root directory.

        Returns:
            An argv list for sandbox execution.

        Raises:
            PathEscapeError: If the path escapes the scratch directory.
        """
        path = args.get("path", "")
        recursive = args.get("recursive", False)

        # Validate containment before building command
        resolve_safe_path_allow_missing(path, scratch_dir)

        argv: list[str] = ["ls"]
        if recursive:
            argv.append("-R")
        argv.append(os.path.join("/scratch", path.lstrip("/")))
        return argv

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Parse ``ls`` output into a structured directory listing.

        Args:
            stdout: Raw ls output.
            stderr: ls stderr.
            exit_code: Exit code.
            scratch_dir: Path to scratch directory.

        Returns:
            A dict with ``entries`` (list of filenames), ``count``,
            and ``raw_stdout``.
        """
        entries: list[str] = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("total "):
                entries.append(line)

        return {
            "entries": entries,
            "count": len(entries),
            "raw_stdout": stdout,
        }


# ---------------------------------------------------------------------------
# READ FILE
# ---------------------------------------------------------------------------

READ_FILE_MANIFEST = ToolManifest(
    name="read_file",
    category="filesystem",
    binary="cat",
    version_pinned=None,
    input_schema={
        "path": {
            "type": "string",
            "required": True,
        },
        "max_bytes": {
            "type": "int",
            "required": False,
        },
    },
    output_parser="file_content_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=False,
    dangerous=False,
    rate_limit=None,
    description="Read file contents from the engagement scratch directory.",
)


class ReadFileAdapter(ToolAdapter):
    """Adapter for reading file contents within the scratch root."""

    manifest = READ_FILE_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build a ``cat`` argv with path containment validation.

        Args:
            args: Must contain ``path`` (relative path within scratch_dir).
            scratch_dir: The allowed root directory.

        Returns:
            An argv list for sandbox execution.

        Raises:
            PathEscapeError: If the path escapes the scratch directory.
            FileNotFoundError: If the path does not exist.
        """
        path = args.get("path", "")

        # Validate containment and existence before building command
        resolve_safe_path_must_exist(path, scratch_dir)

        argv: list[str] = ["cat", os.path.join("/scratch", path.lstrip("/"))]
        return argv

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Parse file content.

        Args:
            stdout: File contents.
            stderr: Error output (if any).
            exit_code: Exit code.
            scratch_dir: Path to scratch directory.

        Returns:
            A dict with ``content``, ``size_bytes``, and ``truncated`` flag.
        """
        max_bytes = 100000  # Default truncation limit
        truncated = len(stdout) > max_bytes
        content = stdout[:max_bytes] if truncated else stdout

        return {
            "content": content,
            "size_bytes": len(stdout),
            "truncated": truncated,
        }


# ---------------------------------------------------------------------------
# WRITE FILE
# ---------------------------------------------------------------------------

WRITE_FILE_MANIFEST = ToolManifest(
    name="write_file",
    category="filesystem",
    binary="sh",
    version_pinned=None,
    input_schema={
        "path": {
            "type": "string",
            "required": True,
        },
        "content": {
            "type": "string",
            "required": True,
        },
    },
    output_parser="file_write_result_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=True,
    dangerous=True,
    rate_limit=None,
    description=(
        "Write content to a file within the engagement scratch directory. "
        "Creating new files based on LLM output is a risk surface — "
        "this tool requires human approval."
    ),
)


class WriteFileAdapter(ToolAdapter):
    """Adapter for writing file contents within the scratch root.

    Dangerous tool — requires human approval for every invocation.
    """

    manifest = WRITE_FILE_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build a command that writes content to a file.

        Uses a heredoc-like approach with ``/bin/sh -c`` and printf to
        safely write content. The path containment is validated before
        constructing the command.

        Args:
            args: Must contain ``path`` and ``content``.
            scratch_dir: The allowed root directory.

        Returns:
            An argv list for sandbox execution.

        Raises:
            PathEscapeError: If the path escapes the scratch directory.
        """
        path = args.get("path", "")
        content = args.get("content", "")

        # Validate containment before building command
        resolve_safe_path_allow_missing(path, scratch_dir)

        target_path = os.path.join("/scratch", path.lstrip("/"))

        # Use /bin/sh -c with printf to write content safely
        # The content is base64-encoded to avoid shell interpolation issues
        import base64
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

        return [
            "/bin/sh", "-c",
            f"echo '{encoded}' | base64 -d > '{target_path}'",
        ]

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Parse write result.

        Args:
            stdout: Command stdout.
            stderr: Command stderr.
            exit_code: Exit code.
            scratch_dir: Path to scratch directory.

        Returns:
            A dict with ``success``, ``path``, and ``bytes_written``.
        """
        return {
            "success": exit_code == 0,
            "bytes_written": 0,  # Could be improved by reading back file size
            "error": stderr if exit_code != 0 else None,
        }


# ---------------------------------------------------------------------------
# EDIT FILE
# ---------------------------------------------------------------------------

EDIT_FILE_MANIFEST = ToolManifest(
    name="edit_file",
    category="filesystem",
    binary="sh",
    version_pinned=None,
    input_schema={
        "path": {
            "type": "string",
            "required": True,
        },
        "old_string": {
            "type": "string",
            "required": True,
        },
        "new_string": {
            "type": "string",
            "required": True,
        },
    },
    output_parser="file_edit_result_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=True,
    dangerous=True,
    rate_limit=None,
    description=(
        "Edit a file by replacing the first occurrence of old_string with "
        "new_string. Fails clearly if old_string is not found. "
        "This tool requires human approval."
    ),
)


class EditFileAdapter(ToolAdapter):
    """Adapter for editing file contents within the scratch root.

    Performs a str_replace pattern: finds the first occurrence of
    ``old_string`` in the file and replaces it with ``new_string``.
    Fails if ``old_string`` is not found.

    Dangerous tool — requires human approval.
    """

    manifest = EDIT_FILE_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build a command that edits a file via sed.

        Path containment is validated before constructing the command.
        Uses a Python one-liner for reliable str_replace semantics.

        Args:
            args: Must contain ``path``, ``old_string``, ``new_string``.
            scratch_dir: The allowed root directory.

        Returns:
            An argv list for sandbox execution.

        Raises:
            PathEscapeError: If the path escapes the scratch directory.
        """
        path = args.get("path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")

        # Validate containment before building command
        resolve_safe_path_must_exist(path, scratch_dir)

        target_path = os.path.join("/scratch", path.lstrip("/"))

        # Use Python for reliable str_replace (handles special chars, multiline)
        import base64
        old_b64 = base64.b64encode(old_string.encode("utf-8")).decode("ascii")
        new_b64 = base64.b64encode(new_string.encode("utf-8")).decode("ascii")

        script = (
            "import base64, sys; "
            "old = base64.b64decode(sys.argv[1]).decode(); "
            "new_ = base64.b64decode(sys.argv[2]).decode(); "
            f"path = '{target_path}'; "
            "with open(path) as f: content = f.read(); "
            "if old not in content: "
            "  print(f'ERROR: old_string not found in {path}', file=sys.stderr); "
            "  sys.exit(1); "
            "content = content.replace(old, new_, 1); "
            f"with open(path, 'w') as f: f.write(content); "
            "print(f'Replaced 1 occurrence')"
        )

        return [
            "python3", "-c", script, old_b64, new_b64,
        ]

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Parse edit result.

        Args:
            stdout: Command stdout.
            stderr: Command stderr.
            exit_code: Exit code.
            scratch_dir: Path to scratch directory.

        Returns:
            A dict with ``success``, ``message``, and error info.
        """
        return {
            "success": exit_code == 0,
            "message": stdout.strip(),
            "error": stderr if exit_code != 0 else None,
        }
