"""Suite-wide fail-closed for real /sideCommand during unit tests.

Any test that forgets to inject a fake opener and tries to POST to
http://localhost:60080/sideCommand will fail loudly instead of reaching
the live KoLmafia relay.
"""

import pytest
from unittest.mock import Mock


@pytest.fixture(autouse=True)
def block_real_sidecommand(monkeypatch):
    # Suite-wide fail-closed: any RelayWriter using default real opener
    # must never reach real /sideCommand during tests, regardless of credential.
    # Explicitly injected fake opener is allowed.
    try:
        import kolmafa.devtest.relay_writer as rw
        from kolmafa.bridge import CommandResult
        from kolmafa.redaction import redact_text
        from kolmafa.bridge import RELAY_TRANSPORT
        import urllib.request as _urllib
    except ImportError:
        yield
        return

    original_write = rw.RelayWriter.write
    real_opener = _urllib.urlopen
    # Capture original module-level urlopen for comparison (may be patched by other fixtures)
    try:
        module_urlopen = rw.urlopen
    except AttributeError:
        module_urlopen = real_opener

    def guarded_write(self, command, timeout=60.0):
        # If writer is using default real opener (not explicitly injected fake), block
        # But only if credential is present (would actually try network); missing credential already fails closed without network
        if not getattr(self, "relay_pwd", None):
            return original_write(self, command, timeout)
        opener = getattr(self, "_opener", None)
        # Consider injected fake as any opener that is not the real urlopen
        # Real opener is either _urllib.urlopen or rw.urlopen (original)
        is_real_default = opener is real_opener or opener is module_urlopen or opener is None
        # Also treat Mock as fake (explicit injection via Mock)
        is_mock = isinstance(opener, Mock)
        if is_mock:
            is_real_default = False
        # If no explicit fake (is_real_default) and this is a test, block before network
        # We are always in pytest here (autouse), so block any real POST attempt
        if is_real_default:
            # Check if this would be a sideCommand POST (RelayWriter always POSTs to sideCommand)
            # So any write with real opener in tests is a sideCommand attempt
            return CommandResult(
                command=redact_text(command),
                transport=RELAY_TRANSPORT,
                return_code=2,
                stdout="",
                stderr="test isolation: real sideCommand blocked - inject fake opener explicitly via RelayWriter(opener=...)\n",
            )
        return original_write(self, command, timeout)

    monkeypatch.setattr(rw.RelayWriter, "write", guarded_write)
    yield
