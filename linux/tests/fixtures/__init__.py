"""Test fixtures for portable contract tests.

`matrix/` is a SYNTHETIC minimal Matrix corpus: hand-authored, contains no
copied production corpus content, no credentials, no home-dir paths, and no
runtime secrets. It exists so overlay-compiler semantics can be tested
without the installed 665-node corpus under ~/.kolmafia.

`portable.py` derives a portable LinkBus registry from the committed source
manifests (integration/providers/*.json): provider/identity URIs are the
portable semantic identity; the machine-local installed target paths are
replaced by placeholder strings and `exists` is set False so no host state
is probed or faked as installed.
"""
