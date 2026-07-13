"""Tests for ScopeGuard URL/hostname matching — needed by Browser Agent.

Confirms that ScopeGuard can validate URL targets (for ``navigate``,
``click``, etc.) by extracting the hostname and checking against
the scope's domain/IP rules.
"""

from redpilot_core.guards.scope_guard import ScopeGuard
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest


class TestScopeGuardUrlResolution:
    """ScopeGuard._resolve_url_target URL hostname extraction."""

    def test_plain_hostname_passes_through(self) -> None:
        result = ScopeGuard._resolve_url_target("example.com")
        assert result == "example.com"

    def test_ip_passes_through(self) -> None:
        result = ScopeGuard._resolve_url_target("10.0.0.50")
        assert result == "10.0.0.50"

    def test_https_url_extracts_hostname(self) -> None:
        result = ScopeGuard._resolve_url_target("https://example.com/page")
        assert result == "example.com"

    def test_http_url_extracts_hostname(self) -> None:
        result = ScopeGuard._resolve_url_target("http://example.com:8080/admin")
        assert result == "example.com"

    def test_url_with_query_string(self) -> None:
        result = ScopeGuard._resolve_url_target("https://example.com/path?q=1&r=2")
        assert result == "example.com"

    def test_url_with_ip(self) -> None:
        result = ScopeGuard._resolve_url_target("http://192.168.1.1:8080/login")
        assert result == "192.168.1.1"

    def test_https_subdomain_url(self) -> None:
        result = ScopeGuard._resolve_url_target("https://admin.example.com/dashboard")
        assert result == "admin.example.com"

    def test_empty_string_passes_through(self) -> None:
        result = ScopeGuard._resolve_url_target("")
        assert result == ""


class TestScopeGuardUrlCheck:
    """ScopeGuard.check_target with URL targets."""

    def make_scope(
        self,
        *,
        allowed: list[str] | None = None,
    ) -> Scope:
        return Scope(
            name="test",
            allowed_targets=allowed or ["example.com"],
        )

    def test_allows_domain_via_url(self) -> None:
        """A domain allowed in scope should work when accessed via https:// URL."""
        scope = self.make_scope(allowed=["example.com"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(
            target="https://example.com/login",
            tool_manifest=tool,
        )
        assert result.allowed

    def test_allows_subdomain_via_url_with_wildcard(self) -> None:
        """Wildcard domain *.example.com should allow subdomain URLs."""
        scope = Scope(
            name="test",
            allowed_targets=["*.example.com"],
        )
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(
            target="https://admin.example.com/dashboard",
            tool_manifest=tool,
        )
        assert result.allowed

    def test_denies_out_of_scope_url(self) -> None:
        """URL with hostname not in scope should be denied."""
        scope = self.make_scope(allowed=["example.com"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(
            target="https://evil.com/phish",
            tool_manifest=tool,
        )
        assert not result.allowed
        assert "denied by default" in result.reason

    def test_allows_ip_in_scope_via_url(self) -> None:
        """IP in scope should work when accessed via http:// URL."""
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/24"],
        )
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(
            target="http://10.0.0.50/admin",
            tool_manifest=tool,
        )
        assert result.allowed

    def test_denies_out_of_scope_ip_via_url(self) -> None:
        """IP not in scope should be denied even via URL."""
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/24"],
        )
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(
            target="http://192.168.1.1/admin",
            tool_manifest=tool,
        )
        assert not result.allowed

    def test_dangerous_browser_action_still_checked(self) -> None:
        """Browser actions flagged as dangerous still go through scope check."""
        scope = self.make_scope(allowed=["example.com"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(
            name="browser",
            sandbox_profile=SandboxProfile.BROWSER,
            dangerous=True,
        )

        # In-scope target should pass scope, but the dangerous check
        # happens at the approval gate level, not scope guard
        result = guard.check(
            target="https://example.com/page",
            tool_manifest=tool,
            agent_permission_level="read_only",
        )
        # Scope check should pass (target is in scope)
        assert result.scope_check.allowed
        # But permission check should fail (read_only can't use dangerous tool)
        assert not result.allowed
        assert "insufficient" in result.reason.lower()


class TestScopeDomainRulesExisting:
    """Confirm existing Scope domain matching still works (regression)."""

    def test_exact_domain_match(self) -> None:
        scope = Scope(name="test", allowed_targets=["example.com"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        result = guard.check(target="example.com", tool_manifest=tool)
        assert result.allowed

    def test_wildcard_domain_match(self) -> None:
        scope = Scope(name="test", allowed_targets=["*.example.com"])
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        assert guard.check(target="sub.example.com", tool_manifest=tool).allowed
        assert guard.check(target="deep.sub.example.com", tool_manifest=tool).allowed
        assert not guard.check(target="example.com", tool_manifest=tool).allowed
        assert not guard.check(target="evil.com", tool_manifest=tool).allowed

    def test_exclusion_override(self) -> None:
        """Excluded domains should be denied even if wildcard allows."""
        scope = Scope(
            name="test",
            allowed_targets=["*.example.com"],
            excluded_targets=["admin.example.com"],
        )
        guard = ScopeGuard(scope)
        tool = ToolManifest(name="browser", sandbox_profile=SandboxProfile.BROWSER)

        assert guard.check(target="sub.example.com", tool_manifest=tool).allowed
        assert not guard.check(target="admin.example.com", tool_manifest=tool).allowed
