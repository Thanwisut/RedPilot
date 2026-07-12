"""Audit log interface for tool invocations.

The audit log is written on **every** exit path from ToolRunner.run(),
including blocked requests. The log must be complete for rejected requests
too — what the system refused to do is as important as what it did.

See architecture doc §9.6 for the audit logging requirements.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_result import ToolResult


@dataclass
class AuditEntry:
    """A single audit log entry for a tool invocation.

    Every entry records the full context: who asked, what they wanted,
    what the scope was, what the outcome was, and all raw output.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tool_name: str = ""
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    requesting_agent: str = ""
    task_node: str = ""
    rationale: str = ""
    scope_name: str = ""
    result_status: str = ""
    result_error: str | None = None
    execution_time_ms: int = 0
    stdout_truncated: str = ""
    stderr_truncated: str = ""
    artifacts: list[str] = field(default_factory=list)
    version_detected: str | None = None
    version_pinned: str | None = None


class AuditLog(ABC):
    """Append-only audit log for tool invocations.

    The default implementation is in-memory. Production deployments should
    substitute a durable backend (file, database, SIEM forwarder).
    """

    @abstractmethod
    async def write(
        self,
        *,
        tool_name: str,
        target: str,
        args: dict[str, Any],
        requesting_agent: str,
        task_node: str,
        rationale: str,
        scope: Scope,
        result: ToolResult,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Write an audit entry for a completed (or blocked) invocation.

        Must be safe to call from concurrent coroutines. Must never raise
        (failures should be logged to a side-channel, not propagated).
        """

    @abstractmethod
    async def read(self, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        """Read the most recent audit entries, newest first.

        Args:
            limit: Maximum number of entries to return.
            offset: Number of entries to skip (for pagination).

        Returns:
            A list of audit entries in reverse chronological order.
        """


class InMemoryAuditLog(AuditLog):
    """Thread-safe, in-memory audit log for testing and development.

    Not suitable for production — entries are lost on process restart.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def write(
        self,
        *,
        tool_name: str,
        target: str,
        args: dict[str, Any],
        requesting_agent: str,
        task_node: str,
        rationale: str,
        scope: Scope,
        result: ToolResult,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        entry = AuditEntry(
            tool_name=tool_name,
            target=target,
            args=args,
            requesting_agent=requesting_agent,
            task_node=task_node,
            rationale=rationale,
            scope_name=scope.name,
            result_status=result.status.value,
            result_error=result.error,
            execution_time_ms=result.execution_time_ms,
            stdout_truncated=stdout[:5000],
            stderr_truncated=stderr[:5000],
            artifacts=result.artifacts,
            version_detected=result.tool_version,
        )
        self._entries.append(entry)

    async def read(self, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        return list(reversed(self._entries))[offset : offset + limit]

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    @property
    def total_count(self) -> int:
        return len(self._entries)
