"""Agent registry and agent instance management.

The AgentRegistry is the thin layer between a ``TaskNode``'s ``agent_id``
and a running agent instance that calls ``ToolRunner``. The Task Manager
uses this to spawn, track, and reconcile agent instances.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from redpilot_core.models.agent_manifest import AgentManifest


@dataclass
class AgentResult:
    """Result produced by an agent instance on completion."""

    success: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_name: str = ""
    execution_time_ms: int = 0


class AgentInstance(ABC):
    """A single running instance of an agent.

    Created by ``AgentRegistry.spawn_instance()`` and tracked by
    the Task Manager during the node's ``DISPATCHED`` / ``EXECUTING``
    lifecycle. Fire-and-forget from the Task Manager's perspective:
    ``start()`` returns immediately and the manager receives results
    via the ``on_complete`` callback.
    """

    id: str
    agent_manifest: AgentManifest
    node_id: str
    graph_id: str
    started_at: datetime

    def __init__(
        self,
        agent_manifest: AgentManifest,
        node_id: str,
        graph_id: str,
    ) -> None:
        self.id = f"INST-{uuid4().hex[:8].upper()}"
        self.agent_manifest = agent_manifest
        self.node_id = node_id
        self.graph_id = graph_id
        self.started_at = datetime.now(UTC)

    @abstractmethod
    async def start(
        self,
        on_complete: Callable[[str, str, AgentResult], None],
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        """Begin execution. Fire-and-forget — returns immediately.

        When the agent finishes (success or failure), calls
        ``on_complete(node_id, graph_id, result)``.

        Args:
            on_complete: Callback invoked with ``(node_id, graph_id, result)``.
            input_payload: The node's input payload (target, scope ref, etc.).
        """

    @abstractmethod
    async def cancel(self) -> None:
        """Attempt to cancel a running instance. No-op if already completed."""

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Whether the instance is still running (not yet completed/failed)."""


class AgentRegistry:
    """Registry for agent manifests and their running instances.

    The Task Manager uses this to:
    - Look up agent manifests by ``agent_id``
    - Spawn new agent instances
    - Track and query running instances (for crash recovery)
    """

    def __init__(self) -> None:
        self._manifests: dict[str, AgentManifest] = {}
        self._instances: dict[str, AgentInstance] = {}

    def register_manifest(self, manifest: AgentManifest) -> None:
        """Register an agent manifest for lookup by ``id``."""
        self._manifests[manifest.id] = manifest

    def register_manifests(self, manifests: dict[str, AgentManifest]) -> None:
        """Register multiple agent manifests at once."""
        self._manifests.update(manifests)

    def get_manifest(self, agent_id: str) -> AgentManifest | None:
        """Look up an agent manifest by ID."""
        return self._manifests.get(agent_id)

    def spawn_instance(
        self,
        agent_manifest: AgentManifest,
        node_id: str,
        graph_id: str,
    ) -> AgentInstance:
        """Create a new agent instance for the given manifest.

        The instance is registered in the registry but NOT started —
        the Task Manager calls ``instance.start()`` separately after
        persisting the ``DISPATCHED`` state.

        Args:
            agent_manifest: The manifest to create an instance for.
            node_id: The task node this instance is assigned to.
            graph_id: The graph this instance belongs to.

        Returns:
            A new (unstarted) AgentInstance.
        """
        instance = self._instance_factory(agent_manifest, node_id, graph_id)
        self._instances[instance.id] = instance
        return instance

    def get_instance(self, instance_id: str) -> AgentInstance | None:
        """Look up a running (or completed) instance by ID."""
        return self._instances.get(instance_id)

    def remove_instance(self, instance_id: str) -> None:
        """Remove a completed/cancelled instance from the registry."""
        self._instances.pop(instance_id, None)

    def count_alive(self) -> int:
        """Count instances that are still alive."""
        return sum(1 for inst in self._instances.values() if inst.is_alive)

    def _instance_factory(
        self,
        manifest: AgentManifest,
        node_id: str,
        graph_id: str,
    ) -> AgentInstance:
        """Create an appropriate AgentInstance for the given manifest.

        In v0.1, all agents are ``GenericAgent``. Future versions may
        dispatch to different instance types based on the manifest's
        cluster or tool requirements.
        """
        # Avoid circular import by importing here
        from redpilot_orchestrator.agents.generic_agent import GenericAgent

        return GenericAgent(
            agent_manifest=manifest,
            node_id=node_id,
            graph_id=graph_id,
        )
