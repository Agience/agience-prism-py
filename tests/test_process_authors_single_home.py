"""`PROCESS_AUTHORS` has one home — asserted against the source, not against an import.

"Is this author subject a PROGRAM?" is answered by one frozenset, imported everywhere it is asked:
`mantle/services/principal.py` reads it to decide whether to mint a person artifact or a foundation
entity, `crystal/evolution.py` reads the same object for `preserve_fitness`'s creator-clobber guard.
A second, independently maintained copy would agree only by coincidence, and edited on one side and
not the other it would answer differently about the same author — minting
`application/vnd.agience.person+json` for an ingest program in one repo while the other correctly
calls it a process.

Why the assertion is an AST scan and not `assert a == b`: comparing the two imported values is a
check that cannot fail in the way that matters. After the re-export both names resolve to the same
object, so equality holds *whether or not* a third copy is declared somewhere else. What must be
true is stronger and is about the SOURCE — exactly one module in the workspace ASSIGNS this name. A
fourth declaration would agree on the day it is written, and drift silently afterwards.

The failure modes these tests watch for, stated first so they can fail:
  - a second module ASSIGNS `PROCESS_AUTHORS` or defines `is_process_author`, re-forking the answer;
  - the re-exports stop resolving to prism's object, so the modules answer independently again;
  - the set silently loses a member that live rows depend on (each named subject is pinned).
"""
import ast
import importlib
import pathlib

import pytest

from prism.principals import PROCESS_AUTHORS, is_process_author

# The workspace root — this file is `<root>/agience-prism/py/tests/`. Derived, never configured: a
# typed-in path would silently scan nothing if the layout moved, which is a pass by absence.
ROOT = pathlib.Path(__file__).resolve().parents[3]

# The sibling source trees that participate. `_ci-work` and `_archive` are BUILD COPIES and archives
# of these same repos, so scanning them reports the same declaration twice under another path.
REPOS = ("agience-prism/py/src", "agience-mantle/src", "agience-crystal/src",
         "agience-chorus/src", "agience-ember/src")

HOME = ROOT / "agience-prism/py/src/prism/principals.py"


def _sources():
    for rel in REPOS:
        base = ROOT / rel
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts or "node_modules" in p.parts:
                continue
            yield p


def _declarers(name):
    """Every file that BINDS `name` by assignment or `def` — an import is not a declaration."""
    out = []
    for p in _sources():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                    out.append(p)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                out.append(p)
    return sorted(set(out))


@pytest.mark.parametrize("name", ["PROCESS_AUTHORS", "is_process_author"])
def test_exactly_one_module_declares_it(name):
    """The one that matters. One question, one declaration, in the module both repos depend on."""
    found = _declarers(name)
    assert found, "%s is declared NOWHERE — the scan found no source, which is not a pass" % name
    assert found == [HOME], (
        "%s is declared in %d place(s): %s. It belongs only in prism/principals.py — one question, one "
        "home, and a leaf module both mantle and crystal can reach when neither may reach the other."
        % (name, len(found), [str(p.relative_to(ROOT)) for p in found]))


def test_both_re_exports_are_the_SAME_object():
    """The re-exports are what keep existing callers working; if one is rebound to a local copy the
    AST scan above catches the declaration, and this catches a rebinding to some other module's.

    The skip gate is the PACKAGE, not the module that re-exports. Neither mantle nor crystal is a
    prism dependency — prism is the leaf they both import, and the edge may not run the other way —
    so a bare SDK install has neither installed and there is genuinely nothing here to compare.
    Once the package IS importable the re-exporting module is imported outright, because
    `importorskip` on the module cannot tell "mantle is not installed" from "the home is gone":
    both read as a skip, and the second is the exact failure this file exists to catch, reported
    as a pass.
    """
    pytest.importorskip("mantle")
    pytest.importorskip("crystal")
    mantle = importlib.import_module("mantle.services.principal")
    crystal = importlib.import_module("crystal.evolution")
    assert mantle.PROCESS_AUTHORS is PROCESS_AUTHORS
    assert crystal.PROCESS_AUTHORS is PROCESS_AUTHORS
    assert mantle.is_process_author is is_process_author
    assert crystal.is_process_author is is_process_author


def test_every_member_is_pinned_because_live_rows_depend_on_it():
    """Each subject here authored rows on the live shard. Dropping one does not raise anywhere — it
    re-mints that author as a PERSON on the next write, which is a false claim about a human and a
    second, colliding identity for the same program. So membership is asserted, not assumed."""
    assert PROCESS_AUTHORS == frozenset(
        {"ember-source", "ember-local", "sage-canon", "probe@local"})
    for sub in PROCESS_AUTHORS:
        assert is_process_author(sub)
        assert is_process_author("  %s  " % sub), "the subject is not stripped before matching"


def test_a_person_is_not_a_process():
    """The negative direction, which the membership test above cannot give: a human subject must
    answer False, or `principal_artifact` mints a foundation entity for a person."""
    for sub in ("john@ikailo.com", "", None, "ember", "canon", "sage"):
        assert not is_process_author(sub), sub
