"""Domain model for the engagement Task Graph — a DAG of work items.

This is the single source of truth for engagement progress, persisted
after every state transition so crashed sessions can resume.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

NodeId = str


class TaskStatus(Enum):
    """Lifecycle status of a task node in the engagement graph.

    State machine (dispatch-relevant subset):
        PENDING → READY → DISPATCHED → EXECUTING → COMPLETED | FAILED | BLOCKED
        FAILED → READY (if retry budget remains) | BLOCKED (if exhausted)
    """

    PENDING = "pending"
    """Initial state — dependencies may still be unmet."""
    READY = "ready"
    """All dependencies are Completed — eligible for dispatch."""
    DISPATCHED = "dispatched"
    """Task Manager has committed the node to an agent instance but hasn't
    yet gotten confirmation the agent started. Crash-recoverable."""
    EXECUTING = "executing"
    """Agent instance confirmed execution has started."""
    COMPLETED = "completed"
    """Agent returned success with output_payload."""
    FAILED = "failed"
    """Agent returned error — may retry if budget remains."""
    ABORTED = "aborted"
    BLOCKED = "blocked"
    """Retry budget exhausted — node will not execute again."""


class EdgeType(Enum):
    """Semantic type of a dependency edge between task nodes."""

    DEPENDS_ON = "depends_on"  # Standard prerequisite: B depends on A finishing
    TRIGGERED_BY = "triggered_by"  # B is triggered by A's result (may run concurrently)
    BLOCKED_BY = "blocked_by"  # B is blocked by A (A must succeed first)


@dataclass
class TaskNode:
    """A single unit of work in the engagement task graph.

    Attributes:
        id: Unique node identifier.
        agent_id: The agent assigned to execute this node (set at dispatch time).
        dependencies: IDs of nodes that must complete before this one runs.
        edge_types: Maps dependency node ID -> edge type for semantic ordering.
        status: Current lifecycle status.
        retry_count: How many times execution has been attempted.
        max_retries: Maximum retry attempts before escalation.
        payload: Agent-specific parameters and configuration for execution.
        artifacts: List of artifact IDs produced by this node's execution.
        result_ref: Reference to the ToolResult produced (set post-execution).
        metadata: Arbitrary key-value metadata for the orchestrator's use.
        created_at: When this node was created.
        started_at: When execution first began.
        completed_at: When execution finished (success or terminal failure).
    """

    id: NodeId = field(default_factory=lambda: f"NODE-{uuid4().hex[:8].upper()}")
    agent_id: str | None = None
    dependencies: list[NodeId] = field(default_factory=list)
    edge_types: dict[NodeId, EdgeType] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    result_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # -- New fields for the dispatch loop --
    retry_budget: int = 2
    """Maximum retry attempts before the node is Blocked.
    Defaults to 2 (matched to recon cluster default from the architecture doc)."""
    input_payload: dict[str, Any] = field(default_factory=dict)
    """What the agent needs — target, scope ref, prior results."""
    output_payload: dict[str, Any] | None = None
    """Populated on Completed with the agent's structured result."""
    failure_reason: str | None = None
    """Populated on Failed/Blocked with the error description."""
    assigned_agent_instance_id: str | None = None
    """Set on dispatch, cleared on terminal state. Links to AgentInstance."""
    updated_at: datetime | None = None
    """Updated on every state transition — used for stale detection."""

    @property
    def is_terminal(self) -> bool:
        """Whether this node has reached a terminal (non-retryable) state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
            TaskStatus.ABORTED,
        )

    @property
    def is_ready(self) -> bool:
        """Whether all dependencies have completed successfully and the node
        is in a state eligible for dispatch."""
        return self.status == TaskStatus.READY

    @property
    def is_awaiting_result(self) -> bool:
        """Whether this node is in a state where a result callback is expected."""
        return self.status in (TaskStatus.DISPATCHED, TaskStatus.EXECUTING)

    @property
    def has_retry_budget(self) -> bool:
        """Whether this node still has retry attempts remaining."""
        return self.retry_count < self.max_retries

    # Internal: not serialized — set during graph construction
    _dependencies_resolved: list[TaskNode] = field(default_factory=list, repr=False)


@dataclass
class TaskGraph:
    """A directed acyclic graph (DAG) representing engagement work items.

    The Task Graph is the single source of truth for engagement progress.
    It is persisted after every state transition so that a crashed session
    can resume gracefully.

    Attributes:
        nodes: All nodes in the graph, keyed by node ID.
        entry_points: Node IDs with no dependencies (the starting points).
        metadata: Engagement-level metadata (name, target, start time, etc.).
    """

    nodes: dict[NodeId, TaskNode] = field(default_factory=dict)
    entry_points: list[NodeId] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(
        self,
        node: TaskNode | None = None,
        *,
        dependencies: list[NodeId] | None = None,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> TaskNode:
        """Add a node to the graph.

        Args:
            node: A pre-constructed TaskNode (optional).
            dependencies: Node IDs this node depends on.
            payload: Agent-specific payload.
            **kwargs: Passed to TaskNode() if *node* is not provided.

        Returns:
            The added (or passed-in) TaskNode.
        """
        if node is None:
            node = TaskNode(
                dependencies=dependencies or [],
                payload=payload or {},
                **kwargs,
            )

        # Resolve dependency references
        node._dependencies_resolved = [
            self.nodes[dep_id] for dep_id in node.dependencies if dep_id in self.nodes
        ]

        self.nodes[node.id] = node

        if not node.dependencies:
            self.entry_points.append(node.id)

        return node

    def get_ready_nodes(self) -> list[TaskNode]:
        """Promote eligible PENDING nodes and return all READY nodes."""
        self.promote_ready_nodes()
        return self.get_nodes_by_status(TaskStatus.READY)

    def topological_sort(self) -> list[TaskNode]:
        """Return nodes in topological (dependency-respecting) order.

        Raises:
            ValueError: If the graph contains a cycle.
        """
        in_degree: dict[NodeId, int] = {}
        for node_id, node in self.nodes.items():
            in_degree[node_id] = len(node.dependencies)

        queue: deque[NodeId] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )

        sorted_nodes: list[TaskNode] = []
        while queue:
            nid = queue.popleft()
            sorted_nodes.append(self.nodes[nid])
            # Decrease in-degree of all nodes that depend on this one
            for other_id, other_node in self.nodes.items():
                if nid in other_node.dependencies:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        if len(sorted_nodes) != len(self.nodes):
            msg = "TaskGraph contains a cycle — topological sort is not possible"
            raise ValueError(msg)

        return sorted_nodes

    def update_status(self, node_id: NodeId, status: TaskStatus) -> None:
        """Update a node's status and timestamps accordingly.

        This is the primary state-transition method; every status change
        should go through here so timestamps are always consistent.
        """
        node = self.nodes[node_id]
        old_status = node.status
        node.status = status

        now = datetime.now(UTC)
        node.updated_at = now

        # Clear dispatched link when leaving awaiting-result states
        if old_status in (TaskStatus.DISPATCHED, TaskStatus.EXECUTING) and status not in (
            TaskStatus.DISPATCHED, TaskStatus.EXECUTING,
        ):
            node.assigned_agent_instance_id = None

        if status in (TaskStatus.DISPATCHED, TaskStatus.EXECUTING) and node.started_at is None:
            node.started_at = now
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                        TaskStatus.BLOCKED, TaskStatus.ABORTED):
            node.completed_at = now

    def increment_retry(self, node_id: NodeId) -> None:
        """Increment retry count and transition to RETRYING state.

        If the retry budget is exhausted, transitions to BLOCKED.
        """
        node = self.nodes[node_id]
        node.retry_count += 1

        if node.retry_count >= node.max_retries:
            self.update_status(node_id, TaskStatus.BLOCKED)
        else:
            self.update_status(node_id, TaskStatus.READY)

    def promote_ready_nodes(self) -> list[NodeId]:
        """Walk all PENDING nodes and promote any whose dependencies are
        all Completed to READY. Returns the newly-promoted node IDs.

        Called after a node completes, before the next dispatch tick.
        """
        promoted: list[NodeId] = []
        for node in self.nodes.values():
            if node.status != TaskStatus.PENDING:
                continue
            if all(
                dep.status == TaskStatus.COMPLETED
                for dep in node._dependencies_resolved
            ):
                node.status = TaskStatus.READY
                node.updated_at = datetime.now(UTC)
                promoted.append(node.id)
        return promoted

    def get_nodes_by_status(self, status: TaskStatus) -> list[TaskNode]:
        """Return all nodes with the given status."""
        return [n for n in self.nodes.values() if n.status == status]

    def all_terminal(self) -> bool:
        """Whether every node in the graph has reached a terminal state."""
        return all(n.is_terminal for n in self.nodes.values())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a JSON-compatible dictionary for persistence."""
        return {
            "nodes": {
                nid: {
                    "id": node.id,
                    "agent_id": node.agent_id,
                    "dependencies": node.dependencies,
                    "edge_types": {k: v.value for k, v in node.edge_types.items()},
                    "status": node.status.value,
                    "retry_count": node.retry_count,
                    "max_retries": node.max_retries,
                    "payload": node.payload,
                    "input_payload": node.input_payload,
                    "output_payload": node.output_payload,
                    "failure_reason": node.failure_reason,
                    "assigned_agent_instance_id": node.assigned_agent_instance_id,
                    "artifacts": node.artifacts,
                    "result_ref": node.result_ref,
                    "metadata": node.metadata,
                    "created_at": node.created_at.isoformat(),
                    "started_at": node.started_at.isoformat() if node.started_at else None,
                    "completed_at": node.completed_at.isoformat() if node.completed_at else None,
                    "updated_at": node.updated_at.isoformat() if node.updated_at else None,
                }
                for nid, node in self.nodes.items()
            },
            "entry_points": self.entry_points,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskGraph:
        """Deserialize a previously serialized graph (for session recovery)."""
        nodes: dict[NodeId, TaskNode] = {}
        for nid, node_data in data["nodes"].items():
            node = TaskNode(
                id=node_data["id"],
                agent_id=node_data.get("agent_id"),
                dependencies=node_data.get("dependencies", []),
                edge_types={
                    k: EdgeType(v) for k, v in node_data.get("edge_types", {}).items()
                },
                status=TaskStatus(node_data["status"]),
                retry_count=node_data.get("retry_count", 0),
                max_retries=node_data.get("max_retries", 3),
                payload=node_data.get("payload", {}),
                input_payload=node_data.get("input_payload", {}),
                output_payload=node_data.get("output_payload"),
                failure_reason=node_data.get("failure_reason"),
                assigned_agent_instance_id=node_data.get("assigned_agent_instance_id"),
                artifacts=node_data.get("artifacts", []),
                result_ref=node_data.get("result_ref"),
                metadata=node_data.get("metadata", {}),
                created_at=datetime.fromisoformat(node_data["created_at"]),
                started_at=datetime.fromisoformat(node_data["started_at"]) if node_data.get("started_at") else None,
                completed_at=datetime.fromisoformat(node_data["completed_at"]) if node_data.get("completed_at") else None,
                updated_at=datetime.fromisoformat(node_data["updated_at"]) if node_data.get("updated_at") else None,
            )
            nodes[nid] = node

        graph = cls(
            nodes=nodes,
            entry_points=data.get("entry_points", []),
            metadata=data.get("metadata", {}),
        )

        # Rebuild dependency references
        for node_id, node in graph.nodes.items():
            node._dependencies_resolved = [
                graph.nodes[dep_id] for dep_id in node.dependencies if dep_id in graph.nodes
            ]

        return graph
