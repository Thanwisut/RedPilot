"""Tests for Subdomain Agent dispatch — verifies GenericAgent abstraction
generalizes to a tool with a different shape than Port Scan Agent.

Port Scan Agent: one input target -> one tool call -> one structured result
Subdomain Agent: one input domain -> one tool call -> MANY subdomains in result

This test proves the GenericAgent/AgentResult/TaskNode abstraction handles
the fan-out-as-payload pattern (Option A) without requiring special-casing.
"""

from __future__ import annotations

import asyncio

import pytest

from redpilot_core.models.agent_manifest import AgentCluster, AgentManifest, PermissionLevel
from redpilot_core.models.task_graph import TaskGraph, TaskNode, TaskStatus

from redpilot_orchestrator.agent_registry import AgentRegistry, AgentResult
from redpilot_orchestrator.graph_store import InMemoryGraphStore
from redpilot_orchestrator.task_manager import TaskManager


class _MockAgentInstance:
    """A controllable mock agent instance — matches existing test pattern."""

    def __init__(self, instance_id: str, manifest, node_id, graph_id,
                 result: AgentResult | None = None, delay: float = 0):
        self.id = instance_id
        self.agent_manifest = manifest
        self.node_id = node_id
        self.graph_id = graph_id
        self._result = result or AgentResult(success=True, payload={"subdomains": []})
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


class _MockRegistry(AgentRegistry):
    """Agent registry that creates mock instances."""

    def __init__(self, result: AgentResult | None = None, delay: float = 0):
        super().__init__()
        self._mock_result = result
        self._mock_delay = delay
        self._instance_factory_calls = []

    def _instance_factory(self, manifest, node_id, graph_id):
        self._instance_factory_calls.append((manifest.id, node_id, graph_id))
        instance_id = f"INST-{len(self._instance_factory_calls):03d}"
        return _MockAgentInstance(
            instance_id=instance_id,
            manifest=manifest,
            node_id=node_id,
            graph_id=graph_id,
            result=self._mock_result or AgentResult(success=True, payload={}),
            delay=self._mock_delay,
        )


# Sample subdomain result payload matching SubfinderAdapter's parse_output format
_SAMPLE_SUBDOMAIN_PAYLOAD = {
    "tool_name": "subfinder",
    "target": "example.com",
    "parsed_output": {
        "subdomains": [
            {"host": "mail.example.com"},
            {"host": "www.example.com"},
            {"host": "api.example.com"},
        ],
        "count": 3,
    },
    "stdout": "mail.example.com\nwww.example.com\napi.example.com\n",
    "artifacts": [],
    "execution_time_ms": 1500,
    "tool_version": "v2.14.0",
}


