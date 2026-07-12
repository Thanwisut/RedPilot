"""TaskGraph persistence store.

The Task Graph is the single source of truth for engagement progress.
It is persisted after every state transition so that a crashed session
can resume gracefully. Every transition in ``TaskManager`` is followed
by a synchronous persist — not batched.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from redpilot_core.models.task_graph import TaskGraph


class TaskGraphStore(ABC):
    """Abstract persistence store for TaskGraphs.

    In-memory implementation for testing; file-backed or database-backed
    implementations for production.
    """

    @abstractmethod
    def save(self, graph: TaskGraph) -> None:
        """Persist a graph. Overwrites any previous version with the
        same graph ID (stored in ``graph.metadata.get("graph_id")``).

        Must be synchronous and atomic at the file/db level.
        """

    @abstractmethod
    def load(self, graph_id: str) -> TaskGraph | None:
        """Load a previously persisted graph by ID.

        Returns None if no graph with that ID exists.
        """

    @abstractmethod
    def delete(self, graph_id: str) -> None:
        """Remove a persisted graph (for cleanup after engagement ends)."""

    @abstractmethod
    def list_graphs(self) -> list[str]:
        """Return all graph IDs currently in the store."""


class InMemoryGraphStore(TaskGraphStore):
    """In-memory graph store for testing and development.

    Not suitable for production — entries are lost on process restart.
    """

    def __init__(self) -> None:
        self._graphs: dict[str, TaskGraph] = {}

    def save(self, graph: TaskGraph) -> None:
        graph_id = graph.metadata.get("graph_id", "default")
        # Deep-copy via serialization round-trip to ensure isolation
        serialized = json.dumps(graph.to_dict())
        restored = TaskGraph.from_dict(json.loads(serialized))
        self._graphs[graph_id] = restored

    def load(self, graph_id: str) -> TaskGraph | None:
        raw = self._graphs.get(graph_id)
        if raw is None:
            return None
        # Deep-copy on read for isolation
        serialized = json.dumps(raw.to_dict())
        return TaskGraph.from_dict(json.loads(serialized))

    def delete(self, graph_id: str) -> None:
        self._graphs.pop(graph_id, None)

    def list_graphs(self) -> list[str]:
        return list(self._graphs.keys())


class FileBackedGraphStore(TaskGraphStore):
    """File-backed graph store for crash recovery.

    Each graph is stored as a JSON file in the configured directory.
    This is suitable for single-user/local mode where the process
    may crash but the filesystem is durable.
    """

    def __init__(self, storage_dir: str | Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, graph: TaskGraph) -> None:
        graph_id = graph.metadata.get("graph_id", "default")
        path = self._storage_dir / f"{graph_id}.json"
        with open(path, "w") as f:
            json.dump(graph.to_dict(), f, indent=2, default=str)

    def load(self, graph_id: str) -> TaskGraph | None:
        path = self._storage_dir / f"{graph_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            data: dict[str, Any] = json.load(f)
        return TaskGraph.from_dict(data)

    def delete(self, graph_id: str) -> None:
        path = self._storage_dir / f"{graph_id}.json"
        if path.exists():
            path.unlink()

    def list_graphs(self) -> list[str]:
        return [
            p.stem for p in self._storage_dir.glob("*.json")
        ]
