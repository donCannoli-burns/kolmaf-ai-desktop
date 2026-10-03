"""Import-safe read-only surface contract for Kolmafa metadata."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from kolmafa.redaction import REDACTED, redact_text

SURFACE_API_VERSION = "kolmafa.surface.v1"
SURFACE_OPERATIONS = ("status", "provider_health")
SURFACE_MODES = ("readonly", "dry_run")
PROVIDER_KINDS = ("static", "ollama")
RESPONSE_STATUS_VALUES = ("ok", "invalid_request", "unsupported_operation", "error")
READINESS_VALUES = ("ready", "unknown", "not_configured")

__all__ = [
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


@dataclass(frozen=True, slots=True)
class SurfaceRequest:
    """Read-only request DTO for the surface contract."""

    api_version: str
    request_id: str
    operation: str
    mode: str
    payload: Mapping[str, object]
    dry_run: bool


@dataclass(frozen=True, slots=True)
class SurfaceResponse:
    """Read-only response DTO for the surface contract."""

    api_version: str
    request_id: str
    operation: str
    status: str
    data: Mapping[str, object]
    reason: str
    recovery_action: str
    redactions_applied: bool
    audit_ref: str
    not_executed: bool


def build_surface_request(
    *,
    request_id: str,
    operation: str,
    mode: str = "readonly",
    payload: Mapping[str, object] | None = None,
    dry_run: bool = True,
) -> SurfaceRequest:
    """Build a read-only surface request without side effects."""

    return SurfaceRequest(SURFACE_API_VERSION, request_id, operation, mode, dict(payload or {}), dry_run)


def handle_surface_request(request: SurfaceRequest) -> SurfaceResponse:
    """Return metadata for a supported read-only operation without executing tools."""

    validation_error = _validate_request(request)
    if validation_error:
        return _response(
            request,
            status="invalid_request",
            data={},
            reason=validation_error,
            recovery_action="Use kolmafa.surface.v1 with readonly or dry_run mode.",
        )
    if request.operation == "status":
        return _response(request, status="ok", data=_status_data(request.payload))
    if request.operation == "provider_health":
        provider_kind = _payload_text(request.payload, "provider_kind", "static")
        if provider_kind not in PROVIDER_KINDS:
            return _response(
                request,
                status="invalid_request",
                data={},
                reason=f"Unsupported provider_kind: {provider_kind}",
                recovery_action="Use provider_kind static or ollama.",
            )
        return _response(request, status="ok", data=_provider_health_data(request.payload))
    return _response(
        request,
        status="unsupported_operation",
        data={},
        reason=f"Unsupported read-only surface operation: {request.operation}",
        recovery_action="Use one of: status, provider_health.",
    )


def get_status_surface(
    *,
    request_id: str,
    mode: str = "readonly",
    payload: Mapping[str, object] | None = None,
) -> SurfaceResponse:
    """Return read-only status metadata."""

    return handle_surface_request(build_surface_request(request_id=request_id, operation="status", mode=mode, payload=payload))


def get_provider_health_surface(
    *,
    request_id: str,
    provider_kind: str = "static",
    mode: str = "readonly",
    payload: Mapping[str, object] | None = None,
) -> SurfaceResponse:
    """Return metadata-only provider health without constructing providers."""

    request_payload = dict(payload or {})
    request_payload["provider_kind"] = provider_kind
    return handle_surface_request(
        build_surface_request(request_id=request_id, operation="provider_health", mode=mode, payload=request_payload)
    )


def to_surface_dict(value: SurfaceRequest | SurfaceResponse) -> dict[str, object]:
    """Serialize a surface DTO to a plain dictionary."""

    return asdict(value)


def _validate_request(request: SurfaceRequest) -> str:
    if request.api_version != SURFACE_API_VERSION:
        return f"Unsupported api_version: {request.api_version}"
    if request.mode not in SURFACE_MODES:
        return f"Unsupported surface mode: {request.mode}"
    return ""


def _response(
    request: SurfaceRequest,
    *,
    status: str,
    data: Mapping[str, object],
    reason: str = "",
    recovery_action: str = "",
) -> SurfaceResponse:
    response_data = dict(data)
    return SurfaceResponse(
        api_version=SURFACE_API_VERSION,
        request_id=request.request_id,
        operation=request.operation,
        status=status,
        data=response_data,
        reason=_surface_redact(reason),
        recovery_action=_surface_redact(recovery_action),
        redactions_applied=_has_populated_redacted_field(response_data),
        audit_ref=f"surface:{_surface_redact(request.request_id)}",
        not_executed=True,
    )


def _status_data(payload: Mapping[str, object]) -> dict[str, object]:
    kolmafia_home_text = _payload_text(payload, "kolmafia_home", "")
    kolmafia_home = Path(kolmafia_home_text) if kolmafia_home_text else None
    player_name = _payload_text(payload, "player_name", "")
    session_dir = kolmafia_home / "sessions" if kolmafia_home is not None else None
    session_file = session_dir / f"{player_name}.txt" if session_dir is not None and player_name else None
    return {
        "database_path_redacted": _redacted_payload_text(payload, "database_path", ""),
        "kolmafia_home_redacted": _surface_redact(str(kolmafia_home or "")),
        "session_dir_redacted": _surface_redact(str(session_dir or "")),
        "cli_command_redacted": _redacted_payload_text(payload, "cli_command", ""),
        "transport": _payload_text(payload, "transport", "relay"),
        "relay_base_url_redacted": _redacted_payload_text(
            payload, "relay_base_url", "http://localhost:60080"
        ),
        "relay_pwd_configured": _payload_bool(
            payload, "relay_pwd_configured", bool(_payload_text(payload, "relay_pwd", ""))
        ),
        "player_name_redacted": _surface_redact(player_name),
        "session_file_redacted": _surface_redact(str(session_file or "")),
        "docker_free_ready": _payload_bool(payload, "docker_free_ready", False),
        "docker_free_problems": _payload_string_tuple(payload, "docker_free_problems", ()),
        "docker_available": _payload_bool(payload, "docker_available", False),
        "container_running": _payload_optional_bool(payload, "container_running"),
        "tool_calls_executed": False,
        "command_dispatch_enabled": False,
        "confirmation_consumed": False,
    }


def _provider_health_data(payload: Mapping[str, object]) -> dict[str, object]:
    provider_kind = _payload_text(payload, "provider_kind", "static")
    readiness = "ready" if provider_kind == "static" else "unknown"
    last_error = _payload_text(payload, "last_error", "")
    return {
        "provider_kind": provider_kind,
        "readiness": readiness,
        "network_checked": False,
        "ollama_instantiated": False,
        "last_error_redacted": _surface_redact(last_error),
        "model_redacted": _redacted_payload_text(payload, "model", ""),
        "tool_calls_executed": False,
        "command_dispatch_enabled": False,
        "confirmation_consumed": False,
    }


def _payload_text(payload: Mapping[str, object], name: str, default: str) -> str:
    value = payload.get(name, default)
    return "" if value is None else str(value)


def _payload_bool(payload: Mapping[str, object], name: str, default: bool) -> bool:
    value = payload.get(name, default)
    return bool(value)


def _payload_optional_bool(payload: Mapping[str, object], name: str) -> bool | None:
    if name not in payload:
        return None
    return bool(payload[name])


def _payload_string_tuple(
    payload: Mapping[str, object], name: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = payload.get(name, default)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple | list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _redacted_payload_text(payload: Mapping[str, object], name: str, default: str) -> str:
    return _surface_redact(_payload_text(payload, name, default))


def _surface_redact(value: object) -> str:
    text = str(value)
    redacted = redact_text(text)
    lower = text.lower()
    if text and redacted == text and any(marker in lower for marker in ("secret", "token", "pwd", "password")):
        return REDACTED
    return redacted


def _has_populated_redacted_field(data: Mapping[str, object]) -> bool:
    return any(key.endswith("_redacted") and value not in ("", None) for key, value in data.items())
