"""Loader for tool manifest files.

Scans manifest directories at startup and produces ``ToolManifest``
instances that feed the ToolRunner's adapter registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redpilot_core.models.tool_manifest import ToolManifest

from redpilot_tools.manifests.schema import MANIFEST_SCHEMA, validate_args


class ManifestLoader:
    """Loads and validates tool manifests from YAML/JSON files.

    Scans a directory for ``*.yaml``, ``*.yml``, and ``*.json`` files,
    parses them, validates them against the manifest schema, and returns
    ``ToolManifest`` objects.
    """

    def __init__(self, manifests_dir: str | Path) -> None:
        self._manifests_dir = Path(manifests_dir)

    def load_all(self) -> dict[str, ToolManifest]:
        """Load all tool manifests from the configured directory.

        Returns:
            A dict mapping ``tool_name → ToolManifest``.
        """
        manifests: dict[str, ToolManifest] = {}

        if not self._manifests_dir.exists():
            return manifests

        for file_path in sorted(self._manifests_dir.iterdir()):
            if file_path.suffix not in (".yaml", ".yml", ".json"):
                continue
            if not file_path.is_file():
                continue

            try:
                manifest = self._load_file(file_path)
                if manifest is not None:
                    manifests[manifest.name] = manifest
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                msg = f"Failed to load manifest '{file_path.name}': {exc}"
                raise RuntimeError(msg) from exc

        return manifests

    def _load_file(self, file_path: Path) -> ToolManifest | None:
        """Load and validate a single manifest file."""
        raw: dict[str, Any]

        if file_path.suffix == ".json":
            with open(file_path) as f:
                raw = json.load(f)
        else:
            # YAML support — requires PyYAML. Fall back to JSON for v0.1
            # if YAML parsing fails.
            raw = self._load_yaml(file_path) or {}

        if not raw:
            return None

        # Validate against the manifest schema
        errors = validate_args(raw, MANIFEST_SCHEMA)
        if errors:
            msg = f"Manifest '{file_path.name}' has schema errors: {'; '.join(errors)}"
            raise ValueError(msg)

        return ToolManifest.from_manifest_entry(raw)

    @staticmethod
    def _load_yaml(file_path: Path) -> dict[str, Any] | None:
        """Attempt to load a YAML file. Returns None if PyYAML is not available."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return None

        with open(file_path) as f:
            result: dict[str, Any] | None = yaml.safe_load(f)
            return result


def load_builtin_manifests() -> dict[str, ToolManifest]:
    """Load manifests bundled with the package from ``manifests/`` directory.

    Scans relative to the ``redpilot_tools/manifests/`` package directory.
    """
    pkg_dir = Path(__file__).resolve().parent.parent / "manifests"
    loader = ManifestLoader(pkg_dir)
    return loader.load_all()
