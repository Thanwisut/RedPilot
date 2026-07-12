"""Scope Guard — validates every tool/browser request against engagement scope.

This is the core safety mechanism of REDPILOT. Every tool invocation
and browser navigation passes through this guard before execution,
enforcing a default-deny stance: nothing touches a target that hasn't
been explicitly authorized.

The guard is enforced at two layers:
1. Application layer (here) — logical check before we even fork a process
2. Sandbox network-egress layer (in tools/) — defense in depth, so an
   app-layer bug doesn't translate into out-of-scope traffic
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from redpilot_core.models.scope import Scope, ScopeCheckResult
from redpilot_core.models.tool_manifest import ToolManifest


@dataclass
class GuardResult:
    """Result of a full scope + permission guard check.

    Attributes:
        allowed: Whether the requested action is permitted.
        reason: Human-readable explanation if denied.
        scope_check: The result of the target scope validation.
        permission_check: The result of the permission level validation.
        time_check: Whether the current time is within the engagement window.
    """

    allowed: bool
    reason: str = ""
    scope_check: ScopeCheckResult = field(default_factory=lambda: ScopeCheckResult(allowed=True))
    permission_check: PermissionCheckResult | None = None
    time_check: bool = True

    @classmethod
    def allow(cls) -> GuardResult:
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> GuardResult:
        return cls(allowed=False, reason=reason)


@dataclass
class PermissionCheckResult:
    """Result of a permission level validation."""

    sufficient: bool
    required_level: str
    agent_level: str
    tool_name: str


class ScopeGuard:
    """Validates tool/browser requests against the engagement scope.

    The guard performs three checks in order:
    1. Time window — is the engagement currently active?
    2. Target scope — is the target in the authorized scope?
    3. Permission level (optional) — does the agent have sufficient permission?

    All three must pass for execution to proceed.
    """

    def __init__(self, scope: Scope) -> None:
        self._scope = scope

    @property
    def scope(self) -> Scope:
        """The scope definition this guard is enforcing."""
        return self._scope

    def check_target(self, target: str) -> ScopeCheckResult:
        """Check if *target* is within the authorized scope.

        Delegates to Scope.check_target() which applies the default-deny rule.
        """
        return self._scope.check_target(target)

    def check_time_window(self, at_time: datetime | None = None) -> bool:
        """Check if *at_time* falls within the engagement's authorized window.

        If no time window is configured, this always passes (no restriction).
        """
        return self._scope.check_time_window(at_time)

    def check_permission(
        self,
        tool_manifest: ToolManifest,
        agent_permission_level: str,
    ) -> PermissionCheckResult:
        """Check if an agent's permission level is sufficient for a tool.

        The check follows the architecture's rule (§9.3):
        - Tool permission levels are defined per-tool in the manifest
        - An agent inherits the permission level of the tool it's invoking
        - The agent's configured level must be >= the tool's required level

        Args:
            tool_manifest: The manifest of the tool being invoked.
            agent_permission_level: The permission level configured for the agent.

        Returns:
            A PermissionCheckResult indicating whether access is granted.
        """
        required = tool_manifest.effective_permission_level
        sufficient = self._compare_permission(agent_permission_level, required)

        return PermissionCheckResult(
            sufficient=sufficient,
            required_level=required,
            agent_level=agent_permission_level,
            tool_name=tool_manifest.name,
        )

    def check(
        self,
        target: str,
        tool_manifest: ToolManifest,
        agent_permission_level: str = "read_only",
        at_time: datetime | None = None,
    ) -> GuardResult:
        """Run the full guard pipeline: time → scope → permission.

        This is the primary entry point for the orchestrator. Every tool
        invocation should go through this method.

        Args:
            target: The target host/IP/domain being acted against.
            tool_manifest: The manifest of the tool being invoked.
            agent_permission_level: The permission level of the requesting agent.
            at_time: Optional timestamp for time-window check (defaults to now).

        Returns:
            A GuardResult — check `.allowed` before proceeding.
        """
        # 1. Time window check
        if not self.check_time_window(at_time):
            return GuardResult.deny(
                reason="Current time is outside the authorized engagement window.",
            )

        # 2. Target scope check
        scope_result = self.check_target(target)
        if not scope_result.allowed:
            return GuardResult(
                allowed=False,
                reason=scope_result.reason or "Target is not in scope.",
                scope_check=scope_result,
            )

        # 3. Permission level check
        perm_result = self.check_permission(tool_manifest, agent_permission_level)
        if not perm_result.sufficient:
            return GuardResult(
                allowed=False,
                reason=(
                    f"Agent permission '{agent_permission_level}' is insufficient "
                    f"for tool '{tool_manifest.name}' which requires '{perm_result.required_level}'."
                ),
                scope_check=scope_result,
                permission_check=perm_result,
                time_check=True,
            )

        return GuardResult(
            allowed=True,
            scope_check=scope_result,
            permission_check=perm_result,
            time_check=True,
        )

    @staticmethod
    def _compare_permission(agent_level: str, required_level: str) -> bool:
        """Compare permission levels using the hierarchy: read_only < write < dangerous."""
        rank = {"read_only": 0, "write": 1, "dangerous": 2}
        return rank.get(agent_level, 0) >= rank.get(required_level, 0)
