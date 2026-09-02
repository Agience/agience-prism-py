"""Two test modules may share a basename only if packaging keeps them apart.

Without `__init__.py`, pytest can import a test module under its bare basename, so two files called
`test_auth.py` resolve to one module name: the second import finds the first already in `sys.modules`
and returns it, and the second file's tests never run. `agience-observe/bundle_spec.json` pins every
module path rather than searching by basename for the same reason (`sage/operators.py` vs
`iris/comms/operators.py`).

This repo has a live duplicate and it is safe: `tests/host/test_auth.py` (10 tests) and
`tests/server/test_auth.py` (4) both collect, because `tests/`, `tests/host/` and `tests/server/`
each carry an `__init__.py`, making them `tests.host.test_auth` and `tests.server.test_auth`.

Measured on this pytest and import mode: removing both package markers stops collection with
`10 tests collected, 1 error` — an import-file-mismatch, which is loud. Removing only one leaves all
14 collecting. So on this configuration the defect announces itself.

The gate is worth having for reasons narrower than "it hides tests":

  * a collection error interrupts the whole run — loud, but a broken suite rather than a clean signal
    about one file;
  * the silent form is real under other import modes and older pytest, and nothing pins this repo to
    the version where it is loud;
  * `--continue-on-collection-errors`, which CI runners reach for, turns the loud form back into a
    quiet one.

So this asserts the structure that makes the question moot.
"""
from __future__ import annotations

import collections
import pathlib

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
SKIP = {"__pycache__", ".pytest_cache"}

# setuptools' default sdist picks up `tests/test*.py` and nothing below it, so an unpacked sdist has
# the top-level test modules and none of the subpackages. The structural gate below still holds
# there — it just has no duplicate to look at.
SUBPACKAGES_PRESENT = all((TESTS / d / "__init__.py").is_file()
                          for d in ("host", "server", "trust"))


def _test_modules():
    for p in sorted(TESTS.rglob("test_*.py")):
        if set(p.parts) & SKIP:
            continue
        yield p


def _duplicate_basenames() -> dict:
    by_name = collections.defaultdict(list)
    for p in _test_modules():
        by_name[p.name].append(p)
    return {k: v for k, v in by_name.items() if len(v) > 1}


def _is_package_protected(path: pathlib.Path) -> bool:
    """Every directory from `tests/` down to this file must be a package, or the module is imported
    under its bare basename and can collide."""
    d = path.parent
    while True:
        if not (d / "__init__.py").is_file():
            return False
        if d == TESTS:
            return True
        d = d.parent


def test_every_DUPLICATE_basename_is_package_protected():
    """The gate. A duplicate basename is fine; an unpackaged duplicate is not.

    Measured on this pytest (see the header): the unprotected case errors during collection rather
    than passing quietly. This asserts the structure anyway — the quiet form is real under other
    import modes, and `--continue-on-collection-errors` converts the loud form back into a quiet one.

    Fails if a second `test_x.py` appears in a directory with no `__init__.py`, or an `__init__.py`
    is deleted from a directory that already holds one. Both read as harmless tidying.
    """
    unsafe = {}
    for name, paths in _duplicate_basenames().items():
        bad = [p.relative_to(TESTS).as_posix() for p in paths if not _is_package_protected(p)]
        if bad:
            unsafe[name] = bad
    assert not unsafe, (
        "these test modules share a basename with another and are NOT package-protected, so one "
        "silently shadows the other and its tests never run: %s. Add `__init__.py` to every "
        "directory on the path, or rename one file." % unsafe)


def test_the_KNOWN_duplicate_still_collects_BOTH_files():
    """The positive control for the gate above. Asserting "no unsafe duplicates" would pass on a
    repo with no duplicates at all — this pins the one that exists, so the protection is exercised
    rather than assumed.

    Fails if `tests/host/__init__.py` or `tests/server/__init__.py` is deleted, or one of the two
    files is removed rather than renamed. The gate above catches the structure; this catches the
    duplicate itself disappearing.
    """
    if not SUBPACKAGES_PRESENT:
        pytest.skip("the test subpackages are not present — this tree carries no duplicate to pin")
    dupes = _duplicate_basenames()
    assert "test_auth.py" in dupes, (
        "the known duplicate is gone. If that was deliberate, delete this test — but check first "
        "that a file was RENAMED and not silently lost.")
    for p in dupes["test_auth.py"]:
        assert _is_package_protected(p), p


def test_THE_DETECTOR_CAN_ACTUALLY_FAIL(tmp_path):
    """Vacuity control. `_is_package_protected` walking to a wrong root would return True for
    everything and the gate would pass on any tree.

    Fails if the loop terminates on the first directory instead of walking to `tests/`. Proven on a
    planted tree where the middle directory has no `__init__.py`.
    """
    global TESTS
    root = tmp_path / "tests"
    (root / "a").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "a" / "test_x.py").write_text("", encoding="utf-8")      # a/ has no __init__.py
    saved, TESTS = TESTS, root
    try:
        assert _is_package_protected(root / "a" / "test_x.py") is False, (
            "an unpackaged directory was reported as protected — the gate cannot fail")
        (root / "a" / "__init__.py").write_text("", encoding="utf-8")
        assert _is_package_protected(root / "a" / "test_x.py") is True, (
            "a fully packaged path was reported unprotected — the gate fires on everything")
    finally:
        TESTS = saved
