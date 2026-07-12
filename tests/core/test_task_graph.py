"""Tests for task graph domain models — TaskGraph, TaskNode, TaskStatus."""

import pytest
from redpilot_core.models.task_graph import (
    EdgeType,
    TaskGraph,
    TaskNode,
    TaskStatus,
)


class TestTaskNode:
    """TaskNode creation and lifecycle."""

    def test_create_node(self) -> None:
        node = TaskNode()
        assert node.id.startswith("NODE-")
        assert node.status == TaskStatus.PENDING
        assert node.retry_count == 0
        assert node.max_retries == 3
        assert not node.is_terminal

    def test_terminal_states(self) -> None:
        completed = TaskNode(status=TaskStatus.COMPLETED)
        assert completed.is_terminal
        aborted = TaskNode(status=TaskStatus.ABORTED)
        assert aborted.is_terminal
        blocked = TaskNode(status=TaskStatus.BLOCKED)
        assert blocked.is_terminal
        non_terminal = TaskNode(status=TaskStatus.READY)
        assert not non_terminal.is_terminal

    def test_is_ready_true(self) -> None:
        node = TaskNode(status=TaskStatus.READY)
        assert node.is_ready

    def test_is_ready_false_for_pending(self) -> None:
        node = TaskNode(status=TaskStatus.PENDING)
        assert not node.is_ready

    def test_is_awaiting_result(self) -> None:
        dispatched = TaskNode(status=TaskStatus.DISPATCHED)
        assert dispatched.is_awaiting_result
        executing = TaskNode(status=TaskStatus.EXECUTING)
        assert executing.is_awaiting_result
        completed = TaskNode(status=TaskStatus.COMPLETED)
        assert not completed.is_awaiting_result

    def test_has_retry_budget(self) -> None:
        node = TaskNode(max_retries=3, retry_count=1)
        assert node.has_retry_budget
        node.retry_count = 3
        assert not node.has_retry_budget

    def test_create_with_payload(self) -> None:
        node = TaskNode(
            payload={"target": "10.0.0.1", "ports": [80, 443]},
            agent_id="nmap_agent",
        )
        assert node.payload["target"] == "10.0.0.1"
        assert node.agent_id == "nmap_agent"


