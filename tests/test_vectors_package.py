"""The shared vectors ship inside the installed package — the gate on the gate.

`prism/vectors/*.json` pins the bytes that prism-py, prism-js, prism-c, ember's aperture and
mantle's beacon are each checked against. The files must travel with a `pip install`, and this file
is what makes that claim falsifiable.

Each failure mode below is pinned by a test, stated first because a green suite would otherwise hide
it:

  * `[tool.setuptools.package-data]` is dropped or misspelled. A SOURCE checkout keeps working —
    the files are right there on disk — so every conformance gate stays green while the built wheel
    ships none of them, and the breakage appears only for the installed consumer this move exists
    to serve. Only reading the DECLARATION catches that, so it is asserted directly.
  * A vector set is deleted. Its consumer's parametrised tests then collect zero cases and pass.
    `VECTOR_NAMES` pins the SET, not whatever happens to be on disk.
  * `load_vectors` grows a "not found, carry on" path. `load_vectors` and `vector_path` raise
    `MissingVectors` for an unknown name instead, asserted as behaviour here.
"""
from __future__ import annotations

import json
import pathlib
import tomllib

import pytest

from prism.vectors import VECTOR_NAMES, MissingVectors, load_vectors, vector_path

_PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_every_named_vector_set_resolves_and_parses():
    """Through `importlib.resources` — the SAME mechanism a wheel-installed consumer uses."""
    assert VECTOR_NAMES, "the vector set roster is empty; this whole file would be vacuous"
    for name in VECTOR_NAMES:
        doc = load_vectors(name)
        assert isinstance(doc, dict) and doc, "%s parsed to nothing" % name


def test_the_five_shared_sets_are_all_present():
    """Named explicitly. A set that quietly stops shipping takes its consumer's gate with it, and
    the consumer reports success on zero cases rather than reporting the loss."""
    assert set(VECTOR_NAMES) == {
        "contract_vectors", "screen_read_vectors", "frame_wire_vectors",
        "ordering_vectors", "plane_seal_vectors",
    }


def test_the_packaging_declares_the_vectors_as_package_data():
    """The check that cannot be made any other way.

    Every other assertion in this file passes from a source checkout whether or not the wheel
    carries the data — the files are on disk either way. If `package-data` is dropped, the whole
    workspace stays green and only a `pip install`ed consumer breaks. So the declaration itself is
    the thing asserted.
    """
    assert _PYPROJECT.is_file(), (
        "pyproject.toml not found at %s — this test cannot verify the packaging declaration and "
        "must not pretend otherwise" % _PYPROJECT)
    cfg = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    package_data = cfg["tool"]["setuptools"].get("package-data", {})
    assert "prism.vectors" in package_data, (
        "[tool.setuptools.package-data] no longer declares `prism.vectors`. Without it the built "
        "wheel ships no vector files and every cross-implementation gate silently loses its data "
        "on an installed consumer, while a source checkout stays green.")
    patterns = package_data["prism.vectors"]
    assert any(p.endswith(".json") or p == "*" for p in patterns), (
        "`prism.vectors` package-data does not match the .json vector files: %r" % patterns)


def test_a_missing_or_unknown_vector_set_raises_rather_than_returning_none():
    """Raising `MissingVectors` rather than returning `None` is the point of this test: a `None`
    would let a caller `skipif` on it, turning a missing vector set into a passing gate that
    checked nothing.
    """
    with pytest.raises(MissingVectors):
        load_vectors("no_such_vectors")
    with pytest.raises(MissingVectors):
        vector_path("no_such_vectors")


def test_the_vector_files_are_json_objects_on_disk_too():
    """Reading through the resource handle and reading the bytes must agree — a stale duplicate
    elsewhere on the path would otherwise be what every gate is actually checking against."""
    for name in VECTOR_NAMES:
        handle = vector_path(name)
        assert json.loads(handle.read_text(encoding="utf-8")) == load_vectors(name)
