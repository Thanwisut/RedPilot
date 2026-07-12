"""Input schema validation for tool manifests.

Each ``ToolManifest.input_schema`` is a dict describing the expected types
and constraints for the tool's arguments. This module validates agent-supplied
args against that schema before they reach the adapter.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Shared schema definition used to validate manifest YAML files themselves.
# ---------------------------------------------------------------------------
MANIFEST_SCHEMA: dict[str, Any] = {
    "name": {"type": "string", "required": True},
    "category": {"type": "string", "required": False},
    "binary": {"type": "string", "required": False},
    "version_pinned": {"type": "string", "required": False},
    "input_schema": {"type": "dict", "required": False},
    "output_parser": {"type": "string", "required": False},
    "sandbox_profile": {
        "type": "enum",
        "values": [
            "network_scan_standard",
            "web_scan",
            "exploit",
            "code_analysis",
            "browser",
        ],
        "required": False,
    },
    "requires_approval": {"type": "bool", "required": False},
    "dangerous": {"type": "bool", "required": False},
    "rate_limit": {"type": "dict", "required": False},
    "timeout_seconds": {"type": "int", "required": False},
    "description": {"type": "string", "required": False},
}

# ---------------------------------------------------------------------------
# Type mapping from schema type annotations to Python types.
# ---------------------------------------------------------------------------
_TYPE_MAP: dict[str, type] = {
    "string": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


def _type_matches(value: object, expected_type: str) -> bool:
    """Check if *value* matches the expected schema type."""
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "bool":
        return isinstance(value, bool)
    if expected_type == "list":
        return isinstance(value, list)
    if expected_type == "dict":
        return isinstance(value, dict)
    if expected_type == "enum":
        return True  # validated by value check below
    return False  # unknown type — reject for safety


def validate_args(
    args: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    """Validate *args* against an *input_schema*.

    The schema is a dict mapping field names to constraint dicts:
    ``{"field_name": {"type": "string", "required": True, ...}}``

    Supported constraint keys:
    - ``type``: Expected type string (string, int, float, bool, list, dict, enum).
    - ``required``: If True, the field must be present.
    - ``values``: For enum types, the allowed values.
    - ``default``: Default value if not provided.

    Args:
        args: Agent-supplied arguments to validate.
        schema: The manifest's input_schema dict.

    Returns:
        A list of error messages. Empty list means validation passed.
    """
    errors: list[str] = []

    for field_name, constraints in schema.items():
        required = constraints.get("required", False)
        expected_type = constraints.get("type", "string")
        allowed_values = constraints.get("values")

        value = args.get(field_name)

        # Check required
        if required and value is None:
            errors.append(f"Missing required field '{field_name}'")
            continue

        if value is None:
            continue

        # Check type
        if expected_type == "enum" and allowed_values is not None:
            if value not in allowed_values:
                errors.append(
                    f"Field '{field_name}': value '{value}' is not in allowed "
                    f"values: {allowed_values}"
                )
        elif not _type_matches(value, expected_type):
            errors.append(
                f"Field '{field_name}': expected type '{expected_type}', "
                f"got '{type(value).__name__}'"
            )

    # Check for unknown fields (only if schema is non-empty — otherwise accept all)
    if schema:
        known_fields = set(schema.keys())
        for arg_key in args:
            if arg_key not in known_fields:
                errors.append(f"Unknown field '{arg_key}'")

    return errors
