"""The one rounding law, held against an independent oracle and against its own inputs.

`prism.rounding` is the single home of a bound that had been written out in several places. The
arithmetic those copies used is kept below, longhand, as an oracle, and the sweep that compared them
runs here as a test rather than as a one-off.

A sweep of this kind is worth keeping because a derivation can be exactly as wrong as a constant
when it models the wrong error. Two implementations can agree on almost the whole input space and
diverge only in the pocket where cancellation dominates over accumulation, so a handful of
hand-picked examples would not catch a wrong error model — only a full sweep does.

The oracle is copied rather than imported, and stays that way. An oracle that calls the thing it
checks shows only that a function equals itself. When `rounding.py` changes, this file changes in
the same commit and every moved number is accounted for, so the change is visible.
"""
from __future__ import annotations

import ast
import itertools
import math
import pathlib
import struct
import sys

import pytest

from prism.rounding import accumulated_rounding, split_walk_operations, split_walk_rounding

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "prism"


def _oracle(n_elements: int, energy: float, eps: float, splits: int = 1) -> float:
    """The superseded implementation, verbatim, minus the one numpy line that read `eps` off the
    frame's dtype.

    Left unrefactored on purpose: its value is that it was written independently of the code it
    checks."""
    terms = 1 + 3 * max(1, int(splits))                    # the additions this verdict assembles
    elems = int(n_elements) * (1 + 2 * max(1, int(splits)))  # every product each ‖·‖² performed
    return eps * max(float(energy), 0.0) * float(terms + elems)


def _bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", float(x)))[0]


#: Machine epsilons a caller can actually hand over: float16, float32, float64, longdouble on this
#: box, and the two ends of the range so the sweep is not confined to the dtypes that exist today.
_EPSILONS = [2.0 ** -10, 2.0 ** -23, sys.float_info.epsilon, 2.0 ** -63, 1.0, 0.0, 1e-300]
_ELEMENTS = [0, 1, 2, 15, 256, 16384, 4194304]
_ENERGIES = [0.0, -0.0, -1.0, -1e12, 5e-324, 1e-12, 1.0, 3.7, 1e6, 1e18, 1e300,
             math.inf, -math.inf, math.nan]
_SPLITS = [-3, 0, 1, 2, 3, 7, 64, 1000]


def test_the_merged_law_agrees_with_the_deleted_implementation_on_every_input() -> None:
    """The sweep, kept as a test. Bit equality rather than `approx`, because comparing two
    tolerances with a tolerance would be the same defect one level up.

    Fails if the number moves in any corner of the input space — a negative energy, a zero split
    count, a float16 epsilon — where the two conservation verdicts riding on this bound would
    otherwise start disagreeing with the vectors that pin them."""
    n = 0
    disagreements = []
    for elems, energy, eps, splits in itertools.product(_ELEMENTS, _ENERGIES, _EPSILONS, _SPLITS):
        n += 1
        got = split_walk_rounding(elems, energy, eps, splits=splits)
        want = _oracle(elems, energy, eps, splits)
        same = (math.isnan(got) and math.isnan(want)) or _bits(got) == _bits(want)
        if not same:
            disagreements.append((elems, energy, eps, splits, got, want))
    assert n >= 5000, f"the sweep collapsed to {n} inputs and would prove almost nothing"
    assert not disagreements, (
        f"{len(disagreements)} of {n} inputs disagree with the deleted implementation; the first "
        f"five: {disagreements[:5]}")


def test_the_band_tracks_its_inputs_rather_than_being_a_constant_in_disguise() -> None:
    """The band moves with each of its three inputs, so it is a derivation rather than a constant
    behind a function signature. Checked as strict inequalities:

      more operations   → wider   (a longer walk earns more room, by exactly the extra additions)
      larger total      → wider   (a relative bound; proportionality is asserted rather than mere
                                   monotonicity, because that is what "ε·Σ·n" says)
      a coarser epsilon → wider   (float32 earns a wider band than float64, from its own dtype)
    """
    eps64, eps32 = sys.float_info.epsilon, 2.0 ** -23
    assert split_walk_rounding(256, 1.0, eps64, splits=1) < \
        split_walk_rounding(256, 1.0, eps64, splits=2), "more hops did not widen the band"
    assert split_walk_rounding(16, 1.0, eps64) < split_walk_rounding(4096, 1.0, eps64), \
        "a bigger frame did not widen the band"
    assert split_walk_rounding(256, 100.0, eps64) == pytest.approx(
        100.0 * split_walk_rounding(256, 1.0, eps64)), "the band is not proportional to the total"
    assert split_walk_rounding(256, 1.0, eps32) > split_walk_rounding(256, 1.0, eps64), \
        "a float32 epsilon did not earn a wider band than float64"


