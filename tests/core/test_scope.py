"""Tests for scope domain models — Scope, ScopeRule, ScopeCheckResult."""

from datetime import UTC, datetime, timedelta

import pytest
from redpilot_core.models.scope import (
    Scope,
    ScopeCheckResult,
    ScopeRule,
    ScopeRuleType,
)


class TestScopeRule:
    """ScopeRule creation and matching behavior."""

    def test_allow_host_rule(self) -> None:
        rule = ScopeRule(ScopeRuleType.ALLOW_HOST, "192.168.1.1")
        assert rule.matches("192.168.1.1")
        assert not rule.matches("192.168.1.2")

    def test_allow_cidr_rule(self) -> None:
        rule = ScopeRule(ScopeRuleType.ALLOW_CIDR, "10.0.0.0/8")
        assert rule.matches("10.0.0.1")
        assert rule.matches("10.255.255.255")
        assert not rule.matches("11.0.0.1")

    def test_exclude_cidr_overrides_inclusion(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/8"],
            excluded_targets=["10.0.0.0/16"],
        )
        # 10.0.0.1 is in /8 but also in /16 exclusion
        result = scope.check_target("10.0.0.1")
        assert not result.allowed
        assert "exclusion" in (result.reason or "").lower()

    def test_domain_matching_exact(self) -> None:
        rule = ScopeRule(ScopeRuleType.ALLOW_DOMAIN, "example.com")
        assert rule.matches("example.com")
        assert not rule.matches("sub.example.com")
        assert not rule.matches("notexample.com")

    def test_domain_matching_wildcard(self) -> None:
        rule = ScopeRule(ScopeRuleType.ALLOW_DOMAIN, "*.example.com")
        assert rule.matches("sub.example.com")
        assert rule.matches("a.b.example.com")
        assert not rule.matches("example.com")  # wildcard doesn't match root
        assert not rule.matches("notexample.com")

    def test_invalid_cidr_raises(self) -> None:
        with pytest.raises(ValueError):
            ScopeRule(ScopeRuleType.ALLOW_CIDR, "not-a-cidr")

    def test_invalid_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid domain"):
            ScopeRule(ScopeRuleType.ALLOW_DOMAIN, "not a domain!")

    def test_exclude_host_rule(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/8"],
            excluded_targets=["10.0.0.5"],
        )
        assert scope.check_target("10.0.0.1").allowed
        assert not scope.check_target("10.0.0.5").allowed


class TestScope:
    """Scope creation and target validation."""

    def test_default_deny(self) -> None:
        """Targets not matching any rule are denied by default."""
        scope = Scope(name="empty")
        result = scope.check_target("192.168.1.1")
        assert not result.allowed
        assert "denied by default" in (result.reason or "").lower()

    def test_single_host_allow(self) -> None:
        scope = Scope(name="test", allowed_targets=["10.0.0.1"])
        assert scope.check_target("10.0.0.1").allowed
        assert not scope.check_target("10.0.0.2").allowed

    def test_cidr_allow(self) -> None:
        scope = Scope(name="test", allowed_targets=["10.0.0.0/24"])
        assert scope.check_target("10.0.0.1").allowed
        assert scope.check_target("10.0.0.254").allowed
        assert not scope.check_target("10.0.1.1").allowed

    def test_domain_allow(self) -> None:
        scope = Scope(name="test", allowed_targets=["*.example.com"])
        assert scope.check_target("app.example.com").allowed
        assert not scope.check_target("evil.com").allowed

    def test_multiple_allows(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/24", "192.168.1.1"],
        )
        assert scope.check_target("10.0.0.50").allowed
        assert scope.check_target("192.168.1.1").allowed
        assert not scope.check_target("10.1.0.1").allowed

    def test_exclusion_overrides_inclusion(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/8"],
            excluded_targets=["10.0.0.0/16"],
        )
        # In /8 but also in /16 exclusion
        assert not scope.check_target("10.0.0.1").allowed
        # In /8 but NOT in /16 exclusion
        result = scope.check_target("10.1.0.1")
        assert result.allowed

    def test_exclusion_with_domains(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["*.example.com"],
            excluded_targets=["admin.example.com"],
        )
        assert scope.check_target("app.example.com").allowed
        assert not scope.check_target("admin.example.com").allowed

    def test_description_and_attestation(self) -> None:
        scope = Scope(
            name="pentest-2026-001",
            authorization_attestation="AUTH-2026-001-SIGNED",
            description="Annual external penetration test",
        )
        assert scope.name == "pentest-2026-001"
        assert scope.authorization_attestation == "AUTH-2026-001-SIGNED"
        assert scope.description == "Annual external penetration test"

    def test_rules_auto_generated_from_lists(self) -> None:
        scope = Scope(
            name="test",
            allowed_targets=["10.0.0.0/24", "example.com"],
            excluded_targets=["10.0.0.100"],
        )
        # Should have exactly 3 rules (allow CIDR, allow domain, exclude host)
        assert len(scope.rules) == 3
        rule_types = {r.rule_type for r in scope.rules}
        assert ScopeRuleType.ALLOW_CIDR in rule_types
        assert ScopeRuleType.ALLOW_DOMAIN in rule_types
        assert ScopeRuleType.EXCLUDE_HOST in rule_types


class TestScopeCheckResult:
    """ScopeCheckResult factory behavior."""

    def test_allow_result(self) -> None:
        result = ScopeCheckResult.allow(matched_rule="10.0.0.0/24")
        assert result.allowed
        assert result.matched_rule == "10.0.0.0/24"

    def test_deny_result(self) -> None:
        result = ScopeCheckResult.deny("Out of scope", matched_rule="none")
        assert not result.allowed
        assert result.reason == "Out of scope"
        assert result.matched_rule == "none"


class TestScopeTimeWindow:
    """Engagement time window validation."""

    def test_no_window_always_passes(self) -> None:
        scope = Scope(name="test")
        assert scope.check_time_window()

    def test_before_window_denies(self) -> None:
        future = datetime.now(UTC) + timedelta(days=7)
        scope = Scope(name="test", start_time=future)
        assert not scope.check_time_window()

    def test_inside_window_allows(self) -> None:
        now = datetime.now(UTC)
        scope = Scope(
            name="test",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
        )
        assert scope.check_time_window(now)

    def test_after_window_denies(self) -> None:
        past = datetime.now(UTC) - timedelta(days=7)
        scope = Scope(
            name="test",
            end_time=past,
        )
        assert not scope.check_time_window()
