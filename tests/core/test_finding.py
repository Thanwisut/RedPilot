"""Tests for finding domain models — Finding, EvidenceRef, RiskScore."""

from datetime import datetime

from redpilot_core.models.finding import (
    EvidenceId,
    EvidenceRef,
    Finding,
    MitreAttackTechnique,
    OwaspCategory,
    RiskScore,
    Severity,
)


class TestRiskScore:
    """RiskScore creation and mapping."""

    def test_from_cvss_score_none(self) -> None:
        assert RiskScore.from_cvss_score(0.0) == RiskScore.NONE

    def test_from_cvss_score_low(self) -> None:
        assert RiskScore.from_cvss_score(3.9) == RiskScore.LOW

    def test_from_cvss_score_medium(self) -> None:
        assert RiskScore.from_cvss_score(4.0) == RiskScore.MEDIUM
        assert RiskScore.from_cvss_score(6.9) == RiskScore.MEDIUM

    def test_from_cvss_score_high(self) -> None:
        assert RiskScore.from_cvss_score(7.0) == RiskScore.HIGH
        assert RiskScore.from_cvss_score(8.9) == RiskScore.HIGH

    def test_from_cvss_score_critical(self) -> None:
        assert RiskScore.from_cvss_score(9.0) == RiskScore.CRITICAL
        assert RiskScore.from_cvss_score(10.0) == RiskScore.CRITICAL

    def test_value_strings(self) -> None:
        assert RiskScore.HIGH.value == "high"
        assert RiskScore.CRITICAL.value == "critical"


class TestEvidenceRef:
    """EvidenceRef creation and field validation."""

    def test_create_evidence_ref(self) -> None:
        evidence = EvidenceRef(
            id=EvidenceId("EVID-001"),
            kind="screenshot",
            description="Login page showing SQL injection error",
            path="/evidence/screenshots/sqli_login.png",
        )
        assert evidence.id == "EVID-001"
        assert evidence.kind == "screenshot"
        assert evidence.description == "Login page showing SQL injection error"
        assert evidence.path == "/evidence/screenshots/sqli_login.png"

    def test_auto_timestamp(self) -> None:
        evidence = EvidenceRef(
            id=EvidenceId("EVID-002"),
            kind="tool_output",
            description="nmap scan result",
            path="/evidence/tool_output/scan.xml",
        )
        assert isinstance(evidence.captured_at, datetime)


class TestFinding:
    """Finding creation, verification, and evidence attachment."""

    def test_create_minimal_finding(self) -> None:
        finding = Finding(
            title="SQL Injection in login.php",
            description="The login endpoint is vulnerable to time-based SQL injection.",
        )
        assert finding.title == "SQL Injection in login.php"
        assert finding.severity == RiskScore.MEDIUM  # default
        assert not finding.verified
        assert finding.id.startswith("FIND-")
        assert len(finding.evidence_refs) == 0

    def test_create_with_full_fields(self) -> None:
        finding = Finding(
            title="Reflected XSS in search",
            description="Search parameter reflects unsanitized input.",
            severity=RiskScore.HIGH,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:L/A:N",
            owasp_mappings=[OwaspCategory.A03_INJECTION],
            mitre_attack_mappings=[MitreAttackTechnique.T1190_EXPLOIT_PUBLIC_FACING_APP],
            affected_target="10.0.0.50",
            affected_endpoint="/search?q=test",
            reproduction_steps=[
                "Navigate to /search?q=<script>alert(1)</script>",
                "Observe the alert box",
            ],
            impact="An attacker could steal session cookies.",
            recommendations=["Sanitize user input", "Implement CSP headers"],
        )
        assert finding.severity == RiskScore.HIGH
        assert len(finding.owasp_mappings) == 1
        assert finding.owasp_mappings[0] == OwaspCategory.A03_INJECTION
        assert finding.affected_target == "10.0.0.50"
        assert len(finding.reproduction_steps) == 2
        assert len(finding.recommendations) == 2

    def test_verify_finding(self) -> None:
        finding = Finding(
            title="Test Finding",
            description="A test finding.",
        )
        assert not finding.verified
        assert finding.verified_at is None

        finding.verify()
        assert finding.verified
        assert finding.verified_at is not None

    def test_add_evidence(self) -> None:
        finding = Finding(
            title="Test Finding",
            description="A test finding.",
        )
        evidence = EvidenceRef(
            id=EvidenceId("EVID-001"),
            kind="screenshot",
            description="Evidence screenshot",
            path="/evidence/screenshot.png",
        )

        finding.add_evidence(evidence)
        assert len(finding.evidence_refs) == 1
        assert finding.evidence_refs[0].id == "EVID-001"

        # Adding the same evidence twice should not duplicate
        finding.add_evidence(evidence)
        assert len(finding.evidence_refs) == 1

    def test_risk_label(self) -> None:
        finding = Finding(
            title="Critical Vuln",
            description="A critical finding.",
            severity=RiskScore.CRITICAL,
        )
        assert finding.risk_label == "CRITICAL"

    def test_owasp_enum_values(self) -> None:
        assert "A01:2021" in OwaspCategory.A01_BROKEN_ACCESS_CONTROL.value
        assert "Injection" in OwaspCategory.A03_INJECTION.value

    def test_mitre_enum_values(self) -> None:
        assert "T1190" in MitreAttackTechnique.T1190_EXPLOIT_PUBLIC_FACING_APP.value
        assert "Active Scanning" in MitreAttackTechnique.T1595_ACTIVE_SCANNING.value


class TestSeverity:
    """Severity enum for non-CVSS contexts."""

    def test_values(self) -> None:
        assert Severity.INFO.value == "info"
        assert Severity.HIGH.value == "high"
