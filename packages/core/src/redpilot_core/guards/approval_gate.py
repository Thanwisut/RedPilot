"""Approval Gate — manages human-in-the-loop approval for dangerous operations.

The architecture's key safety property (§9.4): anything flagged as
requiring approval pauses the Task Graph and pushes an approval request
to the TUI. Execution only proceeds on explicit operator confirmation;
a timeout defaults to DENY, not allow.

This module owns the approval lifecycle independent of the transport layer
(TUI WebSocket, REST, etc.). The orchestrator calls into this gate; the
transport layer delivers the prompts.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from redpilot_core.models.agent_manifest import PermissionLevel
from redpilot_core.models.tool_manifest import ToolManifest


class ApprovalStatus(Enum):
    """Lifecycle states of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"  # Timeout reached without resolution


@dataclass
class ApprovalRequest:
    """A request for human approval of a potentially dangerous action.

    Attributes:
        id: Unique request identifier.
        tool_name: Name of the tool being invoked.
        target: The target against which the tool would run.
        args: Arguments that would be passed to the tool.
        rationale: The agent's explanation for why this action is needed.
        agent_id: The agent requesting approval.
        permission_level: What permission level this action requires.
        status: Current lifecycle state.
        created_at: When this request was created.
        resolved_at: When this request was resolved (approved/denied/expired).
        resolved_by: Who or what resolved this request ("human", "timeout", "system").
        timeout_seconds: How long before this request auto-denies.
        on_resolved: Optional callback fired when the request is resolved.
    """

    id: str = field(default_factory=lambda: f"APPR-{uuid4().hex[:8].upper()}")
    tool_name: str = ""
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    agent_id: str = ""
    permission_level: PermissionLevel = PermissionLevel.WRITE
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    timeout_seconds: int = 300  # 5 minutes default
    on_resolved: Callable[[ApprovalRequest], None] | None = None

    @property
    def is_resolved(self) -> bool:
        """Whether this request has reached a terminal state."""
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.DENIED, ApprovalStatus.EXPIRED)

    @property
    def is_expired(self) -> bool:
        """Whether the timeout has elapsed without resolution."""
        if self.is_resolved:
            return self.status == ApprovalStatus.EXPIRED
        elapsed = (datetime.now(UTC) - self.created_at).total_seconds()
        return elapsed > self.timeout_seconds


class ApprovalGate:
    """Manages the lifecycle of approval requests for dangerous operations.

    The gate determines whether an action needs approval, creates requests,
    tracks pending requests, and resolves them on operator input or timeout.

    Thread-safe: the orchestrator and timeout checker may access from
    different coroutines/threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, ApprovalRequest] = {}
        self._resolved: dict[str, ApprovalRequest] = {}

    @property
    def pending_requests(self) -> list[ApprovalRequest]:
        """Return all currently pending approval requests."""
        with self._lock:
            return list(self._pending.values())

    @property
    def resolved_requests(self) -> list[ApprovalRequest]:
        """Return all previously resolved approval requests."""
        with self._lock:
            return list(self._resolved.values())

    def requires_approval(
        self,
        tool_manifest: ToolManifest,
        agent_permission: PermissionLevel = PermissionLevel.READ_ONLY,
    ) -> bool:
        """Determine whether a given tool + agent combination needs approval.

        Approval is required if ANY of these are true:
        1. The tool is classified as ``dangerous``.
        2. The tool's manifest has ``requires_approval: true``.
        3. The agent's permission level would be exceeded by the tool.
        """
        if tool_manifest.dangerous:
            return True
        if tool_manifest.requires_approval:
            return True

        # Check if the agent's permission level is sufficient
        rank = {PermissionLevel.READ_ONLY: 0, PermissionLevel.WRITE: 1, PermissionLevel.DANGEROUS: 2}
        tool_req = tool_manifest.effective_permission_level
        tool_rank = rank.get(
            {
                "read_only": PermissionLevel.READ_ONLY,
                "write": PermissionLevel.WRITE,
                "dangerous": PermissionLevel.DANGEROUS,
            }.get(tool_req, PermissionLevel.READ_ONLY),
            0,
        )

        return rank.get(agent_permission, 0) < tool_rank

    def create_request(
        self,
        tool_name: str,
        target: str,
        args: dict[str, Any],
        rationale: str,
        agent_id: str,
        permission_level: PermissionLevel = PermissionLevel.WRITE,
        *,
        timeout_seconds: int = 300,
        on_resolved: Callable[[ApprovalRequest], None] | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request and register it as pending.

        Args:
            tool_name: The tool being invoked.
            target: The target host/IP/domain.
            args: The tool arguments.
            rationale: The agent's explanation.
            agent_id: The requesting agent's identifier.
            permission_level: The permission level this request requires.
            timeout_seconds: Seconds before auto-denial (default 300).
            on_resolved: Optional callback fired on resolution.

        Returns:
            The newly created ApprovalRequest (status=PENDING).
        """
        request = ApprovalRequest(
            tool_name=tool_name,
            target=target,
            args=args,
            rationale=rationale,
            agent_id=agent_id,
            permission_level=permission_level,
            timeout_seconds=timeout_seconds,
            on_resolved=on_resolved,
        )

        with self._lock:
            self._pending[request.id] = request

        return request

    def resolve(self, request_id: str, approved: bool, resolved_by: str = "human") -> ApprovalRequest | None:
        """Resolve a pending approval request.

        Args:
            request_id: The approval request ID.
            approved: True to approve, False to deny.
            resolved_by: Identifier of the resolver (default "human").

        Returns:
            The resolved ApprovalRequest, or None if not found.
        """
        with self._lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                return None

            request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
            request.resolved_at = datetime.now(UTC)
            request.resolved_by = resolved_by

            self._resolved[request.id] = request

        if request.on_resolved:
            request.on_resolved(request)

        return request

    def check_expired(self) -> list[ApprovalRequest]:
        """Check all pending requests and expire those past their timeout.

        Called periodically by the orchestrator (e.g., every 30 seconds).
        Returns the list of newly expired requests for notification purposes.
        """
        expired: list[ApprovalRequest] = []
        now = datetime.now(UTC)

        with self._lock:
            to_remove: list[str] = []
            for req_id, request in self._pending.items():
                elapsed = (now - request.created_at).total_seconds()
                if elapsed > request.timeout_seconds:
                    request.status = ApprovalStatus.EXPIRED
                    request.resolved_at = now
                    request.resolved_by = "timeout"
                    self._resolved[req_id] = request
                    expired.append(request)
                    to_remove.append(req_id)

            for req_id in to_remove:
                del self._pending[req_id]

        for request in expired:
            if request.on_resolved:
                request.on_resolved(request)

        return expired

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Look up a request by ID (checks pending first, then resolved)."""
        with self._lock:
            return self._pending.get(request_id) or self._resolved.get(request_id)

    def clear_resolved(self) -> int:
        """Clear all resolved requests from the gate (for memory management)."""
        with self._lock:
            count = len(self._resolved)
            self._resolved.clear()
        return count
