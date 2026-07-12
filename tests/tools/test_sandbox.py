"""Tests for sandbox context and factory."""

import pytest
from redpilot_core.models.tool_manifest import SandboxProfile
from redpilot_tools.sandbox import (
    PROFILE_RESOURCES,
    NetworkPolicy,
    ResourceLimits,
    SandboxContext,
    SandboxExecutionResult,
    SandboxFactory,
)


class _MockFactory(SandboxFactory):
    """Minimal factory for testing the interface."""

    def __init__(self) -> None:
        self.last_build: tuple[SandboxProfile, str] | None = None
        self.last_execute: tuple[list[str], SandboxContext] | None = None

    def build(self, profile, target):
        self.last_build = (profile, target)
        return SandboxContext(
            container_id="mock-test",
            scratch_dir="/tmp/test",
            network_policy=NetworkPolicy(allowed_targets=[target]),
            resource_limits=PROFILE_RESOURCES.get(profile, ResourceLimits()),
        )

    async def execute(self, argv, context):
        self.last_execute = (argv, context)
        return SandboxExecutionResult(
            stdout="mock",
            stderr="",
            exit_code=0,
            execution_time_ms=5,
            detected_version="1.0",
        )


class TestSandboxContext:
    """SandboxContext creation."""

    def test_create_minimal(self) -> None:
        ctx = SandboxContext()
        assert ctx.container_id == ""
        assert ctx.scratch_dir == ""
        assert ctx.timeout_seconds == 600
        assert ctx.granted_capabilities == []

    def test_create_full(self) -> None:
        ctx = SandboxContext(
            container_id="abc-123",
            scratch_dir="/tmp/scan-001",
            network_policy=NetworkPolicy(allowed_targets=["10.0.0.1"]),
            resource_limits=ResourceLimits(cpu_count=2.0, memory_mb=1024, timeout_seconds=300),
            granted_capabilities=["CAP_NET_RAW"],
            timeout_seconds=300,
        )
        assert ctx.container_id == "abc-123"
        assert ctx.scratch_dir == "/tmp/scan-001"
        assert ctx.network_policy.allowed_targets == ["10.0.0.1"]
        assert ctx.resource_limits.cpu_count == 2.0
        assert ctx.granted_capabilities == ["CAP_NET_RAW"]


class TestNetworkPolicy:
    """Network policy creation."""

    def test_create(self) -> None:
        policy = NetworkPolicy(allowed_targets=["10.0.0.1"])
        assert policy.allowed_targets == ["10.0.0.1"]
        assert policy.dns_resolver == "none"


class TestResourceLimits:
    """Resource limits creation and defaults."""

    def test_defaults(self) -> None:
        limits = ResourceLimits()
        assert limits.cpu_count == 1.0
        assert limits.memory_mb == 512
        assert limits.timeout_seconds == 600


class TestProfileResources:
    """Profile resource assignments."""

    def test_all_profiles_have_resources(self) -> None:
        for profile in SandboxProfile:
            assert profile in PROFILE_RESOURCES
            limits = PROFILE_RESOURCES[profile]
            assert limits.cpu_count > 0
            assert limits.memory_mb > 0
            assert limits.timeout_seconds > 0

    def test_network_scan_profile(self) -> None:
        limits = PROFILE_RESOURCES[SandboxProfile.NETWORK_SCAN_STANDARD]
        assert limits.cpu_count == 1.0
        assert limits.memory_mb == 512

    def test_exploit_profile(self) -> None:
        limits = PROFILE_RESOURCES[SandboxProfile.EXPLOIT]
        assert limits.cpu_count == 2.0
        assert limits.memory_mb == 2048
        assert limits.timeout_seconds == 1200


class TestMockFactory:
    """SandboxFactory interface contract."""

    @pytest.mark.asyncio
    async def test_build_returns_context(self) -> None:
        factory = _MockFactory()
        ctx = factory.build(SandboxProfile.NETWORK_SCAN_STANDARD, "10.0.0.1")
        assert isinstance(ctx, SandboxContext)
        assert ctx.scratch_dir == "/tmp/test"
        assert factory.last_build is not None
        assert factory.last_build[0] == SandboxProfile.NETWORK_SCAN_STANDARD

    @pytest.mark.asyncio
    async def test_execute_returns_result(self) -> None:
        factory = _MockFactory()
        ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "10.0.0.1")
        result = await factory.execute(["echo", "test"], ctx)
        assert isinstance(result, SandboxExecutionResult)
        assert result.stdout == "mock"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_records_call(self) -> None:
        factory = _MockFactory()
        ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "10.0.0.1")
        argv = ["test_binary", "--flag"]
        await factory.execute(argv, ctx)
        assert factory.last_execute is not None
        assert factory.last_execute[0] == argv
        assert factory.last_execute[1].container_id == ctx.container_id
