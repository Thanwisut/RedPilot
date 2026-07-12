"""ToolRunner — the single entry point for the orchestrator to invoke tools.

The ToolRunner owns the execution pipeline in a fixed, non-configurable order:

  1. Look up ToolAdapter + ToolManifest by request.tool_name
  2. Validate request.args against manifest.input_schema
  3. ScopeGuard.check() — time window → target scope → permission level
  4. ApprovalGate — if the tool requires approval, block on resolution
  5. SandboxFactory.build() → SandboxContext
  6. Adapter.build_command() → argv
  7. Execute inside sandbox with resource limits + rate limiting
  8. Adapter.check_version() — flag drift but don't block
  9. Adapter.parse_output() → structured payload
  10. AuditLog.write() — always, success or failure, before returning
  11. Return ToolResult

**Critical property**: scope check happens BEFORE approval gate and
schema validation happens BEFORE scope check. See §2.1 of the spec
for rationale.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from redpilot_core.guards.approval_gate import ApprovalGate
from redpilot_core.guards.scope_guard import ScopeGuard
from redpilot_core.models.agent_manifest import PermissionLevel
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_manifest import ToolManifest
from redpilot_core.models.tool_result import ToolResult, ToolResultStatus

from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.audit import AuditLog
from redpilot_tools.manifests.schema import validate_args
from redpilot_tools.sandbox import SandboxContext, SandboxExecutionResult, SandboxFactory


@dataclass
class ToolInvocationRequest:
    """What an agent asks for when it wants a tool executed.

    Deliberately narrow — an agent cannot specify sandbox parameters,
    only the tool name, logical arguments, and justification.
    """

    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    target: str = ""
    requesting_agent_id: str = ""
    agent_permission_level: str = "read_only"
    task_node_id: str = ""
    rationale: str = ""


class ToolRunner:
    """The only thing agents/orchestrator ever call to run a tool.

    Not intended to be subclassed — all customization lives in ToolAdapter
    implementations.
    """

    def __init__(
        self,
        scope_guard: ScopeGuard,
        approval_gate: ApprovalGate,
        sandbox_factory: SandboxFactory,
        audit_log: AuditLog,
        registry: dict[str, ToolAdapter],
    ) -> None:
        self._scope_guard = scope_guard
        self._approval_gate = approval_gate
        self._sandbox_factory = sandbox_factory
        self._audit_log = audit_log
        self._registry = registry

    async def run(
        self,
        request: ToolInvocationRequest,
        scope: Scope,
    ) -> ToolResult:
        """Execute the full tool invocation pipeline.

        Args:
            request: The agent's invocation request.
            scope: The engagement scope (passed explicitly so the runner
                   can re-evaluate against the latest scope state).

        Returns:
            A ToolResult — always, even on internal errors (returned as
            ``ToolResult(status=FAILURE, error=...)`` rather than raising).
        """
        start_time = datetime.now(UTC)

        # ---------------------------------------------------------------
        # 1. Look up adapter + manifest
        # ---------------------------------------------------------------
        adapter = self._registry.get(request.tool_name)
        if adapter is None:
            return await self._finalize(
                request=request,
                scope=scope,
                result=ToolResult.blocked(
                    request.tool_name,
                    reason=f"Unregistered tool: '{request.tool_name}'",
                    target=request.target,
                    raw_args=request.args,
                ),
                raw_stdout="",
                raw_stderr="",
                start_time=start_time,
            )

        manifest: ToolManifest = adapter.manifest

        # ---------------------------------------------------------------
        # 2. Validate args against manifest.input_schema
        # ---------------------------------------------------------------
        schema_errors = validate_args(request.args, manifest.input_schema)
        if schema_errors:
            return await self._finalize(
                request=request,
                scope=scope,
                result=ToolResult.blocked(
                    request.tool_name,
                    reason=f"Schema validation failed: {'; '.join(schema_errors)}",
                    target=request.target,
                    raw_args=request.args,
                ),
                raw_stdout="",
                raw_stderr="",
                start_time=start_time,
            )

        # ---------------------------------------------------------------
        # 3. ScopeGuard check (time → target → permission)
        # ---------------------------------------------------------------
        guard_result = self._scope_guard.check(
            target=request.target,
            tool_manifest=manifest,
            agent_permission_level=request.agent_permission_level,
        )
        if not guard_result.allowed:
            return await self._finalize(
                request=request,
                scope=scope,
                result=ToolResult.blocked(
                    request.tool_name,
                    reason=guard_result.reason,
                    target=request.target,
                    raw_args=request.args,
                ),
                raw_stdout="",
                raw_stderr="",
                start_time=start_time,
            )

        # ---------------------------------------------------------------
        # 4. Approval Gate check
        # ---------------------------------------------------------------
        agent_perm = PermissionLevel(request.agent_permission_level)
        approval_required = self._approval_gate.requires_approval(
            manifest, agent_perm
        )
        if approval_required:
            approval_request = self._approval_gate.create_request(
                tool_name=request.tool_name,
                target=request.target,
                args=request.args,
                rationale=request.rationale,
                agent_id=request.requesting_agent_id,
            )
            # In v0.1, approval is synchronous — the caller (orchestrator)
            # will retry with polling. For now, if not approved immediately,
            # we block. A future version will make this async with WebSocket.
            if approval_request is None or not approval_request.is_resolved:
                return await self._finalize(
                    request=request,
                    scope=scope,
                    result=ToolResult.blocked(
                        request.tool_name,
                        reason="Approval request created — awaiting human resolution",
                        target=request.target,
                        raw_args=request.args,
                    ),
                    raw_stdout="",
                    raw_stderr="",
                    start_time=start_time,
                )

        # ---------------------------------------------------------------
        # 5. Build sandbox context
        # ---------------------------------------------------------------
        sandbox: SandboxContext = self._sandbox_factory.build(
            profile=manifest.sandbox_profile,
            target=request.target,
        )
        # Populate per-invocation capability requirements from adapter
        sandbox.granted_capabilities = adapter.required_capabilities(request.args)

        # ---------------------------------------------------------------
        # 6. Build command via adapter
        # ---------------------------------------------------------------
        argv = adapter.build_command(request.args, sandbox.scratch_dir)

        # ---------------------------------------------------------------
        # 7. Execute inside sandbox
        # ---------------------------------------------------------------
        exec_result: SandboxExecutionResult = await self._sandbox_factory.execute(
            argv=argv,
            context=sandbox,
        )

        # ---------------------------------------------------------------
        # 8. Check version drift
        # ---------------------------------------------------------------
        version_drift = False
        if exec_result.detected_version is not None:
            version_drift = not adapter.check_version(exec_result.detected_version)

        # ---------------------------------------------------------------
        # 9. Parse output
        # ---------------------------------------------------------------
        parsed: dict[str, Any] | None = None
        try:
            parsed = adapter.parse_output(
                stdout=exec_result.stdout,
                stderr=exec_result.stderr,
                exit_code=exec_result.exit_code,
                scratch_dir=sandbox.scratch_dir,
            )
        except (ValueError, ET.ParseError, KeyError, IndexError) as exc:
            # Parse failure is not a block — return PARTIAL with error info
            parsed = {"parse_error": str(exc), "raw_truncated": exec_result.stdout[:2000]}

        # Determine status based on exit code and parse result
        # Interrupted/timeout scans should be PARTIAL, not FAILURE (§3.3)
        if exec_result.exit_code == 0 and parsed and "parse_error" not in parsed:
            status = ToolResultStatus.SUCCESS
        elif exec_result.exit_code == 0 or exec_result.execution_time_ms >= sandbox.timeout_seconds * 1000:
            status = ToolResultStatus.PARTIAL
        else:
            status = ToolResultStatus.FAILURE

        result = ToolResult(
            status=status,
            tool_name=request.tool_name,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            exit_code=exec_result.exit_code,
            artifacts=exec_result.artifacts,
            parsed_output=parsed,
            execution_time_ms=exec_result.execution_time_ms,
            target=request.target,
            raw_args=request.args,
            tool_version=exec_result.detected_version,
        )

        # Tag version drift for downstream Critic Agent
        if version_drift:
            if result.parsed_output is not None:
                result.parsed_output["_version_drift"] = True
                result.parsed_output["_detected_version"] = exec_result.detected_version

        # Attach version drift note to error if present
        if version_drift and result.error is None:
            result.error = (
                f"Tool version drift detected: expected {manifest.version_pinned}, "
                f"got {exec_result.detected_version}"
            )

        # ---------------------------------------------------------------
        # 10. Audit log — always, before returning
        # ---------------------------------------------------------------
        return await self._finalize(
            request=request,
            scope=scope,
            result=result,
            raw_stdout=exec_result.stdout,
            raw_stderr=exec_result.stderr,
            start_time=start_time,
        )

    async def _finalize(
        self,
        *,
        request: ToolInvocationRequest,
        scope: Scope,
        result: ToolResult,
        raw_stdout: str,
        raw_stderr: str,
        start_time: datetime,
    ) -> ToolResult:
        """Write audit log entry and return the result.

        Called on **every** exit path from ``run()``, including blocked
        requests — the audit log must be complete for rejected requests too.
        """
        elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        # Use the larger of sandbox execution time or total elapsed
        if elapsed_ms > result.execution_time_ms:
            result.execution_time_ms = elapsed_ms

        await self._audit_log.write(
            tool_name=request.tool_name,
            target=request.target,
            args=request.args,
            requesting_agent=request.requesting_agent_id,
            task_node=request.task_node_id,
            rationale=request.rationale,
            scope=scope,
            result=result,
            stdout=raw_stdout,
            stderr=raw_stderr,
        )

        return result
