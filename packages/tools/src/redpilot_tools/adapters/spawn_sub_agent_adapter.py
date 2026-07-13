"""Sub-agent spawning adapter — creates real TaskGraph nodes from LLM tool calls.

This adapter bridges the LLM tool-calling layer to the orchestrator's
Task Graph. When the LLM calls ``spawn_sub_agent``, the adapter:

1. Runs a no-op inside the sandbox (the actual graph mutation happens
   outside the sandbox in ``parse_output``)
2. In ``parse_output``, calls ``TaskManager.propose_child_node()``
   which creates a real ``TaskNode`` in the graph
3. Returns the new node's ID so the LLM can track it

**Critical properties:**
- The TaskNode goes through normal dispatch/retry/failure machinery
- It is visible in the audit log and TUI
- No out-of-band agent instances are created
"""

from __future__ import annotations

import json
import os
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter

SPAWN_SUB_AGENT_MANIFEST = ToolManifest(
    name="spawn_sub_agent",
    category="orchestration",
    binary="true",
    version_pinned=None,
    input_schema={
        "agent_id": {
            "type": "string",
            "required": True,
        },
        "task_description": {
            "type": "string",
            "required": True,
        },
        "target": {
            "type": "string",
            "required": True,
        },
        "depends_on": {
            "type": "list",
            "required": False,
        },
        "input_payload": {
            "type": "dict",
            "required": False,
        },
    },
    output_parser="task_node_parser",
    sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    requires_approval=True,
    dangerous=True,
    rate_limit=None,
    description=(
        "Create a new sub-agent in the engagement task graph. "
        "The new node is subject to normal dispatch, retry, and failure "
        "handling by the Task Manager. Returns the new node's ID."
    ),
)


class SpawnSubAgentAdapter(ToolAdapter):
    """Adapter for creating sub-agent task nodes from LLM tool calls.

    The adapter runs a no-op binary inside the sandbox and performs the
    actual graph mutation in ``parse_output``, where it has access to
    the ``TaskManager`` via the runner's callback mechanism.

    Note: The ``task_manager`` must be injected via ``set_task_manager()``
    before the adapter is used, or set on the runner registry entry.
    """

    def __init__(self, task_manager: Any | None = None) -> None:
        self._task_manager = task_manager

    manifest = SPAWN_SUB_AGENT_MANIFEST

    def set_task_manager(self, task_manager: Any) -> None:
        """Inject the ``TaskManager`` instance.

        Must be called before the adapter is used. The TaskManager
        provides ``propose_child_node()`` which creates the actual
        TaskNode in the graph.
        """
        self._task_manager = task_manager

    _ARGS_FILENAME = "_spawn_sub_agent_args.json"

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Save the spawn args to the scratch directory, then run a no-op.

        The args are persisted to a JSON file in the scratch directory so
        that ``parse_output()`` can read them back and call
        ``TaskManager.propose_child_node()``. This is necessary because
        the ToolRunner pipeline does not pass ``request.args`` to
        ``parse_output()`` directly.

        Args:
            args: The validated spawn arguments.
            scratch_dir: Host-visible scratch directory path.

        Returns:
            A simple ``true`` command that does nothing inside the sandbox.
        """
        args_path = os.path.join(scratch_dir, self._ARGS_FILENAME)
        with open(args_path, "w") as f:
            json.dump(args, f)
        return ["true"]

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Create a new TaskNode via TaskManager and return its ID.

        Reads the spawn arguments from the scratch directory (written by
        ``build_command()``), then calls ``TaskManager.propose_child_node()``
        to create a real TaskNode in the engagement graph.

        Args:
            stdout: No-op command stdout (empty).
            stderr: No-op command stderr (empty).
            exit_code: Exit code (0 for the no-op).
            scratch_dir: Path to scratch directory containing the args file.

        Returns:
            A dict with ``node_id``, ``agent_id``, and ``status`` of the
            newly created task node.

        Raises:
            RuntimeError: If ``task_manager`` is not configured.
            FileNotFoundError: If the args file was not written.
        """
        if self._task_manager is None:
            msg = (
                "TaskManager not configured — call set_task_manager() "
                "before using this adapter"
            )
            raise RuntimeError(msg)

        # Read args from scratch directory
        args_path = os.path.join(scratch_dir, self._ARGS_FILENAME)
        if not os.path.exists(args_path):
            msg = f"Spawn args file not found at {args_path}"
            raise FileNotFoundError(msg)

        with open(args_path) as f:
            args: dict[str, Any] = json.load(f)

        # Extract parameters
        agent_id = args.get("agent_id", "")
        task_description = args.get("task_description", "")
        target = args.get("target", "")
        depends_on = args.get("depends_on")
        input_payload = args.get("input_payload")
        graph_id = args.get("_graph_id", "default")

        # Validate
        self._validate_args(args)

        # Create the TaskNode
        node_id = self._task_manager.propose_child_node(
            graph_id=graph_id,
            agent_id=agent_id,
            task_description=task_description,
            target=target,
            depends_on=depends_on,
            input_payload=input_payload,
        )

        return {
            "node_id": node_id,
            "agent_id": agent_id,
            "status": "pending",
        }

    def _validate_args(self, args: dict[str, Any]) -> None:
        """Validate spawn_sub_agent arguments before processing."""
        agent_id = args.get("agent_id", "")
        if not isinstance(agent_id, str) or not agent_id.strip():
            msg = "'agent_id' must be a non-empty string"
            raise ValueError(msg)

        task_description = args.get("task_description", "")
        if not isinstance(task_description, str) or not task_description.strip():
            msg = "'task_description' must be a non-empty string"
            raise ValueError(msg)

        target = args.get("target", "")
        if not isinstance(target, str) or not target.strip():
            msg = "'target' must be a non-empty string"
            raise ValueError(msg)

        depends_on = args.get("depends_on")
        if depends_on is not None:
            if not isinstance(depends_on, list):
                msg = "'depends_on' must be a list of node IDs"
                raise ValueError(msg)
            for dep in depends_on:
                if not isinstance(dep, str):
                    msg = f"Each element of 'depends_on' must be a string, got {type(dep).__name__}"
                    raise ValueError(msg)
