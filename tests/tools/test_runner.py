"""Tests for ToolRunner — pipeline ordering, guard integration, audit completeness."""

import pytest
from redpilot_core.guards.approval_gate import ApprovalGate
from redpilot_core.guards.scope_guard import ScopeGuard
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest
from redpilot_core.models.tool_result import ToolResultStatus
from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.audit import InMemoryAuditLog
from redpilot_tools.runner import ToolInvocationRequest, ToolRunner
from redpilot_tools.sandbox import (
    SandboxContext,
    SandboxExecutionResult,
    SandboxFactory,
)


class _EchoAdapter(ToolAdapter):
    """Adapter that echoes args as command — useful for testing the pipeline."""

    manifest = ToolManifest(
        name="echo_tool",
        binary="echo",
        sandbox_profile=SandboxProfile.CODE_ANALYSIS,
        input_schema={
            "message": {"type": "string", "required": True},
        },
    )

    def build_command(self, args, scratch_dir):
        return ["echo", args.get("message", "")]

    def parse_output(self, stdout, stderr, exit_code, scratch_dir):
        return {"echoed": stdout.strip()}


class _SlowAdapter(ToolAdapter):
    """Adapter that simulates a hung tool — for timeout testing."""

    manifest = ToolManifest(
        name="slow_tool",
        binary="sleep",
        sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    )

    def build_command(self, args, scratch_dir):
        return ["sleep", "3600"]

    def parse_output(self, stdout, stderr, exit_code, scratch_dir):
        return {}


class _MockSandboxFactory(SandboxFactory):
    """Sandbox factory that returns canned execution results."""

    def __init__(self) -> None:
        self.build_calls: list[tuple[SandboxProfile, str]] = []
        self.execute_calls: list[tuple[list[str], SandboxContext]] = []
        self.next_result = SandboxExecutionResult(
            stdout="mock output",
            stderr="",
            exit_code=0,
            execution_time_ms=10,
            detected_version="1.0.0",
        )

    def build(self, profile, target):
        self.build_calls.append((profile, target))
        return SandboxContext(
            container_id="mock-001",
            scratch_dir="/tmp/mock-scratch",
        )

    async def execute(self, argv, context):
        self.execute_calls.append((argv, context))
        return self.next_result


class TestToolRunner:
    """ToolRunner pipeline tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        scope = Scope(name="test", allowed_targets=["10.0.0.0/24"])
        self.scope_guard = ScopeGuard(scope)
        self.approval_gate = ApprovalGate()
        self.sandbox_factory = _MockSandboxFactory()
        self.audit_log = InMemoryAuditLog()
        self.adapter = _EchoAdapter()
        self.runner = ToolRunner(
            scope_guard=self.scope_guard,
            approval_gate=self.approval_gate,
            sandbox_factory=self.sandbox_factory,
            audit_log=self.audit_log,
            registry={"echo_tool": self.adapter},
        )

    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        request = ToolInvocationRequest(
            tool_name="echo_tool",
            args={"message": "hello world"},
            target="10.0.0.50",
            requesting_agent_id="test_agent",
            task_node_id="NODE-001",
            rationale="Testing the runner",
        )
        result = await self.runner.run(request, self.scope_guard.scope)
        assert result.status == ToolResultStatus.SUCCESS
        assert result.parsed_output == {"echoed": "mock output"}
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_unregistered_tool_returns_blocked(self) -> None:
        request = ToolInvocationRequest(
            tool_name="nonexistent_tool",
            args={},
            target="10.0.0.50",
            requesting_agent_id="test_agent",
        )
        result = await self.runner.run(request, self.scope_guard.scope)
        assert result.status == ToolResultStatus.BLOCKED
        assert "unregistered" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_schema_validation_failure_blocks(self) -> None:
        """Missing required 'message' field should block before scope check."""
        request = ToolInvocationRequest(
            tool_name="echo_tool",
            args={"wrong_field": "hello"},
            target="10.0.0.50",
            requesting_agent_id="test_agent",
        )
        result = await self.runner.run(request, self.scope_guard.scope)
        assert result.status == ToolResultStatus.BLOCKED
        assert "schema" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_out_of_scope_blocked_before_approval(self) -> None:
        """Guard ordering: scope check must happen before approval gate
        — an out-of-scope request should never create an approval prompt."""
        request = ToolInvocationRequest(
            tool_name="echo_tool",
            args={"message": "hello"},
            target="192.168.1.1",  # not in scope
            requesting_agent_id="test_agent",
        )
        result = await self.runner.run(request, self.scope_guard.scope)
        assert result.status == ToolResultStatus.BLOCKED
        assert "scope" in (result.error or "").lower()
        # No approval request should have been created
        assert len(self.approval_gate.pending_requests) == 0

    @pytest.mark.asyncio
    async def test_audit_log_written_on_success(self) -> None:
        request = ToolInvocationRequest(
            tool_name="echo_tool",
            args={"message": "hello"},
            target="10.0.0.50",
            requesting_agent_id="test_agent",
        )
        await self.runner.run(request, self.scope_guard.scope)
        assert self.audit_log.total_count == 1
        entry = self.audit_log.entries[0]
        assert entry.tool_name == "echo_tool"
        assert entry.target == "10.0.0.50"
        assert entry.result_status == "success"

    @pytest.mark.asyncio
    async def test_audit_log_written_on_blocked(self) -> None:
        """Audit log must record REJECTED requests too (§6 test #7)."""
        request = ToolInvocationRequest(
            tool_name="nonexistent_tool",
            args={},
            target="10.0.0.50",
            requesting_agent_id="test_agent",
        )
        await self.runner.run(request, self.scope_guard.scope)
        assert self.audit_log.total_count == 1
        assert self.audit_log.entries[0].result_status == "blocked"

    @pytest.mark.asyncio
    async def test_audit_log_written_on_out_of_scope(self) -> None:
        request = ToolInvocationRequest(
            tool_name="echo_tool",
            args={"message": "hello"},
            target="192.168.1.1",
            requesting_agent_id="test_agent",
        )
        await self.runner.run(request, self.scope_guard.scope)
        assert self.audit_log.total_count == 1
        assert self.audit_log.entries[0].result_status == "blocked"
