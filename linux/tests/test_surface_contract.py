"""Contract tests for the read-only surface module."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import socket
import sys
import urllib.request

import pytest

from kolmafa.redaction import REDACTED
from kolmafa.surface import (
    PROVIDER_KINDS,
    READINESS_VALUES,
    RESPONSE_STATUS_VALUES,
    SURFACE_API_VERSION,
    SURFACE_MODES,
    SURFACE_OPERATIONS,
    SurfaceRequest,
    SurfaceResponse,
    build_surface_request,
    get_provider_health_surface,
    get_status_surface,
    handle_surface_request,
    to_surface_dict,
)


def test_public_contract_constants_and_all() -> None:
    surface = importlib.import_module("kolmafa.surface")

    assert surface.__all__ == [
        "SURFACE_API_VERSION",
        "SURFACE_OPERATIONS",
        "SURFACE_MODES",
        "PROVIDER_KINDS",
        "RESPONSE_STATUS_VALUES",
        "READINESS_VALUES",
        "SurfaceRequest",
        "SurfaceResponse",
        "build_surface_request",
        "handle_surface_request",
        "get_status_surface",
        "get_provider_health_surface",
        "to_surface_dict",
    ]
    assert SURFACE_API_VERSION == "kolmafa.surface.v1"
    assert SURFACE_OPERATIONS == ("status", "provider_health")
    assert SURFACE_MODES == ("readonly", "dry_run")
    assert PROVIDER_KINDS == ("static", "ollama")
    assert RESPONSE_STATUS_VALUES == ("ok", "invalid_request", "unsupported_operation", "error")
    assert READINESS_VALUES == ("ready", "unknown", "not_configured")


def test_dataclass_shapes_are_frozen_and_slotted() -> None:
    assert dataclasses.is_dataclass(SurfaceRequest)
    assert dataclasses.is_dataclass(SurfaceResponse)
    assert SurfaceRequest.__dataclass_params__.frozen is True
    assert SurfaceResponse.__dataclass_params__.frozen is True
    assert hasattr(SurfaceRequest, "__slots__")
    assert hasattr(SurfaceResponse, "__slots__")
    assert [field.name for field in dataclasses.fields(SurfaceRequest)] == [
        "api_version",
        "request_id",
        "operation",
        "mode",
        "payload",
        "dry_run",
    ]
    assert [field.name for field in dataclasses.fields(SurfaceResponse)] == [
        "api_version",
        "request_id",
        "operation",
        "status",
        "data",
        "reason",
        "recovery_action",
        "redactions_applied",
        "audit_ref",
        "not_executed",
    ]


def test_function_signatures_are_exact() -> None:
    assert str(inspect.signature(build_surface_request)) == (
        "(*, request_id: str, operation: str, mode: str = 'readonly', "
        "payload: collections.abc.Mapping[str, object] | None = None, dry_run: bool = True) -> kolmafa.surface.SurfaceRequest"
    )
    assert str(inspect.signature(handle_surface_request)) == (
        "(request: kolmafa.surface.SurfaceRequest) -> kolmafa.surface.SurfaceResponse"
    )
    assert str(inspect.signature(get_status_surface)) == (
        "(*, request_id: str, mode: str = 'readonly', "
        "payload: collections.abc.Mapping[str, object] | None = None) -> kolmafa.surface.SurfaceResponse"
    )
    assert str(inspect.signature(get_provider_health_surface)) == (
        "(*, request_id: str, provider_kind: str = 'static', mode: str = 'readonly', "
        "payload: collections.abc.Mapping[str, object] | None = None) -> kolmafa.surface.SurfaceResponse"
    )
    assert str(inspect.signature(to_surface_dict)) == (
        "(value: kolmafa.surface.SurfaceRequest | kolmafa.surface.SurfaceResponse) -> dict[str, object]"
    )


def test_status_surface_data_fields_redaction_and_non_execution(tmp_path) -> None:  # noqa: ANN001
    kolmafia_home = tmp_path / "kolmafia_pwd=secret"

    response = get_status_surface(
        request_id="status-1",
        payload={
            "database_path": tmp_path / "db_token=secret.sqlite",
            "kolmafia_home": kolmafia_home,
            "cli_command": "run --pwd=secret",
            "transport": "docker-free",
            "relay_base_url": "http://localhost:60080/game.php?pwd=secret",
            "relay_pwd": "secret",
            "player_name": "player_token=secret",
            "docker_free_ready": True,
        },
    )

    assert response.status == "ok"
    assert response.not_executed is True
    assert response.redactions_applied is True
    assert list(response.data) == [
        "database_path_redacted",
        "kolmafia_home_redacted",
        "session_dir_redacted",
        "cli_command_redacted",
        "transport",
        "relay_base_url_redacted",
        "relay_pwd_configured",
        "player_name_redacted",
        "session_file_redacted",
        "docker_free_ready",
        "docker_free_problems",
        "docker_available",
        "container_running",
        "tool_calls_executed",
        "command_dispatch_enabled",
        "confirmation_consumed",
    ]
    assert response.data["tool_calls_executed"] is False
    assert response.data["command_dispatch_enabled"] is False
    assert response.data["confirmation_consumed"] is False
    assert response.data["docker_available"] is False
    assert response.data["container_running"] is None
    assert response.data["docker_free_ready"] is True
    assert response.data["docker_free_problems"] == ()
    redacted_values = [value for key, value in response.data.items() if key.endswith("_redacted")]
    assert all(isinstance(value, str) for value in redacted_values)
    assert all("secret" not in value for value in redacted_values)
    assert any(REDACTED in value for value in redacted_values)


def test_status_surface_does_not_probe_filesystem_for_metadata_booleans(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    def trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("surface status must not probe filesystem for metadata booleans")

    pathlib = importlib.import_module("pathlib")
    monkeypatch.setattr(pathlib.Path, "exists", trap)
    monkeypatch.setattr(pathlib.Path, "is_file", trap)
    monkeypatch.setattr(pathlib.Path, "is_dir", trap)
    monkeypatch.setattr(pathlib.Path, "stat", trap)

    response = get_status_surface(
        request_id="status-no-probe",
        payload={
            "kolmafia_home": tmp_path / "missing-kolmafia",
            "player_name": "missing-player",
            "docker_free_ready": True,
            "docker_free_problems": ["supplied-only"],
            "docker_available": True,
            "container_running": False,
            "relay_pwd_configured": True,
        },
    )

    assert response.status == "ok"
    assert response.data["docker_free_ready"] is True
    assert response.data["docker_free_problems"] == ("supplied-only",)
    assert response.data["docker_available"] is True
    assert response.data["container_running"] is False
    assert response.data["relay_pwd_configured"] is True


def test_status_surface_metadata_booleans_use_safe_defaults_when_absent() -> None:
    response = get_status_surface(request_id="status-defaults")

    assert response.status == "ok"
    assert response.data["docker_free_ready"] is False
    assert response.data["docker_free_problems"] == ()
    assert response.data["docker_available"] is False
    assert response.data["container_running"] is None
    assert response.data["relay_pwd_configured"] is False


def _install_no_network_or_provider_traps(monkeypatch: pytest.MonkeyPatch) -> None:
    def trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("surface contract must not construct providers or perform network I/O")

    monkeypatch.setattr(socket, "socket", trap)
    monkeypatch.setattr(urllib.request, "urlopen", trap)
    try:
        httpx = importlib.import_module("httpx")
    except ImportError:
        httpx = None
    if httpx is not None:
        monkeypatch.setattr(httpx, "AsyncClient", trap)

    llm = importlib.import_module("kolmafa.llm")
    monkeypatch.setattr(llm.OllamaProvider, "__init__", trap)
    monkeypatch.setattr(llm, "get_provider", trap)


def test_provider_health_metadata_only_and_redacted() -> None:
    response = get_provider_health_surface(
        request_id="provider-1",
        provider_kind="ollama",
        payload={"model": "llama_token=secret", "last_error": "boom pwd=secret"},
    )

    assert response.status == "ok"
    assert list(response.data) == [
        "provider_kind",
        "readiness",
        "network_checked",
        "ollama_instantiated",
        "last_error_redacted",
        "model_redacted",
        "tool_calls_executed",
        "command_dispatch_enabled",
        "confirmation_consumed",
    ]
    assert response.data["provider_kind"] == "ollama"
    assert response.data["readiness"] == "unknown"
    assert response.data["network_checked"] is False
    assert response.data["ollama_instantiated"] is False
    assert response.data["tool_calls_executed"] is False
    assert response.data["command_dispatch_enabled"] is False
    assert response.data["confirmation_consumed"] is False
    assert response.data["last_error_redacted"] == f"boom pwd={REDACTED}"
    assert response.data["model_redacted"] == REDACTED


def test_provider_health_explicit_provider_kind_overrides_payload() -> None:
    response = get_provider_health_surface(
        request_id="provider-explicit",
        provider_kind="ollama",
        payload={"provider_kind": "static"},
    )

    assert response.status == "ok"
    assert response.data["provider_kind"] == "ollama"
    assert response.data["readiness"] == "unknown"


def test_provider_health_invalid_provider_kind_is_invalid_request_without_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_no_network_or_provider_traps(monkeypatch)

    response = get_provider_health_surface(request_id="provider-bad", provider_kind="remote")

    assert response.status == "invalid_request"
    assert response.data == {}
    assert response.not_executed is True


def test_provider_health_does_not_use_network_or_provider_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_no_network_or_provider_traps(monkeypatch)

    response = get_provider_health_surface(request_id="provider-safe", provider_kind="ollama")

    assert response.status == "ok"
    assert response.data["network_checked"] is False
    assert response.data["ollama_instantiated"] is False


def test_redactions_applied_false_when_no_redacted_data_fields() -> None:
    response = handle_surface_request(build_surface_request(request_id="plain", operation="unsupported"))

    assert response.status == "unsupported_operation"
    assert response.redactions_applied is False


@pytest.mark.parametrize(
    "operation",
    [
        "search",
        "observe",
        "respond",
        "send",
        "execute",
        "sideCommand",
        "write_back",
        "confirmation_consume",
        "relay_post",
        "tool_dispatch",
    ],
)
def test_forbidden_operation_values_are_unsupported(operation: str) -> None:
    response = handle_surface_request(build_surface_request(request_id="blocked", operation=operation))

    assert response.status == "unsupported_operation"
    assert response.not_executed is True
    assert response.data == {}


def test_invalid_mode_and_api_version_fail_as_invalid_request() -> None:
    invalid_mode = handle_surface_request(build_surface_request(request_id="bad-mode", operation="status", mode="write"))
    invalid_api = handle_surface_request(
        SurfaceRequest(
            api_version="kolmafa.surface.v0",
            request_id="bad-api",
            operation="status",
            mode="readonly",
            payload={},
            dry_run=True,
        )
    )

    assert invalid_mode.status == "invalid_request"
    assert invalid_api.status == "invalid_request"
    assert invalid_mode.not_executed is True
    assert invalid_api.not_executed is True


def test_to_surface_dict_serializes_request_and_response() -> None:
    request = build_surface_request(request_id="r1", operation="status", payload={"x": "y"})
    response = handle_surface_request(request)

    assert to_surface_dict(request)["payload"] == {"x": "y"}
    assert to_surface_dict(response)["status"] == "ok"


def test_no_forbidden_public_operation_names() -> None:
    surface = importlib.import_module("kolmafa.surface")
    forbidden_names = {
        "search",
        "observe",
        "respond",
        "send",
        "execute",
        "sideCommand",
        "write_back",
        "confirmation_consume",
        "relay_post",
        "tool_dispatch",
    }

    assert forbidden_names.isdisjoint(surface.__all__)
    assert forbidden_names.isdisjoint(name for name in dir(surface) if not name.startswith("_"))


def test_no_network_or_provider_modules_loaded_by_surface() -> None:
    for module_name in ["kolmafa.surface", "kolmafa.llm", "kolmafa.live", "httpx", "urllib.request", "socket"]:
        sys.modules.pop(module_name, None)

    surface = importlib.import_module("kolmafa.surface")
    response = surface.get_provider_health_surface(request_id="no-network", provider_kind="ollama")

    assert response.data["network_checked"] is False
    assert response.data["ollama_instantiated"] is False
    assert "kolmafa.llm" not in sys.modules
    assert "kolmafa.live" not in sys.modules
    assert "httpx" not in sys.modules
    assert "urllib.request" not in sys.modules
    assert "socket" not in sys.modules
