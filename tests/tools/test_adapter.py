"""Tests for ToolAdapter abstract base class."""

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest
from redpilot_tools.adapter import ToolAdapter


class _ConcreteAdapter(ToolAdapter):
    """Minimal concrete adapter for testing the ABC."""

    manifest = ToolManifest(
        name="test_tool",
        binary="test_binary",
        version_pinned="1.0.0",
        sandbox_profile=SandboxProfile.CODE_ANALYSIS,
    )

    def build_command(self, args, scratch_dir):
        return ["test_binary", "--output", scratch_dir]

    def parse_output(self, stdout, stderr, exit_code, scratch_dir):
        return {"parsed": True}


class TestToolAdapter:
    """ToolAdapter ABC contract tests."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ToolAdapter()  # type: ignore[abstract]

    def test_manifest_is_accessible(self) -> None:
        adapter = _ConcreteAdapter()
        assert adapter.manifest.name == "test_tool"
        assert adapter.manifest.binary == "test_binary"

    def test_build_command_returns_list(self) -> None:
        adapter = _ConcreteAdapter()
        argv = adapter.build_command({}, "/tmp/scratch")
        assert isinstance(argv, list)
        assert all(isinstance(arg, str) for arg in argv)

    def test_parse_output_returns_dict(self) -> None:
        adapter = _ConcreteAdapter()
        parsed = adapter.parse_output("stdout", "stderr", 0, "/tmp/scratch")
        assert isinstance(parsed, dict)
        assert parsed["parsed"] is True

    def test_check_version_no_pin(self) -> None:
        adapter = _ConcreteAdapter()
        adapter.manifest.version_pinned = None
        assert adapter.check_version("anything")

    def test_check_version_matches(self) -> None:
        adapter = _ConcreteAdapter()
        adapter.manifest.version_pinned = "1.0.0"
        assert adapter.check_version("1.0.0")
        assert not adapter.check_version("2.0.0")

    def test_effective_permission_level(self) -> None:
        adapter = _ConcreteAdapter()
        adapter.manifest.dangerous = False
        adapter.manifest.requires_approval = False
        assert adapter.manifest.effective_permission_level == "read_only"

        adapter.manifest.requires_approval = True
        assert adapter.manifest.effective_permission_level == "write"

        adapter.manifest.dangerous = True
        assert adapter.manifest.effective_permission_level == "dangerous"


import pytest  # noqa: E402 — must be after class usage for fixture
