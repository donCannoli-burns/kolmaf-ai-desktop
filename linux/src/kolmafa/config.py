"""Runtime configuration for Kolmafa."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


DOCKER_FREE_TRANSPORT = "docker-free"
DEFAULT_TRANSPORT = "relay"
VALID_TRANSPORTS = frozenset({DEFAULT_TRANSPORT, "cli", DOCKER_FREE_TRANSPORT})
PLAYER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ConfigError(ValueError):
    """Raised when environment configuration fails closed."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Environment-backed settings."""

    database_path: Path
    kolmafia_home: Path
    cli_command: str | None
    send_timeout: float
    transport: str
    relay_base_url: str
    relay_pwd: str | None
    player_name: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[2]
        transport = _validated_transport(os.environ.get("KOLMAFA_TRANSPORT", DEFAULT_TRANSPORT))
        player_name = validate_player_name(os.environ.get("KOLMAFA_PLAYER_NAME"))
        kolmafia_home = _validated_kolmafia_home(
            os.environ.get("KOLMAFA_KOLMAFIA_HOME", str(root / "data" / "runtime" / "kolmafia"))
        )
        return cls(
            database_path=Path(os.environ.get("KOLMAFA_DB", root / "data" / "kolmafa.db")),
            kolmafia_home=kolmafia_home,
            cli_command=os.environ.get("KOLMAFA_CLI_COMMAND"),
            send_timeout=float(os.environ.get("KOLMAFA_SEND_TIMEOUT", "120")),
            transport=transport,
            relay_base_url=os.environ.get("KOLMAFA_RELAY_BASE_URL", "http://localhost:60080"),
            relay_pwd=_resolve_relay_pwd(),
            player_name=player_name,
        )


def _most_recent_rotation_utc(now_utc: datetime | None = None) -> datetime:
    """Return most recent completed 19:30 America/Phoenix rotation as UTC.

    Uses America/Phoenix (MST, no DST, UTC-7) if ZoneInfo available,
    otherwise falls back to fixed -7 offset.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if ZoneInfo is not None:
        try:
            phx = ZoneInfo("America/Phoenix")
            now_phx = now_utc.astimezone(phx)
            today_reset = now_phx.replace(hour=19, minute=30, second=0, microsecond=0)
            if now_phx >= today_reset:
                recent_phx = today_reset
            else:
                recent_phx = today_reset - timedelta(days=1)
            return recent_phx.astimezone(timezone.utc)
        except Exception:
            pass
    # Fallback: fixed -7
    az_offset = timedelta(hours=-7)
    now_phx = now_utc + az_offset
    today_reset = now_phx.replace(hour=19, minute=30, second=0, microsecond=0)
    if now_phx >= today_reset:
        recent_phx = today_reset
    else:
        recent_phx = today_reset - timedelta(days=1)
    return (recent_phx.replace(tzinfo=timezone.utc) - az_offset) if recent_phx.tzinfo is None else recent_phx.astimezone(timezone.utc)


def _is_daily_hash_fresh(now_utc: datetime | None = None) -> bool:
    """Check if daily-hash file is fresh for most recent rotation.

    Requires hash file valid shape, metadata exists/parseable, last_updated >= recent rotation.
    """
    store_path = Path.home() / ".kolmafia" / "daily-hash"
    meta_path = Path.home() / ".kolmafia" / "daily-hash.meta"
    # Hash shape already validated elsewhere, but re-check for freshness
    try:
        if not store_path.is_file() or store_path.is_dir():
            return False
        data = store_path.read_bytes().decode("utf-8", errors="strict").strip()
        if len(data) != 32 or not re.fullmatch(r"[0-9a-f]{32}", data):
            return False
    except Exception:
        return False
    try:
        if not meta_path.is_file():
            return False
        meta_text = meta_path.read_text(encoding="utf-8")
        meta = json.loads(meta_text)
        raw = meta.get("last_updated")
        if not isinstance(raw, str) or not raw:
            return False
        # Parse ISO, handle Z
        last_updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        else:
            last_updated = last_updated.astimezone(timezone.utc)
    except Exception:
        return False
    try:
        recent = _most_recent_rotation_utc(now_utc)
        return last_updated >= recent
    except Exception:
        return False


def _resolve_relay_pwd() -> str | None:
    """Resolve relay credential with precedence: env > daily-hash file (if fresh) > none.

    File-backed credential must be exactly 32 lower-hex chars after stripping
    and must be fresh per metadata last_updated >= recent 19:30 Phoenix.
    Read-only, no creation, no logging.
    """
    env_val = os.environ.get("KOLMAFA_RELAY_PWD")
    if env_val is not None and env_val != "":
        return env_val

    # Fallback to protected store — check shape first, then freshness
    store_path = Path.home() / ".kolmafia" / "daily-hash"
    try:
        if not store_path.is_file() or store_path.is_dir():
            return None
        data = store_path.read_bytes()
    except Exception:
        return None
    try:
        text = data.decode("utf-8", errors="strict")
    except Exception:
        return None
    stripped = text.strip()
    if len(stripped) != 32 or not re.fullmatch(r"[0-9a-f]{32}", stripped):
        return None
    # Freshness check for file path only
    if not _is_daily_hash_fresh():
        return None
    return stripped


def get_credential_source() -> str:
    """Return safe metadata about credential source (no raw credential)."""
    env_val = os.environ.get("KOLMAFA_RELAY_PWD")
    if env_val is not None and env_val != "":
        return "env"
    # File source only if fresh
    if _is_daily_hash_fresh():
        return "daily-hash-store"
    return "none"


def is_credential_fresh() -> bool:
    """Return whether file-backed credential is fresh (safe metadata)."""
    env_val = os.environ.get("KOLMAFA_RELAY_PWD")
    if env_val is not None and env_val != "":
        # Env override is considered fresh (explicit)
        return True
    return _is_daily_hash_fresh()


def get_settings() -> Settings:
    """Return settings from the current process environment."""

    return Settings.from_env()


def _validated_transport(value: str) -> str:
    transport = value.strip().lower()
    if transport not in VALID_TRANSPORTS:
        raise ConfigError("KOLMAFA_TRANSPORT is invalid; expected relay, cli, or docker-free")
    return transport


def validate_player_name(value: str | None) -> str | None:
    """Return a safe KoLmafia player/session-log basename or fail closed."""

    if value is None or value == "":
        return None
    if not PLAYER_NAME_PATTERN.fullmatch(value):
        raise ConfigError("KOLMAFA_PLAYER_NAME is invalid; expected 1-64 safe filename characters")
    return value


def _validated_kolmafia_home(value: str) -> Path:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ConfigError("KOLMAFA_KOLMAFIA_HOME is invalid; control characters are not allowed")
    path = Path(value).expanduser()
    if not path.parts:
        raise ConfigError("KOLMAFA_KOLMAFIA_HOME is invalid; empty path is not allowed")
    if any(part == ".." for part in path.parts):
        raise ConfigError("KOLMAFA_KOLMAFIA_HOME is invalid; traversal segments are not allowed")
    return path
