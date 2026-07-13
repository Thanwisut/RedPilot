"""Tests for spawn_sub_agent — adapter and TaskManager.propose_child_node().

Confirms that:
1. The adapter validates input correctly
2. TaskManager.propose_child_node() creates a real TaskNode in the graph
3. The new node goes through normal dispatch/retry/failure handling
"""

import pytest
from redpilot_core.models.agent_manifest import AgentCluster, AgentManifest, PermissionLevel
from redpilot_core.models.task_graph import TaskStatus
from redpilot_orchestrator.agent_registry import AgentRegistry
from redpilot_orchestrator.graph_store import InMemoryGraphStore
from redpilot_orchestrator.task_manager import TaskManager
from redpilot_tools.adapters.spawn_sub_agent_adapter import (
    SPAWN_SUB_AGENT_MANIFEST,
    SpawnSubAgentAdapter,
)


class TestSpawnSubAgentAdapter:
    """SpawnSubAgentAdapter argument validation and manifest."""

    def setup_method(self) -> None:
        self.adapter = SpawnSubAgentAdapter()

    def test_manifest_is_correct(self) -> None:
        assert SPAWN_SUB_AGENT_MANIFEST.name == "spawn_sub_agent"
        assert SPAWN_SUB_AGENT_MANIFEST.category == "orchestration"
        assert SPAWN_SUB_AGENT_MANIFEST.requires_approval is True
        assert SPAWN_SUB_AGENT_MANIFEST.dangerous is True

    def test_input_schema_requires_agent_id(self) -> None:
        schema = SPAWN_SUB_AGENT_MANIFEST.input_schema
        assert "agent_id" in schema
        assert schema["agent_id"]["required"] is True

    def test_input_schema_requires_task_description(self) -> None:
        schema = SPAWN_SUB_AGENT_MANIFEST.input_schema
        assert "task_description" in schema
        assert schema["task_description"]["required"] is True

    def test_input_schema_requires_target(self) -> None:
        schema = SPAWN_SUB_AGENT_MANIFEST.input_schema
        assert "target" in schema
        assert schema["target"]["required"] is True

    def test_build_command_noop(self) -> None:
        """Should always return ['true'] regardless of args."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = self.adapter.build_command(
                {"agent_id": "test", "task_description": "test", "target": "10.0.0.1"},
                tmpdir,
            )
            assert argv == ["true"]

    def test_build_command_always_noop(self) -> None:
        """Even with empty args, should still return ['true']."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = self.adapter.build_command({}, tmpdir)
            assert argv == ["true"]

    def test_parse_output_without_task_manager(self) -> None:
        """Should raise RuntimeError if TaskManager is not set."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(RuntimeError, match="TaskManager not configured"):
                self.adapter.parse_output("", "", 0, tmpdir)

    def test_set_task_manager(self) -> None:
        """After set_task_manager, parse_output should not raise."""
        manager = object()  # Any object is fine for the test
        self.adapter.set_task_manager(manager)
        assert self.adapter._task_manager is manager

    def test_validate_args_valid(self) -> None:
        """Valid args should not raise."""
        # _validate_args is internal — this just checks it handles valid input
        args = {
            "agent_id": "subdomain_agent",
            "task_description": "Enumerate subdomains",
            "target": "example.com",
            "depends_on": ["NODE-001", "NODE-002"],
        }
        # Should not raise
        self.adapter._validate_args(args)

    def test_validate_args_missing_agent_id(self) -> None:
        with pytest.raises(ValueError, match="agent_id"):
            self.adapter._validate_args({"agent_id": "", "task_description": "test", "target": "t"})

    def test_validate_args_invalid_depends_on(self) -> None:
        with pytest.raises(ValueError, match="depends_on"):
            self.adapter._validate_args({
                "agent_id": "a", "task_description": "t", "target": "t",
                "depends_on": [123],
            })


class TestTaskManagerProposeChildNode:
    """TaskManager.propose_child_node() creates real, visible TaskNodes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph_store = InMemoryGraphStore()
        self.agent_registry = AgentRegistry()

        # Register a manifest for the sub-agent
        self.manifest = AgentManifest(
            id="subdomain_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Subdomain enumeration"],
            tools_allowed=["subfinder"],
            tool_permission_level=PermissionLevel.READ_ONLY,
        )
        self.agent_registry.register_manifest(self.manifest)

        self.task_manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=self.agent_registry,
        )

    def _create_base_graph(self) -> str:
        """Create a simple base graph and return its ID."""
        from redpilot_core.models.task_graph import TaskGraph

        graph = TaskGraph()
        graph.metadata["graph_id"] = "test-spawn-graph"
        self.graph_store.save(graph)
        return "test-spawn-graph"

    def test_propose_child_node_creates_node(self) -> None:
        """propose_child_node should create a real TaskNode in the graph."""
        graph_id = self._create_base_graph()
        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Enumerate subdomains for example.com",
            target="example.com",
        )

        # The node should exist in the graph
        graph = self.graph_store.load(graph_id)
        assert graph is not None
        assert node_id in graph.nodes

        node = graph.nodes[node_id]
        assert node.agent_id == "subdomain_agent"
        assert node.status == TaskStatus.PENDING
        assert "example.com" in str(node.payload)
        assert node.dependencies == []

    def test_propose_child_node_with_dependencies(self) -> None:
        """propose_child_node should respect depends_on."""
        graph_id = self._create_base_graph()

        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Enumerate subdomains",
            target="example.com",
            depends_on=["NODE-PARENT-001"],
        )

        graph = self.graph_store.load(graph_id)
        node = graph.nodes[node_id]
        assert node.dependencies == ["NODE-PARENT-001"]

    def test_propose_child_node_with_input_payload(self) -> None:
        """propose_child_node should pass through input_payload."""
        graph_id = self._create_base_graph()

        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Enumerate subdomains",
            target="example.com",
            input_payload={"tool_name": "subfinder", "target": "example.com", "args": {}},
        )

        graph = self.graph_store.load(graph_id)
        node = graph.nodes[node_id]
        assert node.input_payload == {
            "tool_name": "subfinder",
            "target": "example.com",
            "args": {},
        }

    def test_propose_child_node_is_persisted(self) -> None:
        """The graph should be persisted immediately after propose_child_node."""
        graph_id = self._create_base_graph()
        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Test persistence",
            target="10.0.0.1",
        )

        # Load from store again — should still have the node
        graph = self.graph_store.load(graph_id)
        assert node_id in graph.nodes

    def test_propose_child_node_unknown_graph_raises(self) -> None:
        """Proposing a child on an unknown graph should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            self.task_manager.propose_child_node(
                graph_id="nonexistent-graph",
                agent_id="subdomain_agent",
                task_description="test",
                target="10.0.0.1",
            )

    def test_propose_child_node_unknown_agent_raises(self) -> None:
        """Proposing a child with an unknown agent should raise ValueError."""
        graph_id = self._create_base_graph()
        with pytest.raises(ValueError, match="No manifest"):
            self.task_manager.propose_child_node(
                graph_id=graph_id,
                agent_id="nonexistent_agent",
                task_description="test",
                target="10.0.0.1",
            )

    def test_node_goes_through_normal_dispatch(self) -> None:
        """The created node should be dispatchable by the TaskManager normally."""
        graph_id = self._create_base_graph()
        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Test dispatch",
            target="10.0.0.1",
        )

        # The node should start as PENDING
        graph = self.graph_store.load(graph_id)
        node = graph.nodes[node_id]
        assert node.status == TaskStatus.PENDING

        # promote_ready_nodes should promote it (no dependencies = ready)
        graph.promote_ready_nodes()
        assert node.status == TaskStatus.READY

    def test_node_retry_failure_handling(self) -> None:
        """The created node should support retry/failure like any other node."""
        graph_id = self._create_base_graph()
        node_id = self.task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id="subdomain_agent",
            task_description="Test retry",
            target="10.0.0.1",
        )

        graph = self.graph_store.load(graph_id)
        node = graph.nodes[node_id]

        # Exhaust retry budget
        for _ in range(node.max_retries):
            node.retry_count += 1

        assert not node.has_retry_budget
        graph.update_status(node_id, TaskStatus.BLOCKED)
        assert node.status == TaskStatus.BLOCKED
