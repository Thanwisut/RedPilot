"""Domain model for vulnerability findings and evidence references."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import NewType
from uuid import uuid4

FindingId = NewType("FindingId", str)
EvidenceId = NewType("EvidenceId", str)


class RiskScore(Enum):
    """Qualitative risk rating aligned with CVSS severity bands."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_cvss_score(cls, score: float) -> RiskScore:
        """Map a CVSS v3.x numeric score (0.0–10.0) to a qualitative rating."""
        if score == 0.0:
            return cls.NONE
        if score < 4.0:
            return cls.LOW
        if score < 7.0:
            return cls.MEDIUM
        if score < 9.0:
            return cls.HIGH
        return cls.CRITICAL

    @classmethod
    def from_cvss_vector(cls, vector: str) -> RiskScore:
        """Parse a CVSS v3 vector string and return the qualitative severity.

        Only extracts the base score; environmental/temporal are ignored
        at this tier. Returns MEDIUM if parsing fails.
        """
        try:
            # Simple parser: look for CVSS:3.x/AV:... pattern
            # Base Score ≈ f(AV, AC, PR, UI, S, C, I, A)
            # For v0.1 we use a lookup-based approximation
            parts = {}
            for segment in vector.split("/"):
                if ":" in segment:
                    k, v = segment.split(":", 1)
                    parts[k] = v

            av = parts.get("AV", "N")
            c_val = parts.get("C", "N")
            i_val = parts.get("I", "N")
            a_val = parts.get("A", "N")

            # Simplified heuristic: count high/critical impacts
            impact_count = sum(1 for v in (c_val, i_val, a_val) if v in ("H", "C"))
            exploitability = av == "N"  # Network-accessible is easier to exploit

            if impact_count == 3 and c_val == "H":
                return cls.CRITICAL
            if impact_count >= 2:
                return cls.HIGH
            if impact_count >= 1 and exploitability:
                return cls.MEDIUM
            if impact_count >= 1:
                return cls.LOW
            return cls.NONE

        except (ValueError, AttributeError, KeyError):
            return cls.MEDIUM