class TestTaskGraph:
    """TaskGraph DAG operations."""

    def test_empty_graph(self) -> None:
        graph = TaskGraph()
        assert len(graph.nodes) == 0
        assert graph.get_ready_nodes() == []

    def test_add_node(self) -> None:
        graph = TaskGraph()
        node = graph.add_node(TaskNode(payload={"task": "scan"}))
        assert node.id in graph.nodes
        assert node.id in graph.entry_points  # no deps -> entry point

    def test_add_node_with_dependencies(self) -> None:
        graph = TaskGraph()
        scan = graph.add_node(TaskNode(payload={"task": "scan"}))
        exploit = graph.add_node(
            TaskNode(
                payload={"task": "exploit"},
                dependencies=[scan.id],
            ),
        )
        assert exploit.id in graph.nodes
        assert exploit.id not in graph.entry_points
        assert scan.id in graph.entry_points

    def test_promote_ready_nodes(self) -> None:
        graph = TaskGraph()
        scan = graph.add_node(TaskNode(payload={"task": "scan"}))
        exploit = graph.add_node(
            TaskNode(payload={"task": "exploit"}, dependencies=[scan.id]),
        )

        # Initially scan should be PROMOTED to READY (no deps), exploit stays PENDING
        promoted = graph.promote_ready_nodes()
        assert scan.id in promoted
        assert exploit.id not in promoted
        assert graph.nodes[scan.id].status == TaskStatus.READY
        assert graph.nodes[exploit.id].status == TaskStatus.PENDING

        # Complete scan, promote exploit
        graph.update_status(scan.id, TaskStatus.COMPLETED)
        promoted = graph.promote_ready_nodes()
        assert exploit.id in promoted
        assert graph.nodes[exploit.id].status == TaskStatus.READY

    def test_topological_sort_simple(self) -> None:
        graph = TaskGraph()
        n1 = graph.add_node(TaskNode(payload={"step": 1}))
        n2 = graph.add_node(TaskNode(payload={"step": 2}, dependencies=[n1.id]))
        n3 = graph.add_node(TaskNode(payload={"step": 3}, dependencies=[n1.id, n2.id]))

        sorted_nodes = graph.topological_sort()
        ids = [n.id for n in sorted_nodes]
        # n1 must come before both n2 and n3
        assert ids.index(n1.id) < ids.index(n2.id)
        assert ids.index(n1.id) < ids.index(n3.id)
        # n2 must come before n3
        assert ids.index(n2.id) < ids.index(n3.id)

    def test_topological_sort_complex_dag(self) -> None:
        graph = TaskGraph()
        recon = graph.add_node(TaskNode(payload={"task": "recon"}))
        scan = graph.add_node(TaskNode(payload={"task": "scan"}, dependencies=[recon.id]))
        vuln_scan = graph.add_node(TaskNode(payload={"task": "vuln_scan"}, dependencies=[scan.id]))
        exploit = graph.add_node(TaskNode(payload={"task": "exploit"}, dependencies=[vuln_scan.id]))

        sorted_nodes = graph.topological_sort()
        ids = [n.id for n in sorted_nodes]
        assert ids.index(recon.id) < ids.index(scan.id)
        assert ids.index(scan.id) < ids.index(vuln_scan.id)
        assert ids.index(vuln_scan.id) < ids.index(exploit.id)

    def test_cycle_detection(self) -> None:
        graph = TaskGraph()
        n1 = graph.add_node(TaskNode(payload={}))
        n2 = graph.add_node(TaskNode(payload={}, dependencies=[n1.id]))
        n3 = graph.add_node(TaskNode(payload={}, dependencies=[n2.id]))

        # Manually add a cycle by making n1 depend on n3
        graph.nodes[n1.id].dependencies.append(n3.id)

        with pytest.raises(ValueError, match="contains a cycle"):
            graph.topological_sort()

    def test_update_status_records_timestamps(self) -> None:
        graph = TaskGraph()
        node = graph.add_node(TaskNode())

        assert node.started_at is None
        graph.update_status(node.id, TaskStatus.DISPATCHED)
        assert node.started_at is not None

        assert node.completed_at is None
        graph.update_status(node.id, TaskStatus.COMPLETED)
        assert node.completed_at is not None

    def test_increment_retry(self) -> None:
        graph = TaskGraph()
        node = graph.add_node(TaskNode(max_retries=2))

        assert node.retry_count == 0
        graph.increment_retry(node.id)
        assert node.retry_count == 1
        assert node.status == TaskStatus.READY  # retry eligible

        graph.increment_retry(node.id)
        assert node.retry_count == 2
        assert node.status == TaskStatus.BLOCKED  # exhausted retry budget

    def test_serialize_and_deserialize(self) -> None:
        graph = TaskGraph()
        n1 = graph.add_node(TaskNode(payload={"task": "scan", "ports": [80]}))
        n2 = graph.add_node(
            TaskNode(payload={"task": "exploit"}, dependencies=[n1.id]),
        )
        graph.metadata["engagement"] = "test-001"
        graph.metadata["target"] = "10.0.0.1"

        # Add edge type
        n2.edge_types[n1.id] = EdgeType.DEPENDS_ON

        graph.update_status(n1.id, TaskStatus.COMPLETED)

        serialized = graph.to_dict()
        assert len(serialized["nodes"]) == 2
        assert serialized["metadata"]["engagement"] == "test-001"
        assert serialized["nodes"][n1.id]["status"] == "completed"

        # Deserialize
        restored = TaskGraph.from_dict(serialized)
        assert len(restored.nodes) == 2
        assert restored.nodes[n1.id].status == TaskStatus.COMPLETED
        assert restored.nodes[n2.id].status == TaskStatus.PENDING
        assert restored.metadata["engagement"] == "test-001"
        assert n1.id in restored.nodes[n2.id].edge_types
        assert restored.nodes[n2.id].edge_types[n1.id] == EdgeType.DEPENDS_ON