def test_a_negative_total_refuses_rather_than_granting_slack() -> None:
    """A negative total clamps the band to zero, so no difference is admitted as noise.

    The direction matters. An unclamped negative bound would read to `abs(defect) <= tol` as "admit
    nothing" only by accident of sign, and as a very wide band to a caller comparing signed. At
    zero, the caller's check fails where it should. NaN propagates for the same reason: it is not a
    band, and `abs(x) <= nan` is False."""
    assert accumulated_rounding(10, -1.0, sys.float_info.epsilon) == 0.0
    assert accumulated_rounding(10, -1e300, 1.0) == 0.0
    nan_band = accumulated_rounding(10, math.nan, 1.0)
    assert math.isnan(nan_band)
    assert not (abs(1.0) <= nan_band), "a NaN band admitted a real difference as noise"


def test_the_operation_count_is_counted_and_never_zero() -> None:
    """The count is exact rather than bounded — the caller knows how many hops it took — so it is
    asserted against the arithmetic it describes rather than against a remembered number.

    `splits` floors at 1 because a walk that split nothing still summed one frame's energy. A zero
    operation count would claim the arithmetic was exact, and floating point earns that claim
    nowhere."""
    for elems, splits in itertools.product([0, 1, 7, 4096], [1, 2, 9]):
        assert split_walk_operations(elems, splits=splits) == \
            (1 + 3 * splits) + elems * (1 + 2 * splits)
    # a walk with no split, and a nonsense split count, both floor at one hop's worth of arithmetic
    one = split_walk_operations(64, splits=1)
    assert split_walk_operations(64, splits=0) == one
    assert split_walk_operations(64, splits=-5) == one
    assert split_walk_operations(0, splits=1) == 4 and one > 0


def test_the_law_needs_nothing_but_stdlib() -> None:
    """The law sits on prism's dependency-free base so that a component running on numpy alone —
    mantle's beacon — can reach it. Behind an extra, such a component would install prism and still
    need its own copy.

    `test_contract_install_is_pure.py` holds the general floor with the packages blocked at the
    import system. This asserts the specific fact that makes the module placeable there: it reads no
    dtype, because reading a dtype's epsilon is numpy, and therefore the caller's job."""
    import ast
    import pathlib
    src = pathlib.Path(__import__("prism.rounding", fromlist=["x"]).__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom)}
    assert not (imported - {"__future__", ""}), (
        f"prism/rounding.py imports {sorted(imported)}; the law must stay stdlib-only or the "
        f"component that has only numpy goes back to keeping its own copy")


# ═════════════════════════════════════════════════════════════════════════════════════════════
# The reappearance guard — AST, not grep
# ═════════════════════════════════════════════════════════════════════════════════════════════

#: Every site in `src/prism` that touches a machine epsilon, with the error each one models.
#:
#: The annotation carries the weight here, not the membership. These are different bounds, and
#: merging them would be worse than leaving them apart, because a derivation can be exactly as wrong
#: as a constant when it models the wrong error. Adding an entry means naming the model:
#: accumulation, cancellation, rank or representation.
ALLOWED = {
    ("rounding.py", "accumulated_rounding"):
        "ACCUMULATION — THE LAW ITSELF, and the only place it may be written. `eps * total * n`, "
        "valid only because the terms summed are non-negative, which the module states at length.",
    ("conservation.py", "__init__"):
        "READ ONLY — reads the incident frame's dtype epsilon and stores it; the arithmetic is "
        "`tolerance`, which calls `rounding.accumulated_rounding`. Nothing is derived here.",
    ("frames.py", "offer_basis"):
        "RANK — `max(m, n) * eps * sigma_max`, LAPACK's and numpy's own `matrix_rank` tolerance. "
        "It bounds the REPRESENTATION of a zero singular value, not the drift of a sum; nothing "
        "accumulates, and merging it with the law would merge two different questions.",
    ("minting.py", "conservation_tolerance"):
        "ACCUMULATION *AND* CANCELLATION, which is why it is not the law: `(n + 2)` counts the "
        "naive sum, and `scale = max|inputs|` covers `verified_lift - actor_cost` subtracting two "
        "nearly-equal quantities. Sizing it off the residual instead would model the wrong error.",
    ("resolution.py", "_tie_break"):
        "CANCELLATION — `(v - mean)` subtracts nearly-equal quantities, so the error is set by the "
        "granularity of the INPUTS (`n * eps * max|v|`), not by the size of the deviation. This is "
        "the site where a term count was the WRONG model: 5 wrong cuts in 10,086 inputs.",
}

