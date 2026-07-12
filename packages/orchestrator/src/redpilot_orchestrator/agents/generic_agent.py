"""Generic agent — wraps ``ToolRunner`` for executing tool invocations.

This is the default ``AgentInstance`` implementation used by the
Task Manager. It handles one consistent pattern:
  - Takes ``input_payload`` with ``target``, ``args``, ``tool_name``
  - Calls ``ToolRunner.run()``
  - Returns ``AgentResult`` via callback

Future agent types (Browser Agent, custom LLM-driven agents) will
extend ``AgentInstance`` directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redpilot_core.models.agent_manifest import AgentManifest

from redpilot_orchestrator.agent_registry import AgentInstance, AgentResult


class GenericAgent(AgentInstance):
    """Generic agent that wraps a ``ToolRunner`` call.

    The node's ``input_payload`` must contain:
        ``tool_name``: str — The registered tool name.
        ``target``: str — The target host/IP/domain.
        ``args``: dict — The tool arguments.
        ``permission_level``: str (optional, default \"read_only\").

    The ``ToolRunner`` must be set via ``set_tool_runner()`` before
    ``start()`` is called. This avoids coupling agent construction
    to the full ToolRunner dependency graph.
    """

    def __init__(
        self,
        agent_manifest: AgentManifest,
        node_id: str,
        graph_id: str,
    ) -> None:
        super().__init__(agent_manifest, node_id, graph_id)
        self._tool_runner: Any = None  # Set via set_tool_runner()
        self._completed: bool = False
        self._scope: Any = None  # Set via set_scope()

    def set_tool_runner(self, tool_runner: Any) -> None:
        """Inject the ``ToolRunner`` instance.

        Separated from ``__init__`` to avoid coupling agent construction
        to the full ToolRunner/ScopeGuard/ApprovalGate/SandboxFactory
        dependency graph at agent-registration time.
        """
        self._tool_runner = tool_runner

    def set_scope(self, scope: Any) -> None:
        """Inject the engagement ``Scope``."""
        self._scope = scope

    async def start(
        self,
        on_complete: Callable[[str, str, AgentResult], None],
        input_payload: dict[str, Any] | None = None,
    ) -> None:
        """Build a ``ToolInvocationRequest`` and call ``ToolRunner.run()``.

        Fire-and-forget from the caller's perspective — the result is
        delivered via ``on_complete``.
        """
        payload = input_payload or {}
        tool_name = payload.get("tool_name", "")
        target = payload.get("target", "")
        args = payload.get("args", {})
        permission_level = payload.get("permission_level", "read_only")

        if not tool_name or not target:
            result = AgentResult(
                success=False,
                error=f"Missing required fields: tool_name={tool_name}, target={target}",
            )
            on_complete(self.node_id, self.graph_id, result)
            return

        if self._tool_runner is None:
            result = AgentResult(
                success=False,
                error="ToolRunner not configured — call set_tool_runner() before start()",
            )
            on_complete(self.node_id, self.graph_id, result)
            return

        if self._scope is None:
            result = AgentResult(
                success=False,
                error="Scope not configured — call set_scope() before start()",
            )
            on_complete(self.node_id, self.graph_id, result)
            return

        # Run in a thread to not block the event loop for synchronous runners
        # (ToolRunner.run() is async but executes sync sandbox operations)
        try:
            from redpilot_tools.runner import ToolInvocationRequest

            request = ToolInvocationRequest(
                tool_name=tool_name,
                args=args,
                target=target,
                requesting_agent_id=self.agent_manifest.id,
                agent_permission_level=permission_level,
                task_node_id=self.node_id,
                rationale=f"Node {self.node_id} in graph {self.graph_id}",
            )

            tool_result = await self._tool_runner.run(request, self._scope)

            if tool_result.succeeded:
                result = AgentResult(
                    success=True,
                    payload={
                        "tool_name": tool_name,
                        "target": target,
                        "parsed_output": tool_result.parsed_output,
                        "stdout": tool_result.stdout[:5000],
                        "artifacts": tool_result.artifacts,
                        "execution_time_ms": tool_result.execution_time_ms,
                        "tool_version": tool_result.tool_version,
                    },
                    tool_name=tool_name,
                    execution_time_ms=tool_result.execution_time_ms,
                )
            else:
                result = AgentResult(
                    success=False,
                    error=tool_result.error or f"Tool execution failed: {tool_result.status.value}",
                    tool_name=tool_name,
                    execution_time_ms=tool_result.execution_time_ms,
                    payload={"status": tool_result.status.value},
                )
        except Exception as exc:
            result = AgentResult(
                success=False,
                error=f"Agent execution raised: {exc}",
            )

        self._completed = True
        on_complete(self.node_id, self.graph_id, result)

    async def cancel(self) -> None:
        """Mark as completed to prevent stale callbacks."""
        self._completed = True

    @property
    def is_alive(self) -> bool:
        """Whether the instance is still running."""
        return not self._completed
