"""Fixed live transport for the native.can-equip read-only query.

Exactly one helper, one path, one native function, one boolean output.
The caller controls only ``item_id`` (already validated by the typed
request). Scheme, host, port, path, method, and headers are fixed by this
module and trusted Don configuration. Only the fixed helper GET is used;
no command endpoint, no interactive shell, and no arbitrary script source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from kolmafa.config import get_settings
from kolmafa.devtest.evidence import record_evidence
from kolmafa.devtest.native_query import (
    NativeCanEquipRequest,
    NativeQueryError,
    NativeQueryRawResult,
    NativeQueryTransport,
)


HELPER_FILENAME = "don_native_can_equip.ash"
HELPER_PATH = "/don_native_can_equip.ash"
# Fixed KoLmafia relay-script dispatch field. This routes the request to the
# installed relay script; it is not a caller-selected operation.
HELPER_DISPATCH_QUERY = "relay=true"
HELPER_SCHEMA = "kolmaf-native-can-equip-v1"
MAX_BODY_BYTES = 8192
_ALLOWED_ERRORS = frozenset({"INVALID_ITEM_ID", "UNKNOWN_ITEM"})

CANONICAL_HELPER_PATH = Path(__file__).resolve().parent / "relay" / HELPER_FILENAME


def helper_sha256() -> str:
    """Return the SHA-256 of the canonical helper source."""

    return hashlib.sha256(CANONICAL_HELPER_PATH.read_bytes()).hexdigest()


def install_helper(dest_dir: Path | None = None) -> dict[str, Any]:
    """Project a canonical helper copy into the verified KoLmafia relay dir.

    Copies bytes verbatim, then re-reads and compares hashes. Records file
    metadata only; never executes the helper.
    """

    settings = get_settings()
    relay_dir = Path(dest_dir) if dest_dir is not None else settings.kolmafia_home / "relay"
    if not relay_dir.is_dir():
        raise NativeQueryError(f"relay directory missing: {relay_dir}")
    canonical = CANONICAL_HELPER_PATH.read_bytes()
    installed = relay_dir / HELPER_FILENAME
    installed.write_bytes(canonical)
    digest = hashlib.sha256(installed.read_bytes()).hexdigest()
    if digest != hashlib.sha256(canonical).hexdigest():
        raise NativeQueryError("installed helper hash mismatch")
    stat = installed.stat()
    return {
        "canonical_source": str(CANONICAL_HELPER_PATH),
        "installed_projection": str(installed),
        "sha256": digest,
        "size_bytes": stat.st_size,
        "mode": oct(stat.st_mode & 0o777),
    }


def _parse_helper_response(body: bytes, item_id: int) -> NativeQueryRawResult:
    """Parse only the allowlisted helper schema; discard everything else."""

    try:
        text = body.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
    if len(body) > MAX_BODY_BYTES:
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
    if not isinstance(data, dict):
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
    if data.get("schema") != HELPER_SCHEMA:
        return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
    if data.get("ok") is True:
        if set(data.keys()) != {"schema", "ok", "item_id", "item_name", "can_equip"}:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if data.get("item_id") != item_id:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        name = data.get("item_name")
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if any(ord(character) < 32 for character in name):
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if not isinstance(data.get("can_equip"), bool):
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        return NativeQueryRawResult(True, bool(data["can_equip"]), None, "live", name)
    if data.get("ok") is False:
        if set(data.keys()) != {"schema", "ok", "item_id", "error"}:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if data.get("item_id") != item_id and not (data.get("item_id") == 0 and isinstance(item_id, int)):
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if data.get("error") not in _ALLOWED_ERRORS:
            return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        return NativeQueryRawResult(False, None, str(data["error"]), "live")
    return NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")


class KoLmafiaCanEquipTransport:
    """Live GET transport for native.can-equip only.

    Each completed query appends exactly one allowlisted T1 evidence receipt.
    Receipt persistence never retries the network request.
    """

    def __init__(
        self,
        *,
        opener: Callable | None = None,
        timeout: float = 10.0,
        evidence_path: Path | None = None,
    ) -> None:
        self._opener = opener or urlopen
        self._timeout = timeout
        self._evidence_path = evidence_path
        self.calls: list[NativeCanEquipRequest] = []

    def _record_receipt(self, *, item_id: int, result: bool | None, result_status: str) -> dict[str, Any]:
        extra = {
            "capability": "native.can-equip",
            "item_id": item_id,
            "result": result,
            "result_status": result_status,
            "transport": "fixed-relay-get",
        }
        try:
            event = record_evidence(
                "native.can-equip",
                "live-read",
                "kolmafa.devtest.native_relay",
                f"native.can-equip item={item_id} result={result} status={result_status}",
                extra=extra,
                evidence_path=self._evidence_path,
            )
        except Exception as exc:
            return {"status": "WRITE_FAILED", "error_class": type(exc).__name__}
        return {"event_id": event["event_id"], "timestamp": event["timestamp"], "status": "RECORDED"}

    def query(self, request: NativeCanEquipRequest) -> NativeQueryRawResult:
        if not isinstance(request, NativeCanEquipRequest):
            raise NativeQueryError("unsupported native request")
        self.calls.append(request)
        settings = get_settings()
        url = (
            settings.relay_base_url.rstrip("/")
            + HELPER_PATH
            + "?relay=true&item_id="
            + str(request.item_id)
        )
        http_request = Request(url, method="GET")
        http_request.add_header("User-Agent", "kolmafa-don-native-query/1.0")
        transport_failed = False
        try:
            with self._opener(http_request, timeout=self._timeout) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except NativeQueryError:
            raise
        except Exception:
            transport_failed = True
            raw = NativeQueryRawResult(False, None, "NATIVE_QUERY_UNAVAILABLE", "live")
        if not transport_failed:
            raw = _parse_helper_response(body, request.item_id)
        if transport_failed:
            result_status = "TRANSPORT_ERROR"
        elif raw.ok and isinstance(raw.value, bool):
            result_status = "SUCCESS"
        elif raw.error in ("INVALID_ITEM_ID", "UNKNOWN_ITEM"):
            result_status = "NATIVE_QUERY_UNAVAILABLE"
        else:
            result_status = "SCHEMA_ERROR"
        receipt = self._record_receipt(
            item_id=request.item_id,
            result=raw.value if isinstance(raw.value, bool) else None,
            result_status=result_status,
        )
        return NativeQueryRawResult(raw.ok, raw.value, raw.error, raw.transport, raw.item_name, receipt)


assert isinstance(KoLmafiaCanEquipTransport(), NativeQueryTransport)
