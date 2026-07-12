"""Tests for ManifestLoader — file scanning, YAML/JSON parsing, error handling."""

import json
import os
import tempfile

import pytest
from redpilot_tools.manifests.loader import ManifestLoader


class TestManifestLoader:
    """ManifestLoader file scanning and parsing."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.manifests_dir = self.tmpdir.name
        yield
        self.tmpdir.cleanup()

    def _write_manifest(self, filename: str, data: dict) -> str:
        path = os.path.join(self.manifests_dir, filename)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_loads_empty_dir(self) -> None:
        loader = ManifestLoader(self.manifests_dir)
        manifests = loader.load_all()
        assert manifests == {}

    def test_loads_single_json_manifest(self) -> None:
        self._write_manifest("nmap.json", {
            "name": "nmap",
            "category": "port_scan",
            "binary": "nmap",
            "version_pinned": ">=7.90,<8.0",
            "sandbox_profile": "network_scan_standard",
            "requires_approval": False,
            "dangerous": False,
        })
        loader = ManifestLoader(self.manifests_dir)
        manifests = loader.load_all()
        assert "nmap" in manifests
        assert manifests["nmap"].name == "nmap"
        assert manifests["nmap"].binary == "nmap"

    def test_loads_multiple_manifests(self) -> None:
        self._write_manifest("nmap.json", {
            "name": "nmap",
            "category": "port_scan",
            "binary": "nmap",
            "sandbox_profile": "network_scan_standard",
            "requires_approval": False,
            "dangerous": False,
        })
        self._write_manifest("sqlmap.json", {
            "name": "sqlmap",
            "category": "exploitation",
            "binary": "sqlmap",
            "sandbox_profile": "web_scan",
            "requires_approval": True,
            "dangerous": False,
        })
        loader = ManifestLoader(self.manifests_dir)
        manifests = loader.load_all()
        assert len(manifests) == 2
        assert "nmap" in manifests
        assert "sqlmap" in manifests
        assert manifests["sqlmap"].requires_approval is True

    def test_skips_non_manifest_files(self) -> None:
        self._write_manifest("nmap.json", {
            "name": "nmap",
            "binary": "nmap",
            "sandbox_profile": "network_scan_standard",
        })
        # Write a non-manifest file
        with open(os.path.join(self.manifests_dir, "README.txt"), "w") as f:
            f.write("Not a manifest")
        loader = ManifestLoader(self.manifests_dir)
        manifests = loader.load_all()
        assert len(manifests) == 1

    def test_rejects_missing_required_field(self) -> None:
        self._write_manifest("bad.json", {
            "category": "port_scan",
            # missing 'name' (required)
        })
        loader = ManifestLoader(self.manifests_dir)
        with pytest.raises((ValueError, RuntimeError)):
            loader.load_all()

    def test_rejects_invalid_json(self) -> None:
        path = os.path.join(self.manifests_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not valid json")
        loader = ManifestLoader(self.manifests_dir)
        with pytest.raises(RuntimeError):
            loader.load_all()

    def test_nonexistent_dir_returns_empty(self) -> None:
        loader = ManifestLoader("/nonexistent/path")
        manifests = loader.load_all()
        assert manifests == {}
