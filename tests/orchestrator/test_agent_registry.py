"""Tests for AgentRegistry — manifest registration, instance spawning, lifecycle."""

import pytest

from redpilot_core.models.agent_manifest import AgentCluster, AgentManifest, PermissionLevel

from redpilot_orchestrator.agent_registry import AgentRegistry, AgentResult


class TestAgentRegistry:
    """AgentRegistry manifest and instance management."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.registry = AgentRegistry()
        self.manifest = AgentManifest(
            id="port_scan_agent",
            cluster=AgentCluster.RECON,
            responsibilities=["Port scanning"],
            tools_allowed=["nmap"],
            tool_permission_level=PermissionLevel.READ_ONLY,
        )
        self.registry.register_manifest(self.manifest)

    def test_register_and_get_manifest(self) -> None:
        assert self.registry.get_manifest("port_scan_agent") is self.manifest

    def test_get_nonexistent_manifest(self) -> None:
        assert self.registry.get_manifest("nonexistent") is None

    def test_register_manifests_bulk(self) -> None:
        m2 = AgentManifest(id="agent2", cluster=AgentCluster.RECON)
        self.registry.register_manifests({"agent2": m2})
        assert self.registry.get_manifest("agent2") is m2

    def test_spawn_instance(self) -> None:
        instance = self.registry.spawn_instance(
            self.manifest, "NODE-001", "GRAPH-001",
        )
        assert instance.id.startswith("INST-")
        assert instance.agent_manifest.id == "port_scan_agent"
        assert instance.node_id == "NODE-001"
        assert instance.graph_id == "GRAPH-001"

    def test_spawn_instance_is_tracked(self) -> None:
        instance = self.registry.spawn_instance(
            self.manifest, "NODE-001", "GRAPH-001",
        )
        retrieved = self.registry.get_instance(instance.id)
        assert retrieved is instance

    def test_remove_instance(self) -> None:
        instance = self.registry.spawn_instance(
            self.manifest, "NODE-001", "GRAPH-001",
        )
        self.registry.remove_instance(instance.id)
        assert self.registry.get_instance(instance.id) is None

    def test_count_alive(self) -> None:
        assert self.registry.count_alive() == 0
        instance = self.registry.spawn_instance(
            self.manifest, "NODE-001", "GRAPH-001",
        )
        # Instance is tracked immediately after spawn
        assert self.registry.count_alive() == 1
        self.registry.remove_instance(instance.id)
        assert self.registry.count_alive() == 0


class TestAgentResult:
    """AgentResult creation."""

    def test_success_result(self) -> None:
        result = AgentResult(
            success=True,
            payload={"ports": [22, 80]},
        )
        assert result.success
        assert result.payload["ports"] == [22, 80]

    def test_failure_result(self) -> None:
        result = AgentResult(
            success=False,
            error="Target not in scope",
        )
        assert not result.success
        assert result.error == "Target not in scope"
