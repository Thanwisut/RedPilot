"""Task Manager — the core dispatch loop for the engagement task graph.

Design goals (per spec §1):
1. Task Graph state is the only source of truth — no in-memory state
   that isn't also durably reflected in the graph.
2. The Task Manager does not know about tools, sandboxes, or scope.
3. Dispatch is idempotent — re-dispatching an already-Completed or
   already-Executing node is a safe no-op.
4. One node, one agent instance, one attempt per dispatch cycle.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from redpilot_core.models.task_graph import TaskGraph, TaskNode, TaskStatus

from redpilot_orchestrator.agent_registry import AgentRegistry, AgentResult
from redpilot_orchestrator.graph_store import TaskGraphStore


class TaskManager:
    """Owns the dispatch loop for a single engagement graph.

    The manager polls graph state at a fixed interval, dispatches READY
    nodes to agents, handles results, and reconciles stale dispatches.
    """

    def __init__(
        self,
        graph_store: TaskGraphStore,
        agent_registry: AgentRegistry,
        poll_interval_seconds: float = 2.0,
        stale_after_seconds: int = 120,
    ) -> None:
        self._graph_store = graph_store
        self._agent_registry = agent_registry
        self._poll_interval = poll_interval_seconds
        self._stale_after = stale_after_seconds
        self._running = False

    async def run_dispatch_loop(self, graph_id: str) -> None:
        """Run the dispatch loop until all nodes reach terminal states.

        Each tick:
          1. Load graph from store (always re-read, never trust cache)
          2. Dispatch all READY nodes
          3. Reconcile stale DISPATCHED/EXECUTING nodes
          4. If all nodes terminal, return
          5. Sleep for poll_interval

        Args:
            graph_id: The ID of the graph to dispatch.
        """
        self._running = True

        try:
            while self._running:
                graph = self._graph_store.load(graph_id)
                if graph is None:
                    msg = f"Graph '{graph_id}' not found in store"
                    raise ValueError(msg)

                # Step 1: Promote PENDING nodes whose deps are all Completed
                graph.promote_ready_nodes()

                # Step 2: Dispatch all READY nodes
                ready_nodes = graph.get_nodes_by_status(TaskStatus.READY)
                for node in ready_nodes:
                    self._dispatch(node, graph)

                # Step 3: Reconcile stale dispatches
                self._reconcile_stale_dispatches(graph)

                # Step 4: Check for terminal state
                if graph.all_terminal():
                    return

                # Step 5: Wait for next tick
                await asyncio.sleep(self._poll_interval)

        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the dispatch loop to stop on its next tick."""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Child node proposal — called from SpawnSubAgentAdapter
    # ------------------------------------------------------------------

    def propose_child_node(
        self,
        graph_id: str,
        agent_id: str,
        task_description: str,
        target: str,
        depends_on: list[str] | None = None,
        input_payload: dict | None = None,
    ) -> str:
        """Create a new TaskNode in the specified graph and return its ID.

        This is the narrow, explicit gateway through which an LLM-driven
        ``spawn_sub_agent`` tool call creates a real, visible TaskNode
        in the engagement graph. The node goes through normal
        dispatch/retry/failure handling.

        Args:
            graph_id: The graph to add the node to.
            agent_id: The agent manifest ID for this node.
            task_description: Human-readable description.
            target: The target for this sub-agent.
            depends_on: Optional list of node IDs this node depends on.
            input_payload: Optional payload passed as input_payload.

        Returns:
            The new node's ID.

        Raises:
            ValueError: If the graph is not found or agent_id is unknown.
        """
        graph = self._graph_store.load(graph_id)
        if graph is None:
            msg = f"Graph '{graph_id}' not found in store"
            raise ValueError(msg)

        manifest = self._agent_registry.get_manifest(agent_id)
        if manifest is None:
            msg = f"No manifest for agent '{agent_id}'"
            raise ValueError(msg)

        from redpilot_core.models.task_graph import TaskNode, TaskStatus

        node = TaskNode(
            agent_id=agent_id,
            dependencies=depends_on or [],
            payload={
                "task_description": task_description,
                "target": target,
            },
            input_payload=input_payload or {
                "target": target,
                "tool_name": agent_id,
                "args": {},
            },
            status=TaskStatus.PENDING,
        )
        graph.add_node(node)
        self._graph_store.save(graph)

        return node.id

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, node: TaskNode, graph: TaskGraph) -> None:
        """Dispatch a single READY node to an agent.

        (Spec §4: dispatch() implementation)

        1. Look up agent manifest
        2. Spawn agent instance
        3. Link instance to node
        4. Set status → DISPATCHED
        5. Persist BEFORE starting execution (durability point #1)
        6. Start agent instance (fire-and-forget)
        """
        manifest = self._agent_registry.get_manifest(node.agent_id or "")
        if manifest is None:
            node.failure_reason = f"No manifest for agent '{node.agent_id}'"
            graph.update_status(node.id, TaskStatus.FAILED)
            self._graph_store.save(graph)
            return

        # Spawn instance and link to node
        instance = self._agent_registry.spawn_instance(
            manifest, node.id, graph.metadata.get("graph_id", "default"),
        )
        node.assigned_agent_instance_id = instance.id
        graph.update_status(node.id, TaskStatus.DISPATCHED)

        # Persist BEFORE starting execution (durability point #1)
        self._graph_store.save(graph)

        # Start agent instance (fire-and-forget)
        asyncio.create_task(
            instance.start(
                on_complete=lambda nid, gid, result: self._handle_result(nid, gid, result),
                input_payload=node.input_payload or node.payload,
            ),
        )

    # ------------------------------------------------------------------
    # Result handling
    # ------------------------------------------------------------------

    def _handle_result(
        self,
        node_id: str,
        graph_id: str,
        result: AgentResult,
    ) -> None:
        """Handle an agent completion callback.

        (Spec §4: _handle_result() implementation)

        1. Re-load graph from store (never trust in-memory)
        2. Check node is still awaiting result (idempotency guard)
        3. Update node state based on result
        4. Promote dependents to READY
        5. Persist (durability point #2)
        """
        graph = self._graph_store.load(graph_id)
        if graph is None:
            return

        node = graph.nodes.get(node_id)
        if node is None:
            return

        # Idempotency guard: only process if still awaiting result
        if not node.is_awaiting_result:
            return

        if result.success:
            node.output_payload = result.payload
            node.failure_reason = None
            graph.update_status(node_id, TaskStatus.COMPLETED)
        else:
            node.failure_reason = result.error
            node.retry_count += 1
            if node.has_retry_budget:
                graph.update_status(node_id, TaskStatus.FAILED)
                # Promotion to READY happens on next tick via promote_ready_nodes()
                # But since we transitioned FROM awaiting-result, we need to
                # manually re-promote the node itself to READY here
                node.status = TaskStatus.READY
                node.updated_at = datetime.now(UTC)
            else:
                graph.update_status(node_id, TaskStatus.BLOCKED)

        # Promote dependent nodes to READY
        graph.promote_ready_nodes()

        # Persist (durability point #2)
        self._graph_store.save(graph)

        # Clean up agent instance
        if node.assigned_agent_instance_id:
            self._agent_registry.remove_instance(node.assigned_agent_instance_id)

    # ------------------------------------------------------------------
    # Crash recovery — reconcile stale dispatches
    # ------------------------------------------------------------------

    def _reconcile_stale_dispatches(self, graph: TaskGraph) -> None:
        """Find DISPATCHED/EXECUTING nodes whose agent instance is gone.

        (Spec §5: reconcile_stale_dispatches())

        For each such node:
        1. Check if the instance is still alive
        2. If instance is gone (crash/restart): mark as FAILED, let retry
           budget apply
        3. If instance is alive: leave as-is
        """
        now = datetime.now(UTC)
        for node in graph.get_nodes_by_status(TaskStatus.DISPATCHED):
            self._reconcile_single_node(node, graph, now)
        for node in graph.get_nodes_by_status(TaskStatus.EXECUTING):
            self._reconcile_single_node(node, graph, now)

    def _reconcile_single_node(
        self,
        node: TaskNode,
        graph: TaskGraph,
        now: datetime,
    ) -> None:
        """Reconcile a single potentially-stale node."""
        # Skip nodes that haven't exceeded the stale threshold
        if node.updated_at is None:
            return
        elapsed = (now - node.updated_at).total_seconds()
        if elapsed < self._stale_after:
            return

        # Check if instance actually still exists and is alive
        if node.assigned_agent_instance_id:
            instance = self._agent_registry.get_instance(node.assigned_agent_instance_id)
            if instance is not None and instance.is_alive:
                return  # Legitimately still running — leave as-is

        # Instance is gone or unknown — treat as failed
        node.failure_reason = (
            f"Agent instance '{node.assigned_agent_instance_id}' lost "
            f"(stale for {elapsed:.0f}s, exceeded {self._stale_after}s threshold)"
        )
        node.retry_count += 1
        node.assigned_agent_instance_id = None

        if node.has_retry_budget:
            node.status = TaskStatus.READY
        else:
            node.status = TaskStatus.BLOCKED
        node.updated_at = now

        self._graph_store.save(graph)
