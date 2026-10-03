"""Fixed native observation-query surface for Don Edition.

This module implements the request/registry/transport/normalization seam for a
very small set of explicitly reviewed KoLmafia observational functions. It is
offline-first: production code defaults to an unavailable transport, and no
live KoLmafia invocation exists here.

The surface intentionally cannot express generic ASH, gCLI, approvals,
execution ownership, or writer calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


SCHEMA = "don-native-query-v1"


class SideEffect(str, Enum):
    """Explicit side-effect classification for a native-query capability."""

    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    LOCAL_STATE_ONLY = "LOCAL_STATE_ONLY"
    GAME_MUTATING = "GAME_MUTATING"
    STRUCTURAL_DENY = "STRUCTURAL_DENY"
    UNKNOWN = "UNKNOWN"


class NativeQueryError(ValueError):
    """Raised when a native-query request cannot be admitted."""


@dataclass(frozen=True, slots=True)
class NativeQuerySpec:
    """A code-defined fixed native capability."""

    capability_id: str
    native_function: str
    authority: str
    side_effects: SideEffect
    required_argument: str
    result_type: str

    def __post_init__(self) -> None:
        if not self.capability_id or not self.capability_id.startswith("native."):
            raise NativeQueryError("native capability id must use the native. namespace")
        if not self.native_function or any(character.isspace() for character in self.native_function):
            raise NativeQueryError("native function name must be a single reviewed identifier")
        if self.authority != "OBSERVATION_ONLY":
            raise NativeQueryError("only observation-only native queries may be registered")
        if self.side_effects is not SideEffect.OBSERVATION_ONLY:
            raise NativeQueryError("only observation-only native queries may be registered")
        if self.required_argument != "item_id":
            raise NativeQueryError("unsupported fixed native-query argument")


@dataclass(frozen=True, slots=True)
class NativeCanEquipRequest:
    """Typed request for the fixed native.can-equip capability."""

    item_id: int
    capability_id: str = "native.can-equip"

    def __post_init__(self) -> None:
        if self.capability_id != "native.can-equip":
            raise NativeQueryError("unsupported native capability")
        if isinstance(self.item_id, bool) or not isinstance(self.item_id, int):
            raise NativeQueryError("item_id must be an integer")
        if self.item_id <= 0:
            raise NativeQueryError("item_id must be positive")


@dataclass(frozen=True, slots=True)
class NativeQueryRawResult:
    """Transport-level native result before Don normalization."""

    ok: bool
    value: Any
    error: str | None
    transport: str
    item_name: str | None = None
    receipt: dict[str, Any] | None = None


@runtime_checkable
class NativeQueryTransport(Protocol):
    """Explicit seam for invoking one fixed native observation."""

    def query(self, request: NativeCanEquipRequest) -> NativeQueryRawResult:
        """Return a transport-level result without performing game mutation."""


class FakeNativeQueryTransport:
    """Deterministic offline transport for explicitly configured fixtures."""

    def __init__(self, results: Mapping[int, bool] | None = None) -> None:
        mapping = dict(results or {})
        for item_id, value in mapping.items():
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                raise NativeQueryError("fake native item_id must be a positive integer")
            if not isinstance(value, bool):
                raise NativeQueryError("fake native value must be boolean")
        self._results = mapping
        self.calls: list[NativeCanEquipRequest] = []

    def query(self, request: NativeCanEquipRequest) -> NativeQueryRawResult:
        if not isinstance(request, NativeCanEquipRequest):
            raise NativeQueryError("unsupported native request")
        self.calls.append(request)
        if request.item_id not in self._results:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "fake")
        return NativeQueryRawResult(True, self._results[request.item_id], None, "fake")


class UnavailableNativeQueryTransport:
    """Production default: no approved live native transport is configured."""

    def query(self, request: NativeCanEquipRequest) -> NativeQueryRawResult:
        if not isinstance(request, NativeCanEquipRequest):
            raise NativeQueryError("unsupported native request")
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "unavailable")


_REGISTRY: dict[str, NativeQuerySpec] = {}


def _register(spec: NativeQuerySpec) -> NativeQuerySpec:
    if not isinstance(spec, NativeQuerySpec):
        raise NativeQueryError("unsupported registry entry")
    if spec.capability_id in _REGISTRY:
        raise NativeQueryError(f"duplicate native capability: {spec.capability_id}")
    _REGISTRY[spec.capability_id] = spec
    return spec


def get_spec(capability_id: str) -> NativeQuerySpec:
    """Return a registered fixed capability or fail closed."""

    if not isinstance(capability_id, str):
        raise NativeQueryError("capability id must be a string")
    try:
        return _REGISTRY[capability_id]
    except KeyError as exc:
        raise NativeQueryError(f"unknown native capability: {capability_id}") from exc


def resolve_request(payload: Mapping[str, Any]) -> NativeCanEquipRequest:
    """Validate an untrusted mapping into the fixed typed request."""

    if not isinstance(payload, Mapping):
        raise NativeQueryError("native request must be a mapping")
    if set(payload.keys()) != {"capability", "arguments"}:
        raise NativeQueryError("unsupported native request shape")
    capability_id = payload["capability"]
    arguments = payload["arguments"]
    if capability_id != "native.can-equip":
        raise NativeQueryError("unsupported native capability")
    get_spec(capability_id)
    if not isinstance(arguments, Mapping) or set(arguments.keys()) != {"item_id"}:
        raise NativeQueryError("unsupported native.can-equip arguments")
    return NativeCanEquipRequest(item_id=arguments["item_id"])


def _validate_raw_result(raw: object) -> NativeQueryRawResult:
    if not isinstance(raw, NativeQueryRawResult):
        raise NativeQueryError("malformed native result")
    if not isinstance(raw.ok, bool):
        raise NativeQueryError("malformed native result")
    if raw.transport not in ("fake", "unavailable", "live"):
        raise NativeQueryError("unsupported native transport result")
    if raw.receipt is not None and (
        not isinstance(raw.receipt, dict)
        or set(raw.receipt.keys()) - {"event_id", "timestamp", "status", "error_class"}
    ):
        raise NativeQueryError("malformed native receipt")
    if raw.error is not None and not isinstance(raw.error, str):
        raise NativeQueryError("malformed native error")
    return raw


def _unavailable_result(
    *, transport: str, diagnostic: str, item_id: int, receipt: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "capability": "native.can-equip",
        "ok": False,
        "result": None,
        "status": "NATIVE_QUERY_UNAVAILABLE",
        "native_owner": "KoLmafia",
        "authority": "OBSERVATION_ONLY",
        "transport": transport,
        "freshness": "UNAVAILABLE",
        "diagnostics": [diagnostic],
        "item_id": item_id,
        "evidence": receipt,
    }


def normalize_can_equip(raw: NativeQueryRawResult, *, item_id: int) -> dict[str, Any]:
    """Normalize only boolean native can-equip results; fail closed otherwise."""

    try:
        validated = _validate_raw_result(raw)
    except NativeQueryError:
        return _unavailable_result(transport="unknown", diagnostic="malformed native result", item_id=item_id)
    receipt = validated.receipt
    if not validated.ok or validated.value is None:
        return _unavailable_result(
            transport=validated.transport,
            diagnostic=validated.error or "transport reported no value",
            item_id=item_id,
            receipt=receipt,
        )
    if not isinstance(validated.value, bool):
        return _unavailable_result(
            transport=validated.transport,
            diagnostic="malformed native result",
            item_id=item_id,
            receipt=receipt,
        )
    if validated.item_name is not None and (
        not isinstance(validated.item_name, str)
        or not 1 <= len(validated.item_name) <= 200
        or any(ord(character) < 32 for character in validated.item_name)
    ):
        return _unavailable_result(
            transport=validated.transport, diagnostic="malformed native result", item_id=item_id
        )
    if validated.transport == "live":
        freshness = "LIVE"
    elif validated.transport == "fake":
        freshness = "TEST"
    elif validated.transport == "unavailable":
        freshness = "UNAVAILABLE"
    else:  # pragma: no cover - rejected by _validate_raw_result
        freshness = "UNAVAILABLE"
    return {
        "schema": SCHEMA,
        "capability": "native.can-equip",
        "ok": True,
        "result": validated.value,
        "status": "SUCCESS",
        "native_owner": "KoLmafia",
        "authority": "OBSERVATION_ONLY",
        "transport": validated.transport,
        "freshness": freshness,
        "diagnostics": [],
        "item_id": item_id,
        "item_name": validated.item_name,
        "evidence": validated.receipt,
    }


def execute_native_can_equip(
    item_id: int,
    *,
    transport: NativeQueryTransport | None = None,
) -> dict[str, Any]:
    """Execute the fixed native.can-equip query through an explicit transport."""

    request = NativeCanEquipRequest(item_id=item_id)
    active_transport = transport or UnavailableNativeQueryTransport()
    if not isinstance(active_transport, NativeQueryTransport):
        raise NativeQueryError("unsupported native transport")
    try:
        raw = active_transport.query(request)
    except NativeQueryError:
        raise
    except Exception as exc:
        return _unavailable_result(
            transport="unknown", diagnostic=f"transport failed: {type(exc).__name__}", item_id=item_id
        )
    try:
        return normalize_can_equip(raw, item_id=item_id)
    except NativeQueryError:
        return _unavailable_result(transport="unknown", diagnostic="malformed native result", item_id=item_id)


def capability_directory_entry(*, transport_status: str = "UNAVAILABLE") -> dict[str, Any]:
    """Return code-defined metadata for the portable capability directory."""

    if transport_status == "READY":
        availability = "READY"
        freshness = "LIVE"
    else:
        availability = "REGISTERED_BUT_TRANSPORT_UNAVAILABLE"
        freshness = "LIVE when live transport exists"
    return {
        "id": "native.can-equip",
        "native_owner": "KoLmafia",
        "adapter_owner": "Don",
        "authority": "OBSERVATION_ONLY",
        "freshness": freshness,
        "activation": "lazy",
        "transport": {
            "type": "fixed-relay-get",
            "method": "GET",
            "caller_controls_destination": False,
            "caller_controls_function": False,
            "caller_controls_code": False,
        },
        "transport_status": transport_status,
        "availability": availability,
        "mutation_scope": "none",
    }


_register(
    NativeQuerySpec(
        capability_id="native.can-equip",
        native_function="can_equip",
        authority="OBSERVATION_ONLY",
        side_effects=SideEffect.OBSERVATION_ONLY,
        required_argument="item_id",
        result_type="boolean",
    )
)
