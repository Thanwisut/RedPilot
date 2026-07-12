"""REDPILOT Tool Execution Layer — adapters, runner, sandbox, audit, manifests.

This package implements the Tool Execution Layer from the architecture doc (§6).
It depends on ``redpilot-core`` for shared domain models and security guards.
"""

from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.audit import AuditEntry, AuditLog, InMemoryAuditLog
from redpilot_tools.models import OpenPort, PortScanResult
from redpilot_tools.runner import ToolInvocationRequest, ToolRunner
from redpilot_tools.sandbox import (
    PROFILE_RESOURCES,
    DockerSandboxFactory,
    NetworkPolicy,
    ResourceLimits,
    SandboxContext,
    SandboxExecutionResult,
    SandboxFactory,
)

__all__ = [
    "DockerSandboxFactory",
    "PROFILE_RESOURCES",
    "AuditEntry",
    "AuditLog",
    "InMemoryAuditLog",
    "NetworkPolicy",
    "OpenPort",
    "PortScanResult",
    "ResourceLimits",
    "SandboxContext",
    "SandboxExecutionResult",
    "SandboxFactory",
    "ToolAdapter",
    "ToolInvocationRequest",
    "ToolRunner",
]
