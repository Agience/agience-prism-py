"""The shared conformance vectors — the bytes a second implementation is checked against.

Each file here pins a specification as data: the exact bytes, digests and reads that every
implementation of one wire format must reproduce. A second-language implementation is then correct
against bytes rather than against a prose description it has to interpret.

    contract_vectors     canonical JSON / crystal_sha / structural CBOR / the junction — prism py·js·c
    screen_read_vectors  the screen read — the full aperture vs mantle's reduced beacon
    frame_wire_vectors   `BFR1` + rows:u32 + cols:u32 + big-endian float64 — the payload of a reach
    ordering_vectors     the LSH band key and the carrier leaf order
    plane_seal_vectors   AES-256-GCM group-key derivation and the sealed envelope

They live in prism because prism is the specification, the vectors pin a specification, and prism is
a pure leaf that every consumer can already reach.

They ship inside the installed package. `[tool.setuptools.package-data]` in `pyproject.toml` puts
these `.json` files in the wheel, so a consumer that `pip install`ed prism resolves them through a
package handle — no source checkout, no sibling repo, no relative path walk, and the same resolution
wherever the consuming repo sits.

A missing vector file raises `MissingVectors`. A gate whose data is absent has measured nothing, and
the exception is how it says so; there is no return shape here that lets a consumer resolve to
`None` and carry on.

Pure stdlib, so the base install stays the dependency-free contract (see `pyproject.toml`).
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

__all__ = ["VECTOR_NAMES", "MissingVectors", "vector_path", "load_vectors"]

#: Every vector set shipped here. Named explicitly so `tests/test_vectors_package.py` can
#: assert the set rather than whatever happens to be on disk — a file dropped from the wheel
#: would otherwise just reduce the number of things checked, silently.
VECTOR_NAMES: tuple[str, ...] = (
    "contract_vectors",
    "screen_read_vectors",
    "frame_wire_vectors",
    "ordering_vectors",
    "plane_seal_vectors",
)


class MissingVectors(FileNotFoundError):
    """A conformance vector set could not be read from the installed prism package.

    A conformance gate that cannot load its vectors has verified nothing, so this surfaces as a
    failure rather than a skip.
    """


def _traversable(name: str):
    if name not in VECTOR_NAMES:
        raise MissingVectors(
            "%r is not a shared vector set; known sets are %s" % (name, ", ".join(VECTOR_NAMES)))
    return resources.files(__package__) / ("%s.json" % name)


def vector_path(name: str):
    """The importlib.resources traversable for one vector set, verified to be readable.

    Returns a `pathlib.Path` for an ordinary (unzipped) install, which is every install this
    workspace makes. Typed loosely because a zipped install yields a `zipfile.Path` — both
    support `read_text`, and callers here only ever read.
    """
    handle = _traversable(name)
    if not handle.is_file():
        raise MissingVectors(
            "shared conformance vectors %r are missing from the installed prism package "
            "(looked for %s). This gate verifies NOTHING without them. Reinstall "
            "agience-prism-py — do not disable the gate, and do not reintroduce a relative "
            "path walk to a sibling checkout." % (name, handle))
    return handle


def load_vectors(name: str) -> dict[str, Any]:
    """One vector set, parsed. Raises `MissingVectors` if it is absent or unreadable."""
    handle = vector_path(name)
    try:
        text = handle.read_text(encoding="utf-8")
    except OSError as exc:                                    # unreadable is not absent, but it
        raise MissingVectors(                                 # is equally "measured nothing"
            "shared conformance vectors %r could not be read from %s: %s" % (name, handle, exc)
        ) from exc
    return json.loads(text)
