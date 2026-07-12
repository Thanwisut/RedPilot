"""Tests for TaskManager — dispatch loop, crash recovery, state machine transitions."""

import asyncio

import pytest

from redpilot_core.models.agent_manifest import AgentCluster, AgentManifest, PermissionLevel
from redpilot_core.models.task_graph import TaskGraph, TaskNode, TaskStatus

from redpilot_orchestrator.agent_registry import AgentRegistry, AgentResult
from redpilot_orchestrator.graph_store import InMemoryGraphStore
from redpilot_orchestrator.task_manager import TaskManager


class _MockAgentInstance:
    """A controllable mock agent instance for testing the dispatch loop."""

    def __init__(self, instance_id: str, manifest, node_id, graph_id,
                 result: AgentResult | None = None, delay: float = 0):
        self.id = instance_id
        self.agent_manifest = manifest
        self.node_id = node_id
        self.graph_id = graph_id
        self._result = result or AgentResult(success=True, payload={"mock": True})
        self._delay = delay
        self._completed = False

    async def start(self, on_complete, input_payload=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        self._completed = True
        on_complete(self.node_id, self.graph_id, self._result)

    async def cancel(self):
        self._completed = True

    @property
    def is_alive(self):
        return not self._completed


class _MockAgentRegistry(AgentRegistry):
    """Agent registry that creates mock instances."""

    def __init__(self, result: AgentResult | None = None, delay: float = 0):
        super().__init__()
        self._mock_result = result
        self._mock_delay = delay
        self._instance_factory_calls = []

    def _instance_factory(self, manifest, node_id, graph_id):
        self._instance_factory_calls.append((manifest.id, node_id, graph_id))
        instance_id = f"INST-{len(self._instance_factory_calls):03d}"
        instance = _MockAgentInstance(
            instance_id=instance_id,
            manifest=manifest,
            node_id=node_id,
            graph_id=graph_id,
            result=self._mock_result or AgentResult(success=True, payload={}),
            delay=self._mock_delay,
        )
        return instance


class TestTaskManager:
    """TaskManager dispatch loop tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph_store = InMemoryGraphStore()
        self.agent_registry = _MockAgentRegistry()
        port_scan_manifest = AgentManifest(
            id="port_scan_agent",
            cluster=AgentCluster.RECON,
            tools_allowed=["nmap"],
            tool_permission_level=PermissionLevel.READ_ONLY,
        )
        self.agent_registry.register_manifest(port_scan_manifest)

    def _make_single_node_graph(self, graph_id: str = "test-graph") -> TaskGraph:
        """Create a one-node graph with no dependencies (immediately READY)."""
        graph = TaskGraph()
        graph.metadata["graph_id"] = graph_id
        node = graph.add_node(
            TaskNode(
                agent_id="port_scan_agent",
                payload={"task": "scan"},
                input_payload={"tool_name": "nmap", "target": "10.0.0.50", "args": {}},
            ),
        )
        # Manually promote to READY since there are no dependencies
        graph.promote_ready_nodes()
        return graph

    # ------------------------------------------------------------------
    # Test 1: Single-node happy path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_single_node_happy_path(self) -> None:
        """Single-node graph should reach COMPLETED with output_payload."""
        graph = self._make_single_node_graph()
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
            poll_interval_seconds=0.1,
        )

        await manager.run_dispatch_loop("test-graph")

        loaded = self.graph_store.load("test-graph")
        assert loaded is not None
        node = list(loaded.nodes.values())[0]
        assert node.status == TaskStatus.COMPLETED

    # ------------------------------------------------------------------
    # Test 2: Idempotent duplicate callback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_idempotent_duplicate_callback(self) -> None:
        """Calling _handle_result twice for the same node should be a no-op."""
        graph = self._make_single_node_graph()
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
        )

        # Manually dispatch a node
        node = list(graph.nodes.values())[0]
        loaded = self.graph_store.load("test-graph")
        loaded_node = list(loaded.nodes.values())[0]
        loaded_node.status = TaskStatus.DISPATCHED
        loaded_node.assigned_agent_instance_id = "INST-001"
        self.graph_store.save(loaded)

        # First callback
        result1 = AgentResult(success=True, payload={"data": "ok"})
        manager._handle_result(node.id, "test-graph", result1)

        # Second callback (duplicate)
        result2 = AgentResult(success=True, payload={"data": "duplicate"})
        manager._handle_result(node.id, "test-graph", result2)

        # Assert it's still COMPLETED with the first result's payload
        final = self.graph_store.load("test-graph")
        final_node = list(final.nodes.values())[0]
        assert final_node.status == TaskStatus.COMPLETED
        assert final_node.output_payload["data"] == "ok"

    # ------------------------------------------------------------------
    # Test 3: Retry budget exhaustion
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_retry_budget_exhaustion(self) -> None:
        """Force retry_budget failures — should reach BLOCKED, not infinite loop."""
        fail_registry = _MockAgentRegistry(
            result=AgentResult(success=False, error="Connection refused"),
        )
        fail_registry.register_manifest(
            AgentManifest(id="port_scan_agent", cluster=AgentCluster.RECON,
                          tool_permission_level=PermissionLevel.READ_ONLY),
        )

        graph = self._make_single_node_graph()
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=fail_registry,
            poll_interval_seconds=0.05,
        )

        await manager.run_dispatch_loop("test-graph")

        loaded = self.graph_store.load("test-graph")
        assert loaded is not None
        node = list(loaded.nodes.values())[0]
        assert node.status == TaskStatus.BLOCKED
        assert node.retry_count >= node.max_retries

    # ------------------------------------------------------------------
    # Test 4: Out-of-scope target → FAILED path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_failure_path_preserves_error(self) -> None:
        """A failed execution should preserve the failure_reason."""
        fail_registry = _MockAgentRegistry(
            result=AgentResult(success=False, error="Tool execution failed: blocked"),
        )
        fail_registry.register_manifest(
            AgentManifest(id="port_scan_agent", cluster=AgentCluster.RECON,
                          tool_permission_level=PermissionLevel.READ_ONLY),
        )

        graph = self._make_single_node_graph()
        node = list(graph.nodes.values())[0]
        node.max_retries = 0  # Don't retry — fail immediately
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=fail_registry,
            poll_interval_seconds=0.05,
        )

        await manager.run_dispatch_loop("test-graph")

        loaded = self.graph_store.load("test-graph")
        assert loaded is not None
        final_node = list(loaded.nodes.values())[0]
        assert final_node.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
        assert final_node.failure_reason is not None

    # ------------------------------------------------------------------
    # Test 5: Crash recovery — stale DISPATCHED → FAILED → READY
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reconcile_stale_dispatch(self) -> None:
        """A DISPATCHED node with no live instance and stale updated_at
        should be reconciled to FAILED → READY (if retry budget remains)."""
        graph = self._make_single_node_graph()
        node = list(graph.nodes.values())[0]
        node.status = TaskStatus.DISPATCHED
        node.assigned_agent_instance_id = "INST-LOST"
        # Set updated_at to way in the past to trigger stale detection
        from datetime import timedelta
        node.updated_at = node.created_at - timedelta(hours=1)
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
            stale_after_seconds=0,  # Immediate staleness
        )

        # Run one reconcile pass
        loaded = self.graph_store.load("test-graph")
        manager._reconcile_stale_dispatches(loaded)

        reconciled = self.graph_store.load("test-graph")
        assert reconciled is not None
        r_node = list(reconciled.nodes.values())[0]
        assert r_node.status == TaskStatus.READY  # Budget remains → READY
        assert "stale" in (r_node.failure_reason or "").lower()
        assert r_node.assigned_agent_instance_id is None

    # ------------------------------------------------------------------
    # Test 6: Crash recovery — alive instance NOT falsely reaped
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_reconcile_does_not_reap_alive_instance(self) -> None:
        """A DISPATCHED node with a live instance should NOT be reconciled."""
        graph = self._make_single_node_graph()
        node = list(graph.nodes.values())[0]
        node.status = TaskStatus.DISPATCHED

        # Create an instance and register it as alive
        manifest = self.agent_registry.get_manifest("port_scan_agent")
        instance = self.agent_registry.spawn_instance(manifest, node.id, "test-graph")
        node.assigned_agent_instance_id = instance.id

        from datetime import timedelta
        node.updated_at = node.created_at - timedelta(hours=1)
        self.graph_store.save(graph)

        # Add the instance to a simple alive-tracking dict
        # (_MockAgentInstance starts not alive — we need one that IS alive)
        class _AliveMockInstance(_MockAgentInstance):
            @property
            def is_alive(self):
                return True  # Override to report alive

        alive_instance = _AliveMockInstance(
            instance_id=instance.id,
            manifest=manifest,
            node_id=node.id,
            graph_id="test-graph",
        )
        # Directly inject into the registry's _instances
        self.agent_registry._instances[instance.id] = alive_instance

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
            stale_after_seconds=0,
        )

        loaded = self.graph_store.load("test-graph")
        manager._reconcile_stale_dispatches(loaded)

        # Assert node was NOT reaped — still DISPATCHED
        not_reaped = self.graph_store.load("test-graph")
        assert not_reaped is not None
        nr_node = list(not_reaped.nodes.values())[0]
        assert nr_node.status == TaskStatus.DISPATCHED

    # ------------------------------------------------------------------
    # Test 7: Persist-before-execute ordering
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dispatch_persists_before_execution(self) -> None:
        """After dispatch, the graph should be persisted before execution starts.
        This validates durability point #1 from the spec."""
        graph = self._make_single_node_graph()
        node = list(graph.nodes.values())[0]
        self.graph_store.save(graph)

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
            stale_after_seconds=0,
        )

        # Manually dispatch — don't run the loop
        loaded = self.graph_store.load("test-graph")
        l_node = list(loaded.nodes.values())[0]
        manager._dispatch(l_node, loaded)

        # Even without running execution, the graph should be persisted
        # with DISPATCHED status
        dispatched = self.graph_store.load("test-graph")
        assert dispatched is not None
        d_node = list(dispatched.nodes.values())[0]
        assert d_node.status == TaskStatus.DISPATCHED
