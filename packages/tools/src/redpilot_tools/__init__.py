"""REDPILOT Tool Execution Layer — adapters, runner, sandbox, audit, manifests.

This package implements the Tool Execution Layer from the architecture doc (§6).
It depends on ``redpilot-core`` for shared domain models and security guards.
"""

from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.adapters.browser_adapter import BrowserAdapter
from redpilot_tools.adapters.filesystem_adapter import (
    EditFileAdapter,
    ListDirectoryAdapter,
    ReadFileAdapter,
    WriteFileAdapter,
)
from redpilot_tools.adapters.nmap_adapter import NmapAdapter
from redpilot_tools.adapters.shell_exec_adapter import ShellExecAdapter
from redpilot_tools.adapters.spawn_sub_agent_adapter import SpawnSubAgentAdapter
from redpilot_tools.adapters.subfinder_adapter import SubfinderAdapter
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
from redpilot_tools.utils.path_safety import (
    PathEscapeError,
    resolve_safe_path,
    resolve_safe_path_allow_missing,
    resolve_safe_path_must_exist,
)

__all__ = [
    "BrowserAdapter",
    "DockerSandboxFactory",
    "EditFileAdapter",
    "ListDirectoryAdapter",
    "NmapAdapter",
    "PathEscapeError",
    "PROFILE_RESOURCES",
    "AuditEntry",
    "AuditLog",
    "InMemoryAuditLog",
    "NetworkPolicy",
    "OpenPort",
    "PortScanResult",
    "ReadFileAdapter",
    "ResourceLimits",
    "SandboxContext",
    "SandboxExecutionResult",
    "SandboxFactory",
    "ShellExecAdapter",
    "SpawnSubAgentAdapter",
    "SubfinderAdapter",
    "ToolAdapter",
    "ToolInvocationRequest",
    "ToolRunner",
    "WriteFileAdapter",
    "resolve_safe_path",
    "resolve_safe_path_allow_missing",
    "resolve_safe_path_must_exist",
]
