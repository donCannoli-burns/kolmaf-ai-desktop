"""Live GCLI transport for sending commands to KoLmafia.

This module is quarantined outside the daemon-core MVP import graph.
Live KoLmafia GCLI execution requires the future plugin-write infrastructure;
the current default is always kill-switched (denied).
"""

from __future__ import annotations

from kolmafa.bridge import CommandResult, DeniedGcliWriter


def send_command(cli_command: str | None, command: str, timeout: float = 60.0) -> CommandResult:
    """Send a raw command to the configured KoLmafia CLI wrapper.

    This live send transport is intentionally kill-switched by default. The
    command is never launched, echoed, or persisted by this function until later
    policy and confirmation gates provide an explicit allow path.
    """
    del cli_command, command, timeout
    return DeniedGcliWriter().write("")
