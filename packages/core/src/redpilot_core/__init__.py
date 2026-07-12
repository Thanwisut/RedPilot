"""REDPILOT shared domain models — the foundation every other module depends on.

This package contains pure domain models with no I/O. It defines:

- :class:`Scope` / :class:`ScopeRule` — target scope definition and validation
- :class:`Finding` / :class:`EvidenceRef` / :class:`RiskScore` — vulnerability findings
- :class:`TaskGraph` / :class:`TaskNode` — DAG-based engagement progress tracking
- :class:`ToolResult` — structured tool execution output
- :class:`AgentManifest` — agent registration and capability declaration
- :class:`ToolManifest` — tool registration and sandbox profile declaration
- :class:`ScopeGuard` / :class:`ApprovalGate` — security enforcement gates
"""

from redpilot_core.guards.approval_gate import ApprovalGate, ApprovalRequest
from redpilot_core.guards.scope_guard import ScopeGuard
from redpilot_core.models.agent_manifest import AgentCluster, AgentManifest, PermissionLevel
from redpilot_core.models.finding import (
    EvidenceRef,
    Finding,
    MitreAttackTechnique,
    OwaspCategory,
    RiskScore,
    Severity,
)
from redpilot_core.models.scope import Scope, ScopeCheckResult, ScopeRule
from redpilot_core.models.task_graph import EdgeType, TaskGraph, TaskNode, TaskStatus
from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest
from redpilot_core.models.tool_result import ToolResult, ToolResultStatus

__all__ = [
    "AgentCluster",
    "AgentManifest",
    "ApprovalGate",
    "ApprovalRequest",
    "EdgeType",
    "EvidenceRef",
    "Finding",
    "MitreAttackTechnique",
    "OwaspCategory",
    "PermissionLevel",
    "RiskScore",
    "SandboxProfile",
    "Scope",
    "ScopeCheckResult",
    "ScopeGuard",
    "ScopeRule",
    "Severity",
    "TaskGraph",
    "TaskNode",
    "TaskStatus",
    "ToolManifest",
    "ToolResult",
    "ToolResultStatus",
]