class TestSubdomainAgentDispatch:
    """Tests that the dispatch loop handles subdomain agent correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph_store = InMemoryGraphStore()
        self.agent_registry = _MockRegistry()

        from redpilot_core.models.agent_manifest import FailureHandlingStrategy
        subdomain_manifest = AgentManifest(
            id="subdomain_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Enumerate subdomains for in-scope domains"],
            tools_allowed=["subfinder"],
            tool_permission_level=PermissionLevel.READ_ONLY,
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        )
        self.agent_registry.register_manifest(subdomain_manifest)

    def _make_subdomain_node_graph(self, graph_id: str = "subdomain-test") -> TaskGraph:
        """Create a one-node graph for subdomain enumeration."""
        graph = TaskGraph()
        graph.metadata["graph_id"] = graph_id
        node = graph.add_node(
            TaskNode(
                agent_id="subdomain_agent",
                payload={
                    "task": "enumerate_subdomains",
                    "domain": "example.com",
                },
                input_payload={
                    "tool_name": "subfinder",
                    "target": "example.com",
                    "args": {
                        "domain": "example.com",
                        "sources": "all",
                    },
                },
            ),
        )
        # Mark as READY since there are no dependencies
        graph.promote_ready_nodes()
        return graph

    # ------------------------------------------------------------------
    # Test 1: Single-node subdomain happy path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_single_node_reaches_completed(self) -> None:
        """Single subdomain node should reach COMPLETED with output_payload."""
        graph = self._make_subdomain_node_graph()
        self.graph_store.save(graph)

        # Use a registry that returns the mock subdomain payload
        success_registry = _MockRegistry(
            result=AgentResult(success=True, payload=_SAMPLE_SUBDOMAIN_PAYLOAD),
        )
        success_registry.register_manifest(
            AgentManifest(id="subdomain_agent", cluster=AgentCluster.RECON,
                          tool_permission_level=PermissionLevel.READ_ONLY),
        )

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=success_registry,
            poll_interval_seconds=0.1,
        )

        await manager.run_dispatch_loop("subdomain-test")

        loaded = self.graph_store.load("subdomain-test")
        assert loaded is not None
        node = list(loaded.nodes.values())[0]
        assert node.status == TaskStatus.COMPLETED, (
            f"Subdomain agent node should complete. Got: {node.status}"
        )

    # ------------------------------------------------------------------
    # Test 2: Single node contains subdomain list in output_payload
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_output_contains_subdomain_list(self) -> None:
        """The output_payload should contain the discovered subdomain list,
        demonstrating Option A fan-out (list in payload, not graph mutation)."""
        graph = self._make_subdomain_node_graph()
        self.graph_store.save(graph)

        success_registry = _MockRegistry(
            result=AgentResult(success=True, payload=_SAMPLE_SUBDOMAIN_PAYLOAD),
        )
        success_registry.register_manifest(
            AgentManifest(id="subdomain_agent", cluster=AgentCluster.RECON,
                          tool_permission_level=PermissionLevel.READ_ONLY),
        )

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=success_registry,
            poll_interval_seconds=0.1,
        )

        await manager.run_dispatch_loop("subdomain-test")

        loaded = self.graph_store.load("subdomain-test")
        assert loaded is not None
        node = list(loaded.nodes.values())[0]

        assert node.output_payload is not None
        parsed = node.output_payload.get("parsed_output", {})
        subdomains = parsed.get("subdomains", [])
        assert len(subdomains) == 3, (
            f"Should contain 3 discovered subdomains. Got: {subdomains}"
        )
        assert subdomains[0]["host"] == "mail.example.com"

        # Verify no new TaskNodes were created (Option A property)
        assert len(loaded.nodes) == 1, (
            "Option A: single node stays single node. "
            "No graph mutation should occur. "
            f"Got {len(loaded.nodes)} nodes."
        )

    # ------------------------------------------------------------------
    # Test 3: Node count stays at 1 (no fan-out in agent)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_new_nodes_created(self) -> None:
        """Verify that even with many discovered subdomains, the Task Manager
        does not create new TaskNodes. This is the core Option A property:
        fan-out is handled as payload data, not graph mutation."""
        many_payload = {
            "tool_name": "subfinder",
            "target": "example.com",
            "parsed_output": {
                "subdomains": [
                    {"host": f"sub{n:03d}.example.com"}
                    for n in range(100)
                ],
                "count": 100,
            },
            "stdout": "",
            "artifacts": [],
            "execution_time_ms": 3000,
        }

        graph = self._make_subdomain_node_graph()
        self.graph_store.save(graph)

        success_registry = _MockRegistry(
            result=AgentResult(success=True, payload=many_payload),
        )
        success_registry.register_manifest(
            AgentManifest(id="subdomain_agent", cluster=AgentCluster.RECON,
                          tool_permission_level=PermissionLevel.READ_ONLY),
        )

        manager = TaskManager(
            graph_store=self.graph_store,
            agent_registry=success_registry,
            poll_interval_seconds=0.1,
        )

        await manager.run_dispatch_loop("subdomain-test")

        loaded = self.graph_store.load("subdomain-test")
        assert loaded is not None
        # Single node only — no graph mutation
        assert len(loaded.nodes) == 1
        node = list(loaded.nodes.values())[0]
        assert node.status == TaskStatus.COMPLETED
        parsed = (node.output_payload or {}).get("parsed_output", {})
        assert parsed.get("count") == 100


# ======================================================================
# TODO (Phase 7 — Planner Integration):
# The 100 discovered subdomains in output_payload need to become
# individual TaskNodes for downstream agents (httpx probe, port scan,
# screenshot). When the Planner Agent exists (Phase 7), it should:
#   1. Consume the subdomain node's output_payload
#   2. Generate N new TaskNodes (one per subdomain)
#   3. Assign them to appropriate downstream agents
#   4. Wire dependency edges: subdomain discovery -> probe -> scan
# This is explicitly NOT the Subdomain Agent's job — the agent
# produces structured data; the Planner decides what to do with it.
# ======================================================================
