"""Fixtures shared by the trust tests.

`floor` (a KEYS_DIR with a chorus identity and the mantle and origin trust anchors) is defined in
`test_server_auth`, beside the helpers it builds on, and offered here so another module takes it as
a parameter without importing it: an imported fixture used as a parameter reads to the linter as a
redefinition.
"""
from .test_server_auth import floor  # noqa: F401 — a fixture pytest finds here
