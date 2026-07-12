"""Tests for TaskGraphStore implementations."""

import json
import tempfile

import pytest

from redpilot_core.models.task_graph import TaskGraph, TaskNode, TaskStatus

from redpilot_orchestrator.graph_store import (
    FileBackedGraphStore,
    InMemoryGraphStore,
)


class TestInMemoryGraphStore:
    """In-memory graph store tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.store = InMemoryGraphStore()

    def _make_graph(self) -> TaskGraph:
        graph = TaskGraph()
        graph.metadata["graph_id"] = "test-001"
        graph.add_node(TaskNode(payload={"task": "scan"}))
        return graph

    def test_save_and_load(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        loaded = self.store.load("test-001")
        assert loaded is not None
        assert len(loaded.nodes) == 1
        assert list(loaded.nodes.values())[0].payload["task"] == "scan"

    def test_load_nonexistent(self) -> None:
        loaded = self.store.load("nonexistent")
        assert loaded is None

    def test_delete(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        self.store.delete("test-001")
        assert self.store.load("test-001") is None

    def test_list_graphs(self) -> None:
        assert self.store.list_graphs() == []
        g1 = self._make_graph()
        g1.metadata["graph_id"] = "g1"
        self.store.save(g1)
        g2 = self._make_graph()
        g2.metadata["graph_id"] = "g2"
        self.store.save(g2)
        assert set(self.store.list_graphs()) == {"g1", "g2"}

    def test_save_overwrites(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        graph2 = TaskGraph()
        graph2.metadata["graph_id"] = "test-001"
        graph2.add_node(TaskNode(payload={"task": "updated"}))
        self.store.save(graph2)
        loaded = self.store.load("test-001")
        assert loaded is not None
        assert list(loaded.nodes.values())[0].payload["task"] == "updated"


class TestFileBackedGraphStore:
    """File-backed graph store tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = FileBackedGraphStore(self.tmpdir.name)
        yield
        self.tmpdir.cleanup()

    def _make_graph(self) -> TaskGraph:
        graph = TaskGraph()
        graph.metadata["graph_id"] = "test-001"
        graph.add_node(TaskNode(payload={"task": "scan"}))
        return graph

    def test_save_and_load(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        loaded = self.store.load("test-001")
        assert loaded is not None
        assert len(loaded.nodes) == 1

    def test_save_creates_file(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        import os
        assert os.path.exists(os.path.join(self.tmpdir.name, "test-001.json"))

    def test_load_nonexistent(self) -> None:
        assert self.store.load("nonexistent") is None

    def test_delete_removes_file(self) -> None:
        graph = self._make_graph()
        self.store.save(graph)
        self.store.delete("test-001")
        import os
        assert not os.path.exists(os.path.join(self.tmpdir.name, "test-001.json"))

    def test_save_roundtrip_preserves_status(self) -> None:
        graph = self._make_graph()
        node = list(graph.nodes.values())[0]
        graph.update_status(node.id, TaskStatus.COMPLETED)
        node.output_payload = {"result": "ok"}
        self.store.save(graph)

        loaded = self.store.load("test-001")
        assert loaded is not None
        loaded_node = list(loaded.nodes.values())[0]
        assert loaded_node.status == TaskStatus.COMPLETED
        assert loaded_node.output_payload == {"result": "ok"}
