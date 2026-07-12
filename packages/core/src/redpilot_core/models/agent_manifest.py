"""Domain model for agent manifests — how agents are registered and discovered.

Each agent is defined by a manifest rather than hardcoded logic sprawled
through the orchestrator. This file defines the manifest schema and
associated enums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(Enum):
    """Tool permission levels that constrain what an agent can do.

    An agent inherits the permission level of whatever tool it's invoking
    and cannot escalate its own permissions at runtime.
    """

    READ_ONLY = "read_only"
    """Read-only information gathering. No modifications to the target."""

    WRITE = "write"
    """Can make changes that require approval before execution."""

    DANGEROUS = "dangerous"
    """Potentially destructive or irreversible actions. Always requires
    explicit human confirmation per action."""


class AgentCluster(Enum):
    """Cluster to which an agent belongs, determining grouping and ownership.

    The orchestrator uses clusters for:
    - Organizing agents in the TUI display
    - Determining retry budgets (recon gets more retries than exploitation)
    - Applying cluster-wide permission constraints
    """

    CORE = "core"
    """Planner, Task Manager, Critic, Reflection, Verifier, Memory, Retry agents."""

    RECON = "recon"
    """OSINT, Web Recon, Network Recon, Subdomain, DNS, Port Scan,
    Fingerprint, Directory Enumeration, Code Analysis, Cloud agents."""

    EXPLOITATION = "exploitation"
    """Exploit, Web Exploitation, SQLi, XSS, SSRF, RCE, Auth agents."""

    POST_EXPLOITATION = "post_exploitation"
    """Privilege Escalation, Container Escape, Lateral Movement,
    Post Exploitation, Active Directory agents."""

    EVIDENCE = "evidence"
    """Evidence Collector, Screenshot, Browser agents."""


class FailureHandlingStrategy(Enum):
    """Strategy for handling agent failures.

    Declared in the manifest so the Reflection Agent knows what to do
    without needing agent-specific logic.
    """

    RETRY_WITH_BACKOFF = "retry_with_backoff"
    MARK_PARTIAL = "mark_partial"
    NOTIFY_CRITIC = "notify_critic"
    ESCALATE_TO_HUMAN = "escalate_to_human"


@dataclass
class AgentManifest:
    """Declarative definition of an agent's capabilities, constraints, and behavior.

    This is the single source of truth for what an agent can do, what
    tools it can use, and how failures are handled. The orchestrator loads
    these manifests at startup to build its internal capability registry.

    Attributes:
        id: Unique agent identifier (e.g., "subdomain_agent", "sqli_agent").
        cluster: Which cluster this agent belongs to.
        responsibilities: Human-readable list of this agent's job description.
        inputs: Names of data this agent consumes (referenced by the Planner).
        outputs: Names of data this agent produces.
        tools_allowed: List of tool names this agent is permitted to invoke.
        tool_permission_level: Maximum permission level for tools this agent uses.
            (An agent cannot invoke a tool whose permission exceeds this level.)
        memory_access: Which memory stores this agent can read/write.
        escalation: Short description of escalation rules.
        failure_handling: Strategy for handling execution failures.
    """

    id: str
    cluster: AgentCluster
    responsibilities: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    tools_allowed: list[str] = field(default_factory=list)
    tool_permission_level: PermissionLevel = PermissionLevel.READ_ONLY
    memory_access: list[str] = field(default_factory=list)
    escalation: str = ""
    failure_handling: FailureHandlingStrategy = FailureHandlingStrategy.RETRY_WITH_BACKOFF

    def can_use_tool(self, tool_name: str, tool_permission: PermissionLevel) -> bool:
        """Check if this agent is allowed to invoke a specific tool.

        Checks both that the tool is in the allowed list and that
        the tool's permission level doesn't exceed the agent's cap.
        """
        if tool_name not in self.tools_allowed:
            return False
        return self._permission_rank(tool_permission) <= self._permission_rank(
            self.tool_permission_level,
        )

    @staticmethod
    def _permission_rank(level: PermissionLevel) -> int:
        """Rank permission levels for comparison (higher = more permissive)."""
        return {
            PermissionLevel.READ_ONLY: 0,
            PermissionLevel.WRITE: 1,
            PermissionLevel.DANGEROUS: 2,
        }[level]

    def to_manifest_entry(self) -> dict[str, str | list[str]]:
        """Serialize to a dict matching the YAML manifest format in the design doc."""
        return {
            "id": self.id,
            "cluster": self.cluster.value,
            "responsibilities": self.responsibilities,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "tools_allowed": self.tools_allowed,
            "tool_permission_level": self.tool_permission_level.value,
            "memory_access": self.memory_access,
            "escalation": self.escalation,
            "failure_handling": self.failure_handling.value,
        }

    @classmethod
    def from_manifest_entry(cls, data: dict[str, Any]) -> AgentManifest:
        """Create from a dict (deserialized from YAML/JSON manifest file)."""
        return cls(
            id=str(data["id"]),
            cluster=AgentCluster(str(data["cluster"])),
            responsibilities=list(data.get("responsibilities", [])),
            inputs=list(data.get("inputs", [])),
            outputs=list(data.get("outputs", [])),
            tools_allowed=list(data.get("tools_allowed", [])),
            tool_permission_level=PermissionLevel(str(data.get("tool_permission_level", "read_only"))),
            memory_access=list(data.get("memory_access", [])),
            escalation=str(data.get("escalation", "")),
            failure_handling=FailureHandlingStrategy(
                str(data.get("failure_handling", "retry_with_backoff"))
            ),
        )


# Registry of all built-in agents (from §4.2 of the architecture document).
# This is the canonical set; the orchestrator loads from this registry
# at startup and may be extended by plugins.
BUILTIN_AGENTS: dict[str, AgentManifest] = {
    agent.id: agent
    for agent in [
        # Core cluster
        AgentManifest(
            id="planner_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Decompose goal into a task graph (DAG)"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        AgentManifest(
            id="task_manager",
            cluster=AgentCluster.CORE,
            responsibilities=["Schedule, dispatch, track task graph nodes"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        AgentManifest(
            id="critic_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Independently review outputs for correctness and false positives"],
            inputs=["task_output", "finding"],
            outputs=["verification_result"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.NOTIFY_CRITIC,
        ),
        AgentManifest(
            id="reflection_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Decide retry vs. escalate vs. mark done"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        AgentManifest(
            id="verifier_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Re-validate a claimed finding before it enters the report"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.NOTIFY_CRITIC,
        ),
        AgentManifest(
            id="memory_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Summarize and compress context, manage recall"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.MARK_PARTIAL,
        ),
        AgentManifest(
            id="retry_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Re-execute failed task nodes with adjusted parameters"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        # Recon cluster
        AgentManifest(
            id="recon_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Passive and active information gathering"],
            tools_allowed=["nmap", "whois", "dnsrecon"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="subdomain_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Enumerate subdomains for in-scope domains"],
            inputs=["target_domains", "scope_rules"],
            outputs=["subdomain_list", "evidence_refs"],
            tools_allowed=["subfinder", "amass", "assetfinder", "httpx"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="directory_enum_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Content discovery via fuzzing"],
            tools_allowed=["ffuf", "dirsearch"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="code_analysis_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Static analysis of provided source code"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="cloud_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Cloud misconfiguration checks"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        # Exploitation cluster
        AgentManifest(
            id="exploit_agent",
            cluster=AgentCluster.EXPLOITATION,
            responsibilities=["Attempt to validate vulnerabilities"],
            tool_permission_level=PermissionLevel.WRITE,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="web_exploitation_agent",
            cluster=AgentCluster.EXPLOITATION,
            responsibilities=["Web-specific vulnerability validation"],
            tools_allowed=["sqlmap", "nuclei", "burpsuite"],
            tool_permission_level=PermissionLevel.WRITE,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        AgentManifest(
            id="auth_agent",
            cluster=AgentCluster.EXPLOITATION,
            responsibilities=["Test authentication and authorization flaws"],
            tool_permission_level=PermissionLevel.WRITE,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        # Post-exploitation cluster
        AgentManifest(
            id="post_exploitation_agent",
            cluster=AgentCluster.POST_EXPLOITATION,
            responsibilities=["Impact documentation, cleanup verification"],
            tool_permission_level=PermissionLevel.DANGEROUS,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        AgentManifest(
            id="privilege_escalation_agent",
            cluster=AgentCluster.POST_EXPLOITATION,
            responsibilities=["Post-compromise privilege escalation in authorized scope only"],
            tool_permission_level=PermissionLevel.DANGEROUS,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        AgentManifest(
            id="ad_agent",
            cluster=AgentCluster.POST_EXPLOITATION,
            responsibilities=["Active Directory enumeration and attack path analysis"],
            tool_permission_level=PermissionLevel.DANGEROUS,
            failure_handling=FailureHandlingStrategy.ESCALATE_TO_HUMAN,
        ),
        # Evidence cluster
        AgentManifest(
            id="evidence_collector",
            cluster=AgentCluster.EVIDENCE,
            responsibilities=["Capture proof: screenshots, request/response pairs, logs"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.MARK_PARTIAL,
        ),
        AgentManifest(
            id="browser_agent",
            cluster=AgentCluster.EVIDENCE,
            responsibilities=["Drive Playwright for UI-layer testing and evidence"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        ),
        # Reporting
        AgentManifest(
            id="report_agent",
            cluster=AgentCluster.CORE,
            responsibilities=["Compile verified findings into report.md"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.MARK_PARTIAL,
        ),
    ]
}
