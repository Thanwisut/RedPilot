"""Tests for ScopeGuard — the core safety mechanism."""

from datetime import UTC, datetime, timedelta

from redpilot_core.guards.scope_guard import GuardResult, ScopeGuard
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest


class TestScopeGuard:
    """ScopeGuard pipeline: time -> scope -> permission."""

    def make_scope(
        self,
        *,
        allowed: list[str] | None = None,
        excluded: list[str] | None = None,
    ) -> Scope:
        return Scope(
            name="test",
            allowed_targets=allowed or ["10.0.0.0/24"],
            excluded_targets=excluded or [],
        )

    def test_allows_in_scope_target(self) -> None:
        scope = self.make_scope(allowed=["10.0.0.0/24"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="nmap", sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD)

        result = guard.check(target="10.0.0.50", tool_manifest=tool)
        assert result.allowed
        assert result.scope_check.allowed
        assert result.time_check

    def test_denies_out_of_scope_target(self) -> None:
        scope = self.make_scope(allowed=["10.0.0.0/24"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="nmap", sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD)

        result = guard.check(target="192.168.1.1", tool_manifest=tool)
        assert not result.allowed
        assert "denied by default" in result.reason

    def test_denies_outside_time_window(self) -> None:
        future = datetime.now(UTC) + timedelta(days=30)
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/24"],
            start_time=future,
        )
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="nmap", sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD)

        result = guard.check(target="10.0.0.50", tool_manifest=tool)
        assert not result.allowed
        assert "outside" in result.reason.lower()

    def test_denies_insufficient_permission(self) -> None:
        scope = self.make_scope()
        guard = ScopeGuard(scope)
        tool = ToolManifest(
            name="sqlmap",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=True,
        )

        result = guard.check(
            target="10.0.0.50",
            tool_manifest=tool,
            agent_permission_level="read_only",
        )
        assert not result.allowed
        assert "insufficient" in result.reason.lower()
        assert result.permission_check is not None
        assert not result.permission_check.sufficient

    def test_allows_sufficient_permission(self) -> None:
        scope = self.make_scope()
        guard = ScopeGuard(scope)
        # A write-level agent using a write-level tool
        tool = ToolManifest(
            name="sqlmap",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=True,
        )

        result = guard.check(
            target="10.0.0.50",
            tool_manifest=tool,
            agent_permission_level="write",
        )
        assert result.allowed

    def test_scope_property(self) -> None:
        scope = self.make_scope()
        guard = ScopeGuard(scope)
        assert guard.scope is scope

    def test_check_target_delegates_to_scope(self) -> None:
        scope = self.make_scope(allowed=["10.0.0.0/24"])
        guard = ScopeGuard(scope)

        scope_result = guard.check_target("10.0.0.50")
        assert scope_result.allowed

        scope_result = guard.check_target("10.1.0.1")
        assert not scope_result.allowed

    def test_check_time_window_delegates_to_scope(self) -> None:
        scope = self.make_scope()
        guard = ScopeGuard(scope)
        assert guard.check_time_window()  # no window configured

    def test_guard_result_allow_classmethod(self) -> None:
        result = GuardResult.allow()
        assert result.allowed
        assert result.reason == ""

    def test_guard_result_deny_classmethod(self) -> None:
        result = GuardResult.deny("Not permitted")
        assert not result.allowed
        assert result.reason == "Not permitted"


class TestScopeGuardPermissionComparison:
    """Permission level comparison logic."""

    def test_read_only_is_sufficient_for_readonly_tool(self) -> None:
        assert ScopeGuard._compare_permission("read_only", "read_only")

    def test_read_only_is_insufficient_for_write_tool(self) -> None:
        assert not ScopeGuard._compare_permission("read_only", "write")

    def test_write_is_sufficient_for_readonly_tool(self) -> None:
        assert ScopeGuard._compare_permission("write", "read_only")

    def test_write_is_insufficient_for_dangerous_tool(self) -> None:
        assert not ScopeGuard._compare_permission("write", "dangerous")

    def test_dangerous_is_sufficient_for_anything(self) -> None:
        assert ScopeGuard._compare_permission("dangerous", "read_only")
        assert ScopeGuard._compare_permission("dangerous", "write")
        assert ScopeGuard._compare_permission("dangerous", "dangerous")
