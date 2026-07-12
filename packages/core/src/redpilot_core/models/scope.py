"""Domain model for engagement scope definition and validation."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ScopeRuleType(Enum):
    """The kind of match a scope rule performs."""

    ALLOW_HOST = "allow_host"
    ALLOW_CIDR = "allow_cidr"
    ALLOW_DOMAIN = "allow_domain"
    ALLOW_PORT = "allow_port"
    EXCLUDE_HOST = "exclude_host"
    EXCLUDE_CIDR = "exclude_cidr"
    EXCLUDE_DOMAIN = "exclude_domain"
    EXCLUDE_PORT = "exclude_port"


@dataclass(frozen=True)
class ScopeRule:
    """A single scope rule — either an inclusion or exclusion.

    Rules are evaluated in order: exclusions override inclusions.
    This keeps the scope definition restrictive by default.
    """

    rule_type: ScopeRuleType
    value: str

    def __post_init__(self) -> None:
        """Validate the rule value format on construction."""
        if self.rule_type in (ScopeRuleType.ALLOW_CIDR, ScopeRuleType.EXCLUDE_CIDR):
            ipaddress.ip_network(self.value, strict=False)
        elif self.rule_type in (ScopeRuleType.ALLOW_HOST, ScopeRuleType.EXCLUDE_HOST):
            ipaddress.ip_address(self.value)
        elif self.rule_type in (ScopeRuleType.ALLOW_DOMAIN, ScopeRuleType.EXCLUDE_DOMAIN):
            if not re.match(r"^(\*\.)?([a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+(\.[a-zA-Z]{2,})$", self.value):
                msg = f"Invalid domain pattern: {self.value}"
                raise ValueError(msg)

    def matches(self, target: str) -> bool:
        """Check if a given target string matches this rule.

        Supports:
        - Exact host IP
        - CIDR range
        - Domain (exact or wildcard like *.example.com)
        """
        try:
            if self.rule_type in (ScopeRuleType.ALLOW_HOST, ScopeRuleType.EXCLUDE_HOST):
                addr = ipaddress.ip_address(target)
                return str(addr) == self.value

            if self.rule_type in (ScopeRuleType.ALLOW_CIDR, ScopeRuleType.EXCLUDE_CIDR):
                addr = ipaddress.ip_address(target)
                network = ipaddress.ip_network(self.value, strict=False)
                return addr in network

            if self.rule_type in (ScopeRuleType.ALLOW_DOMAIN, ScopeRuleType.EXCLUDE_DOMAIN):
                return self._match_domain(target)

            if self.rule_type in (ScopeRuleType.ALLOW_PORT, ScopeRuleType.EXCLUDE_PORT):
                return target == self.value

        except (ValueError, TypeError):
            # If target isn't a valid IP, try domain matching
            if self.rule_type in (
                ScopeRuleType.ALLOW_CIDR, ScopeRuleType.EXCLUDE_CIDR,
                ScopeRuleType.ALLOW_HOST, ScopeRuleType.EXCLUDE_HOST,
            ):
                return False
            return self._match_domain(target)

        return False

    def _match_domain(self, target: str) -> bool:
        """Match a target hostname against a domain rule, supporting wildcards."""
        if self.value.startswith("*."):
            # Wildcard: *.example.com matches sub.example.com but not example.com
            suffix = self.value[1:]  # ".example.com"
            return target.endswith(suffix) and target != suffix[1:]
        return target == self.value


@dataclass
class ScopeCheckResult:
    """Result of a scope validation check."""

    allowed: bool
    reason: str | None = None
    matched_rule: str | None = None

    @classmethod
    def allow(cls, matched_rule: str | None = None) -> ScopeCheckResult:
        return cls(allowed=True, reason=None, matched_rule=matched_rule)

    @classmethod
    def deny(cls, reason: str, matched_rule: str | None = None) -> ScopeCheckResult:
        return cls(allowed=False, reason=reason, matched_rule=matched_rule)


@dataclass
class Scope:
    """Defines the authorized boundaries for a penetration testing engagement.

    Every tool invocation and browser navigation is validated against
    this scope before execution proceeds.

    Attributes:
        name: Human-readable engagement name.
        allowed_targets: List of allowed hosts, CIDRs, or domains.
        excluded_targets: List of explicitly excluded hosts, CIDRs, or domains.
        rules: Granular allow/deny rules. Exclusions override inclusions.
        start_time: Optional start of the authorized engagement window.
        end_time: Optional end of the authorized engagement window.
        authorization_attestation: Reference to the signed authorization (e.g., doc ID).
        description: Free-text description of the engagement scope.
    """

    name: str
    allowed_targets: list[str] = field(default_factory=list)
    excluded_targets: list[str] = field(default_factory=list)
    rules: list[ScopeRule] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    authorization_attestation: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Normalize rules from the simple target lists into ScopeRule objects.

        Adds auto-generated rules for each entry in ``allowed_targets`` and
        ``excluded_targets``, skipping any that already have an explicit
        rule in ``rules`` with an identical ``(rule_type, value)`` pair.
        """
        existing: set[tuple[ScopeRuleType, str]] = {
            (r.rule_type, r.value) for r in self.rules
        }

        for target in self.allowed_targets:
            rule = self._infer_scope_rule(target, inclusive=True)
            key = (rule.rule_type, rule.value)
            if key not in existing:
                existing.add(key)
                self.rules.append(rule)

        for target in self.excluded_targets:
            rule = self._infer_scope_rule(target, inclusive=False)
            key = (rule.rule_type, rule.value)
            if key not in existing:
                existing.add(key)
                self.rules.append(rule)

    @staticmethod
    def _infer_scope_rule(target: str, *, inclusive: bool) -> ScopeRule:
        """Infer the appropriate ScopeRuleType from a target string.

        Checks:
        1. Single IP address → HOST rule
        2. CIDR notation → CIDR rule
        3. Domain or wildcard → DOMAIN rule
        """
        try:
            ipaddress.ip_address(target)
            rule_type = ScopeRuleType.ALLOW_HOST if inclusive else ScopeRuleType.EXCLUDE_HOST
        except ValueError:
            try:
                ipaddress.ip_network(target, strict=False)
                rule_type = ScopeRuleType.ALLOW_CIDR if inclusive else ScopeRuleType.EXCLUDE_CIDR
            except ValueError:
                rule_type = ScopeRuleType.ALLOW_DOMAIN if inclusive else ScopeRuleType.EXCLUDE_DOMAIN

        return ScopeRule(rule_type=rule_type, value=target)

    def check_target(self, target: str) -> ScopeCheckResult:
        """Check if a target string is within the allowed scope.

        Evaluation order:
        1. Explicit exclusion rules (deny if matched)
        2. Explicit inclusion rules (allow if matched)
        3. If no rule matches, deny by default (default-deny stance)
        """
        # Phase 1: check exclusion rules first
        for rule in self.rules:
            if rule.rule_type in (
                ScopeRuleType.EXCLUDE_HOST,
                ScopeRuleType.EXCLUDE_CIDR,
                ScopeRuleType.EXCLUDE_DOMAIN,
                ScopeRuleType.EXCLUDE_PORT,
            ):
                if rule.matches(target):
                    return ScopeCheckResult.deny(
                        reason=f"Target '{target}' matches exclusion rule: {rule.value}",
                        matched_rule=rule.value,
                    )

        # Phase 2: check inclusion rules
        for rule in self.rules:
            if rule.rule_type in (
                ScopeRuleType.ALLOW_HOST,
                ScopeRuleType.ALLOW_CIDR,
                ScopeRuleType.ALLOW_DOMAIN,
                ScopeRuleType.ALLOW_PORT,
            ):
                if rule.matches(target):
                    return ScopeCheckResult.allow(matched_rule=rule.value)

        # Phase 3: default-deny — no rule matched
        return ScopeCheckResult.deny(
            reason=f"Target '{target}' does not match any in-scope rule and is denied by default.",
        )

    def check_time_window(self, at_time: datetime | None = None) -> bool:
        """Check if *at_time* falls within the authorized engagement window.

        If no time window is configured, the check passes (no restriction).
        """
        if self.start_time is None and self.end_time is None:
            return True

        now = at_time or datetime.now(UTC)

        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False

        return True
