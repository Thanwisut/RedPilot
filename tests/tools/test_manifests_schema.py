"""Tests for manifest input schema validation."""

from redpilot_tools.manifests.schema import MANIFEST_SCHEMA, validate_args


class TestValidateArgs:
    """Input schema validation for tool arguments."""

    def test_empty_schema_passes(self) -> None:
        errors = validate_args({"target": "10.0.0.1"}, {})
        assert errors == []

    def test_required_field_present(self) -> None:
        schema = {"target": {"type": "string", "required": True}}
        errors = validate_args({"target": "10.0.0.1"}, schema)
        assert errors == []

    def test_required_field_missing(self) -> None:
        schema = {"target": {"type": "string", "required": True}}
        errors = validate_args({}, schema)
        assert len(errors) == 1
        assert "Missing required" in errors[0]

    def test_required_field_none(self) -> None:
        schema = {"target": {"type": "string", "required": True}}
        errors = validate_args({"target": None}, schema)
        assert len(errors) == 1

    def test_type_mismatch(self) -> None:
        schema = {"count": {"type": "int", "required": True}}
        errors = validate_args({"count": "not_a_number"}, schema)
        assert len(errors) == 1
        assert "expected type 'int'" in errors[0]

    def test_enum_valid_value(self) -> None:
        schema = {"scan_type": {"type": "enum", "values": ["syn", "connect", "udp"]}}
        errors = validate_args({"scan_type": "syn"}, schema)
        assert errors == []

    def test_enum_invalid_value(self) -> None:
        schema = {"scan_type": {"type": "enum", "values": ["syn", "connect", "udp"]}}
        errors = validate_args({"scan_type": "sweep"}, schema)
        assert len(errors) == 1
        assert "not in allowed" in errors[0]

    def test_unknown_field_rejected(self) -> None:
        schema = {"target": {"type": "string"}}
        errors = validate_args({"target": "10.0.0.1", "unknown_flag": "evil"}, schema)
        assert len(errors) == 1
        assert "Unknown" in errors[0]

    def test_multiple_errors(self) -> None:
        schema = {
            "target": {"type": "string", "required": True},
            "ports": {"type": "int"},
        }
        errors = validate_args({"ports": "not_int", "unknown": True}, schema)
        assert len(errors) >= 2

    def test_bool_type(self) -> None:
        schema = {"verbose": {"type": "bool"}}
        assert validate_args({"verbose": True}, schema) == []
        assert validate_args({"verbose": "yes"}, schema) != []

    def test_float_type_accepts_int(self) -> None:
        schema = {"rate": {"type": "float"}}
        assert validate_args({"rate": 50}, schema) == []
        assert validate_args({"rate": 50.5}, schema) == []
        assert validate_args({"rate": "fast"}, schema) != []


class TestManifestSchema:
    """The manifest schema itself should be validatable."""

    def test_manifest_schema_has_required_fields(self) -> None:
        assert "name" in MANIFEST_SCHEMA
        assert MANIFEST_SCHEMA["name"]["required"] is True

    def test_manifest_schema_has_sandbox_profile_enum(self) -> None:
        assert "sandbox_profile" in MANIFEST_SCHEMA
        assert "network_scan_standard" in MANIFEST_SCHEMA["sandbox_profile"]["values"]
        assert "exploit" in MANIFEST_SCHEMA["sandbox_profile"]["values"]
