"""The scope vocabulary — what a scope string means, and whether one covers a request.

A contract is what a token means; a service is what a deployment does about it. Parsing
`resource:text/markdown:read`, matching a content-type wildcard and recognising a special scope are
pure functions of the string — every consumer needs them, and they are the same in every
deployment, so they live here. Turning a failed check into an HTTP 403 needs `fastapi`, an `APIKey`
row and a request; that is enforcement, and it lives in Origin (`origin/scopes.py`, which imports
its vocabulary from here).

That split is also what keeps prism installable: each extra names only what its own modules import,
and this module needs `re`. Enforcement would put a web framework in the `trust` extra.

Scope format: ``type:contentType:action[:anonymous]``

  * **type** — resource, tool, prompt (maps to MCP primitives)
  * **contentType** — a content type or a wildcard (``text/markdown``, ``text/*``, ``*``)
  * **action** — read, write, search, invoke, delete, create
  * **anonymous** — optional suffix; the default is identified access

Special system scopes use a separate grammar — ``licensing:entitlement:<name>`` and the members of
:data:`SPECIAL_SCOPES`. :func:`parse_scope` raises ``ValueError`` on them, so they have no parse
under the content-type grammar; use :func:`is_special_scope` to recognise them.

Scopes control content-type access (*what you can do*); URIs control storage location (*where it
lives*), and the backend routes by URI scheme (``agience://``, ``file://``, ``s3://``, ``https://``).
"""

from __future__ import annotations

import re
from typing import Tuple

VALID_TYPES = {"resource", "tool", "prompt"}
VALID_ACTIONS = {"read", "write", "search", "invoke", "delete", "create"}
SPECIAL_SCOPES = {
    "collections:commit:verified",
}
LICENSING_SCOPE_PATTERN = re.compile(r"^licensing:entitlement:([a-zA-Z0-9_\-]+)$")

# Content type pattern: type/subtype (supports wildcards and vendor prefixes)
# Examples: text/plain, application/vnd.agience.collection+json, text/*, *
CONTENT_TYPE_PATTERN = re.compile(r'^([\w\-\+]+|\*)(/([\w\-\+\.\*]+))?$')


def is_special_scope(scope_str: str) -> bool:
    """Return True when a scope uses one of the reserved system-level formats."""
    return scope_str in SPECIAL_SCOPES or bool(LICENSING_SCOPE_PATTERN.match(scope_str))


def extract_licensing_entitlements(scopes: list[str]) -> set[str]:
    """Extract entitlement names from explicit licensing scopes."""
    entitlements: set[str] = set()
    for scope in scopes:
        match = LICENSING_SCOPE_PATTERN.match(scope)
        if match:
            entitlements.add(match.group(1))
    return entitlements


def parse_scope(scope_str: str) -> Tuple[str, str, str, bool]:
    """
    Parse a scope string into components.

    Args:
        scope_str: Scope in format "type:contentType:action[:anonymous]"
        Examples:
            "resource:text/markdown:write"
            "resource:text/markdown:write:anonymous"
            "tool:application/vnd.agience.collection+json:search"
            "resource:text/*:read"

    Returns:
        Tuple of (type, content_type, action, is_anonymous)

    Raises:
        ValueError: If scope format is invalid
    """
    if is_special_scope(scope_str):
        raise ValueError(f"Special system scope '{scope_str}' does not use content type scope parsing")

    parts = scope_str.split(":")

    if len(parts) < 3:
        raise ValueError(
            f"Invalid scope format: '{scope_str}'. "
            f"Must be 'type:contentType:action[:anonymous]'"
        )

    scope_type = parts[0]
    content_type = parts[1]
    action = parts[2]
    is_anonymous = len(parts) >= 4 and parts[3] == "anonymous"

    # Validate type
    if scope_type not in VALID_TYPES:
        raise ValueError(f"Invalid type: '{scope_type}'. Must be one of {VALID_TYPES}")

    # Validate content type
    if not CONTENT_TYPE_PATTERN.match(content_type):
        raise ValueError(
            f"Invalid content type: '{content_type}'. "
            f"Must be valid content type or wildcard (e.g., text/markdown, text/*, *)"
        )

    # Validate action
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: '{action}'. Must be one of {VALID_ACTIONS}")

    return scope_type, content_type, action, is_anonymous


def content_type_matches(scope_content_type: str, required_content_type: str) -> bool:
    """
    Check if a scope content type matches a required content type (supports wildcards).

    Args:
        scope_content_type: Content type from scope (may contain wildcards)
        required_content_type: Required content type (no wildcards)

    Returns:
        True if matches

    Examples:
        content_type_matches("text/markdown", "text/markdown") -> True
        content_type_matches("text/*", "text/markdown") -> True
        content_type_matches("text/*", "text/plain") -> True
        content_type_matches("*", "application/json") -> True
        content_type_matches("text/markdown", "text/plain") -> False
    """
    if scope_content_type == "*":
        return True  # Universal wildcard

    if "/" not in scope_content_type:
        return False  # Invalid format

    scope_main, scope_sub = scope_content_type.split("/", 1)

    if "/" not in required_content_type:
        return False

    required_main, required_sub = required_content_type.split("/", 1)

    # Check main type
    if scope_main != "*" and scope_main != required_main:
        return False

    # Check subtype
    if scope_sub == "*":
        return True  # Wildcard subtype

    return scope_sub == required_sub


__all__ = [
    "VALID_TYPES", "VALID_ACTIONS", "SPECIAL_SCOPES", "LICENSING_SCOPE_PATTERN",
    "CONTENT_TYPE_PATTERN", "is_special_scope", "extract_licensing_entitlements",
    "parse_scope", "content_type_matches",
]
