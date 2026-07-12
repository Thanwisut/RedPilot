"""REDPILOT orchestrator — Master Agent, Task Manager, scheduling, agent instances.

This package implements the orchestration layer from the architecture doc (§5).
It depends on ``redpilot-core`` for domain models and ``redpilot-tools`` for
the Tool Execution Layer.
"""

from redpilot_orchestrator.agent_registry import AgentInstance, AgentRegistry, AgentResult
from redpilot_orchestrator.graph_store import (
    FileBackedGraphStore,
    InMemoryGraphStore,
    TaskGraphStore,
)
from redpilot_orchestrator.task_manager import TaskManager

__all__ = [
    "AgentInstance",
    "AgentRegistry",
    "AgentResult",
    "FileBackedGraphStore",
    "InMemoryGraphStore",
    "TaskGraphStore",
    "TaskManager",
]
