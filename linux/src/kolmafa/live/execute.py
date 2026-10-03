"""Live authorize-then-execute helper path.

This module quarantines the confirmation consumption and live execution bridge
for the MVP relay and GCLI transports.  The dry-run writer path in
``kolmafa.bridge`` evaluates policy and records evidence, but it does not call
``ConfirmationStore.consume``.  The actual consume-and-execute belongs here
once the live gate is implemented (SR5+).
"""

from __future__ import annotations
