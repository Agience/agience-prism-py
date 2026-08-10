"""`prism.trust.scopes` — the scope vocabulary, split from the service that enforces it.

Parsing a scope string and matching a content type are pure functions of the string (a contract);
turning a failed check into a 403 needs fastapi, an APIKey row and a request (a service, which
lives in origin). These cases pin the contract half.
"""
from __future__ import annotations

import pytest

from prism.trust.scopes import (
    content_type_matches,
    extract_licensing_entitlements,
    is_special_scope,
    parse_scope,
)


def test_the_module_needs_only_the_standard_library():
    """The `trust` extra must not grow a web framework, and `origin/scopes.py` imports fastapi at
    module scope — the reason only the pure-function half lives here. Reads the source, so it fails
    on a re-added import even though fastapi is installed in this environment."""
    import ast
    import pathlib
    import sys

    import prism.trust.scopes as mod

    tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            imported.add(node.module.split(".")[0])
    outside = imported - set(sys.stdlib_module_names)
    assert not outside, f"the scope vocabulary grew a third-party import: {sorted(outside)}"


# ── licensing scopes: the one function chorus reads ───────────────────────────────────────────────
def test_licensing_entitlements_are_extracted():
    got = extract_licensing_entitlements([
        "licensing:entitlement:foresight_pro",
        "licensing:entitlement:seats-25",
        "resource:text/markdown:read",
        "licensing:entitlement:",                  # malformed — no name
        "licensing:entitlement:bad name",          # malformed — space
    ])
    assert got == {"foresight_pro", "seats-25"}


def test_no_licensing_scopes_yields_the_empty_set():
    assert extract_licensing_entitlements(["resource:text/*:read"]) == set()
    assert extract_licensing_entitlements([]) == set()


def test_special_scopes_are_recognised():
    assert is_special_scope("collections:commit:verified")
    assert is_special_scope("licensing:entitlement:pro")
    assert not is_special_scope("resource:text/markdown:read")


# ── parse_scope ───────────────────────────────────────────────────────────────────────────────────
def test_parse_scope_reads_all_four_components():
    assert parse_scope("resource:text/markdown:write") == ("resource", "text/markdown", "write", False)
    assert parse_scope("resource:text/markdown:write:anonymous") == (
        "resource", "text/markdown", "write", True)
    assert parse_scope("tool:application/vnd.agience.collection+json:search") == (
        "tool", "application/vnd.agience.collection+json", "search", False)


@pytest.mark.parametrize("bad", [
    "resource:text/markdown",                       # too few parts
    "widget:text/markdown:read",                    # invalid type
    "resource:text/markdown:teleport",              # invalid action
    "resource:not a content type:read",             # invalid content type
    "licensing:entitlement:pro",                    # special scope — raises rather than mis-parsing
    "collections:commit:verified",                  # special scope
])
def test_parse_scope_refuses_what_it_cannot_read(bad):
    with pytest.raises(ValueError):
        parse_scope(bad)


# ── content_type_matches ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("scope_ct,required,expected", [
    ("text/markdown", "text/markdown", True),
    ("text/*", "text/markdown", True),
    ("text/*", "text/plain", True),
    ("*", "application/json", True),
    ("text/markdown", "text/plain", False),
    ("text/*", "application/json", False),
    ("text", "text/plain", False),                  # malformed scope side
    ("text/*", "text", False),                      # malformed required side
])
def test_content_type_matching(scope_ct, required, expected):
    assert content_type_matches(scope_ct, required) is expected