_EPS_NAMES = {"eps", "_eps", "epsilon", "_epsilon", "EPS", "EPSILON"}


def _enclosing(tree: ast.AST) -> dict:
    owner: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner.setdefault(line, node.name)
    return owner


def _mentions_epsilon(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in _EPS_NAMES:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _EPS_NAMES:
            return True
    return False


def _epsilon_sites(root: pathlib.Path) -> dict:
    """Two detectors over one tree, because a copy of the law can arrive either way:

      · a multiplication mentioning an epsilon anywhere inside it — what writing the law out looks
        like, whatever the local variable happens to be called;
      · a read of machine epsilon (`finfo(...).eps`, `float_info.epsilon`) — the point at which the
        value a hand-written law needs can enter this package.

    The extent of the guard: a copy that receives `eps` as a parameter under another name and is fed
    from an already-allowed read falls outside both detectors. The read sites are enumerated above,
    so such a copy still has to appear in a diff beside one of them."""
    found: dict = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _enclosing(tree)
        rel = str(path.relative_to(root)).replace("\\", "/")
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                hit = _mentions_epsilon(node)
            elif isinstance(node, ast.Attribute) and node.attr in ("eps", "epsilon"):
                hit = True
            if hit:
                found.setdefault((rel, owner.get(node.lineno, "<module>")), []).append(node.lineno)
    return found


def test_no_second_implementation_of_the_rounding_law_exists_in_prism() -> None:
    """The law appears once in `src/prism`, checked by AST rather than by text search.

    AST because several docstrings in this package discuss `ε · Σ · n`: a textual search matches the
    prose, and tuning it until it stops matching the prose leaves it guarding nothing.

    Fails when someone needs a noise band, prefers not to take the import, and writes
    `eps * total * n` locally. Such a copy agrees on the day it is written, and then one copy is
    repaired and the others are not."""
    sites = _epsilon_sites(SRC)
    unexpected = {k: v for k, v in sites.items() if k not in ALLOWED}
    assert not unexpected, (
        "an epsilon expression appeared outside the enumerated sites:\n"
        + "\n".join(f"  {f}:{ls} in {fn}()" for (f, fn), ls in sorted(unexpected.items()))
        + "\n\nIf it is the accumulation bound, call `prism.rounding` instead of writing it again. "
          "If it is a DIFFERENT bound, add it to ALLOWED with the error model it assumes.")
    assert set(ALLOWED) <= set(sites), (
        f"ALLOWED names sites that no longer exist: {sorted(set(ALLOWED) - set(sites))}. An "
        f"allow-list that has drifted from the tree stops being evidence about it.")


def test_the_guard_fires_on_a_seeded_copy(tmp_path: pathlib.Path) -> None:
    """The control: the scanner finds a verbatim copy of the law when one is planted.

    The guard above concludes from an absence, so its silence is only evidence once the scanner has
    been seen to speak."""
    (tmp_path / "sneaky.py").write_text(
        "def _float_noise(W, energy, splits=1):\n"
        "    eps = 2.220446049250313e-16\n"
        "    terms = 1 + 3 * max(1, int(splits))\n"
        "    elems = int(W.size) * (1 + 2 * max(1, int(splits)))\n"
        "    return eps * max(float(energy), 0.0) * float(terms + elems)\n",
        encoding="utf-8")
    sites = _epsilon_sites(tmp_path)
    assert ("sneaky.py", "_float_noise") in sites, (
        f"the scanner did not find a verbatim copy of the deleted law, so its silence on the real "
        f"tree means nothing. It saw: {sorted(sites)}")
