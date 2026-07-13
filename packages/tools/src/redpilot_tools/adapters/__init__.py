"""Tool adapter implementations — one module per tool."""

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

__all__ = [
    "BrowserAdapter",
    "EditFileAdapter",
    "ListDirectoryAdapter",
    "NmapAdapter",
    "ReadFileAdapter",
    "ShellExecAdapter",
    "SpawnSubAgentAdapter",
    "SubfinderAdapter",
    "WriteFileAdapter",
]