class Severity(Enum):
    """Severity for non-CVSS contexts (info, warning, error)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OwaspCategory(Enum):
    """OWASP Top 10 (2021) categories."""

    A01_BROKEN_ACCESS_CONTROL = "A01:2021 - Broken Access Control"
    A02_CRYPTOGRAPHIC_FAILURES = "A02:2021 - Cryptographic Failures"
    A03_INJECTION = "A03:2021 - Injection"
    A04_INSECURE_DESIGN = "A04:2021 - Insecure Design"
    A05_SECURITY_MISCONFIGURATION = "A05:2021 - Security Misconfiguration"
    A06_VULNERABLE_COMPONENTS = "A06:2021 - Vulnerable and Outdated Components"
    A07_IDENTIFICATION_FAILURES = "A07:2021 - Identification and Authentication Failures"
    A08_SOFTWARE_DATA_INTEGRITY_FAILURES = "A08:2021 - Software and Data Integrity Failures"
    A09_SECURITY_LOGGING_FAILURES = "A09:2021 - Security Logging and Monitoring Failures"
    A10_SERVER_SIDE_REQUEST_FORGERY = "A10:2021 - Server-Side Request Forgery (SSRF)"


class MitreAttackTechnique(Enum):
    """Representative MITRE ATT&CK enterprise techniques relevant to penetration testing."""

    # Reconnaissance
    T1595_ACTIVE_SCANNING = "T1595 - Active Scanning"
    T1590_GATHER_VICTIM_NETWORK_INFO = "T1590 - Gather Victim Network Information"
    T1592_GATHER_VICTIM_HOST_INFO = "T1592 - Gather Victim Host Information"

    # Resource Development
    T1588_OBTAIN_CAPABILITIES = "T1588 - Obtain Capabilities"

    # Initial Access
    T1190_EXPLOIT_PUBLIC_FACING_APP = "T1190 - Exploit Public-Facing Application"
    T1133_EXTERNAL_REMOTE_SERVICES = "T1133 - External Remote Services"
    T1078_VALID_ACCOUNTS = "T1078 - Valid Accounts"

    # Execution
    T1059_COMMAND_AND_SCRIPTING_INTERPRETER = "T1059 - Command and Scripting Interpreter"

    # Persistence
    T1098_ACCOUNT_MANIPULATION = "T1098 - Account Manipulation"

    # Privilege Escalation
    T1068_EXPLOITATION_FOR_PRIVILEGE_ESCALATION = "T1068 - Exploitation for Privilege Escalation"

    # Defense Evasion
    T1070_INDICATOR_REMOVAL = "T1070 - Indicator Removal"

    # Credential Access
    T1110_BRUTE_FORCE = "T1110 - Brute Force"
    T1552_UNSECURED_CREDENTIALS = "T1552 - Unsecured Credentials"

    # Discovery
    T1046_NETWORK_SERVICE_DISCOVERY = "T1046 - Network Service Discovery"
    T1082_SYSTEM_INFORMATION_DISCOVERY = "T1082 - System Information Discovery"

    # Lateral Movement
    T1021_REMOTE_SERVICES = "T1021 - Remote Services"

    # Collection
    T1005_DATA_FROM_LOCAL_SYSTEM = "T1005 - Data from Local System"

    # Command and Control
    T1071_APPLICATION_LAYER_PROTOCOL = "T1071 - Application Layer Protocol"

    # Exfiltration
    T1048_EXFILTRATION_OVER_ALT_PROTOCOL = "T1048 - Exfiltration Over Alternative Protocol"

    # Impact
    T1491_DEFACEMENT = "T1491 - Defacement"
    T1485_DATA_DESTRUCTION = "T1485 - Data Destruction"


@dataclass(frozen=True)
class EvidenceRef:
    """Reference to a piece of evidence stored in the evidence cache.

    Attributes:
        id: Unique evidence identifier (content-addressed in the cache).
        kind: Type of evidence — screenshot, request_response, tool_output, log.
        description: Human-readable description of what this evidence shows.
        path: Relative path to the evidence artifact in the cache.
        captured_at: When the evidence was captured.
    """

    id: EvidenceId
    kind: str  # "screenshot" | "request_response" | "tool_output" | "log"
    description: str
    path: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Finding:
    """A verified vulnerability finding within a penetration testing engagement.

    Findings are only created after passing through the Critic Agent's
    verification step. Unconfirmed leads live in a separate context.

    Attributes:
        id: Unique finding identifier.
        title: Short, descriptive title (e.g., "SQL Injection in login.php").
        description: Detailed technical description of the finding.
        severity: Qualitative risk rating.
        cvss_vector: CVSS v3.x vector string if scored.
        cvss_score: Computed CVSS numeric score (0.0–10.0).
        owasp_mappings: Relevant OWASP Top 10 categories.
        mitre_attack_mappings: Relevant MITRE ATT&CK techniques.
        evidence_refs: References to captured evidence artifacts.
        affected_target: The specific target where this was found.
        affected_endpoint: The specific URL, path, or component affected.
        reproduction_steps: Step-by-step reproduction instructions.
        impact: Description of potential business/technical impact.
        recommendations: Remediation recommendations.
        verified: Whether this finding passed Critic verification.
        discovered_at: When the finding was first identified.
        verified_at: When the finding passed verification (if applicable).
    """

    title: str
    description: str
    severity: RiskScore = RiskScore.MEDIUM
    id: FindingId = field(default_factory=lambda: FindingId(f"FIND-{uuid4().hex[:8].upper()}"))
    cvss_vector: str | None = None
    cvss_score: float | None = None
    owasp_mappings: list[OwaspCategory] = field(default_factory=list)
    mitre_attack_mappings: list[MitreAttackTechnique] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    affected_target: str = ""
    affected_endpoint: str = ""
    reproduction_steps: list[str] = field(default_factory=list)
    impact: str = ""
    recommendations: list[str] = field(default_factory=list)
    verified: bool = False
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    verified_at: datetime | None = None

    def verify(self) -> None:
        """Mark this finding as Critic-verified."""
        self.verified = True
        self.verified_at = datetime.now(UTC)

    def add_evidence(self, evidence: EvidenceRef) -> None:
        """Attach an evidence reference to this finding."""
        if evidence not in self.evidence_refs:
            self.evidence_refs.append(evidence)

    @property
    def risk_label(self) -> str:
        """Return an uppercase severity label string (e.g., 'HIGH', 'CRITICAL')."""
        return self.severity.value.upper()
