"""Domain model for structured tool execution results.

Every tool invocation — whether a CLI binary, a Python function, or
an MCP server call — returns a ToolResult through the ToolRunner interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ToolResultStatus(Enum):
    """Outcome status of a tool execution.

    Maps to the state machine paths:
    - SUCCESS / PARTIAL → proceed to Verifier Agent
    - FAILURE → check retry budget
    - TIMEOUT → check retry budget (with adjusted parameters)
    - BLOCKED → was stopped by Scope Guard or Approval Gate; no retry
    """

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass
class ToolResult:
    """Structured result from a single tool invocation.

    Attributes:
        status: Outcome of the execution.
        tool_name: Name of the tool that was executed (from manifest).
        stdout: Captured standard output text.
        stderr: Captured standard error text.
        exit_code: Process exit code (0 for success in CLI tools).
        artifacts: Paths to any artifacts produced (files, screenshots, logs).
        parsed_output: Structured data extracted by the output parser, if any.
        execution_time_ms: Wall-clock execution time in milliseconds.
        error: Human-readable error description (populated on failure/timeout).
        target: The target against which the tool was run.
        raw_args: The actual arguments passed to the tool.
        tool_version: Version of the tool binary that was executed.
        timestamp: When the tool invocation completed.
    """

    status: ToolResultStatus
    tool_name: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    artifacts: list[str] = field(default_factory=list)
    parsed_output: dict[str, Any] | None = None
    execution_time_ms: int = 0
    error: str | None = None
    target: str = ""
    raw_args: dict[str, Any] = field(default_factory=dict)
    tool_version: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def success(
        cls,
        tool_name: str,
        *,
        stdout: str = "",
        stderr: str = "",
        artifacts: list[str] | None = None,
        parsed_output: dict[str, Any] | None = None,
        execution_time_ms: int = 0,
        target: str = "",
        raw_args: dict[str, Any] | None = None,
        tool_version: str | None = None,
    ) -> ToolResult:
        """Convenience constructor for a successful execution."""
        return cls(
            status=ToolResultStatus.SUCCESS,
            tool_name=tool_name,
            stdout=stdout,
            stderr=stderr,
            exit_code=0,
            artifacts=artifacts or [],
            parsed_output=parsed_output,
            execution_time_ms=execution_time_ms,
            target=target,
            raw_args=raw_args or {},
            tool_version=tool_version,
        )

    @classmethod
    def failure(
        cls,
        tool_name: str,
        *,
        error: str,
        exit_code: int = 1,
        stdout: str = "",
        stderr: str = "",
        target: str = "",
        raw_args: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Convenience constructor for a failed execution."""
        return cls(
            status=ToolResultStatus.FAILURE,
            tool_name=tool_name,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            error=error,
            target=target,
            raw_args=raw_args or {},
        )

    @classmethod
    def blocked(
        cls,
        tool_name: str,
        *,
        reason: str,
        target: str = "",
        raw_args: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Convenience constructor for an execution blocked by the Scope Guard."""
        return cls(
            status=ToolResultStatus.BLOCKED,
            tool_name=tool_name,
            error=reason,
            target=target,
            raw_args=raw_args or {},
        )

    @property
    def succeeded(self) -> bool:
        """Whether the tool completed with a success status."""
        return self.status == ToolResultStatus.SUCCESS

    @property
    def can_retry(self) -> bool:
        """Whether this result represents a condition that could be retried.

        BLOCKED results should NOT be retried (the guard's decision stands
        unless the scope or approval changes).
        """
        return self.status in (ToolResultStatus.FAILURE, ToolResultStatus.TIMEOUT)
