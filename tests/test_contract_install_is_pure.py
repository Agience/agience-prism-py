"""The base install is the contract, and it stays dependency-free.

A consumer that cannot import `prism` without also pulling fastapi vendors its own copy of what it
needs instead — and a content address decided in two places is decided twice. The rule therefore
holds in both directions:

  · keep the contract pure  ⇒  a bare consumer can import it  ⇒  one canonicaliser, not several
  · let one eager import in ⇒  fastapi lands on that consumer's install path ⇒ the copies come back

The contract is stdlib-only; everything else is an extra. `CONTRACT` below names the modules. They
are checked by source analysis first, then again in a subprocess with the extras made unimportable,
because source analysis cannot see an import that happens through `importlib`.

Both `instrument` and `embodiment` are on the list. `instrument` is where the protocols live;
`embodiment` is the alias crystal and chorus import, and an alias that reached for numpy would break
the bare install exactly as the original would.

`instrument` is the module this file most constrains, because it is the contract for the measurement
and so invites a measurement in it. It holds none: numpy and entroptics are unavailable on a bare
install, and a protocol that could compute would be an implementation.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

PRISM = pathlib.Path(__file__).resolve().parents[1] / "src" / "prism"

#: The modules a bare `pip install agience-prism-py` must be able to import.
#:
#: Most of these declare: canonical JSON, the crystal model, the capability grammar, the instrument
#: protocol. `resolution`, `adaptive_cut` and `rounding` derive — Otsu between-class variance against
#: a computed null, `1 − 1/|union|`, the floating-point rounding law, the env-var mode gate. The base
#: install therefore promises arithmetic as well as vocabulary.
#:
#: That promise is what lets every component hold the same answer, including the ones that must stay
#: self-contained. Behind an extra, a component could install prism and not get the one resolution;
#: a sha-verified source bundle that cannot require numpy would then keep its own copy of a
#: calculation that has no domain, and two copies of a calculation are two decision-makers.
#:
#: The floor is measured rather than asserted:
#: `test_the_derivations_import_with_numpy_blocked_too` runs the derivations in a subprocess with
#: `numpy` blocked as well, control first. `numpy` is not in `BLOCKED_IN_CONTRACT` because the rest
#: of the contract is not at risk of reaching for it.
CONTRACT = ["canonical", "capabilities", "crystal_model", "config", "errors", "structural",
            "environment", "instrument", "embodiment", "resolution", "adaptive_cut", "rounding"]

#: The derivations, named separately because they carry a stricter promise than the rest of the
#: contract: no numpy either, at import or through any name the module resolves eagerly. The
#: component that most needs `rounding` — mantle's beacon — runs on numpy and nothing else, so a
#: numpy-free floor is what makes that reach possible.
DERIVATIONS = ["resolution", "adaptive_cut", "rounding"]

#: Packages that must not be reachable at import time from the contract.
HEAVY = {"fastapi", "uvicorn", "httpx", "mcp", "jose", "jwt", "starlette", "pydantic"}

# ── The embodiment slot ──────────────────────────────────────────────────────────────────────────
# These are blocked for `prism.instrument` specifically rather than added to HEAVY: the rest of the
# contract is not at risk of reaching for them, and a blanket ban would be a rule with no cause to
# point at. Here the cause is exact — `instrument.py` describes what an instrument must do, and the
# implementations that fill the slot are numpy-and-entroptics. A protocol that imported either would
# stop being a protocol.
SLOT_ONLY_BLOCKED = {"numpy", "beam"}

# ── The publication boundary ─────────────────────────────────────────────────────────────────────
# `entroptics` is not in HEAVY — it is numpy-only. It is private, which is a different reason to keep
# it out. prism and mantle publish while entroptics does not, so a single import here would make the
# published SDK depend on a package a consumer cannot install.
#
# mantle enforces its own half: `entroptics` is in the FORBIDDEN set of
# `mantle/db/lattice/test_embeddable_surface.py`. This is prism's half, checked in both directions —
# the AST pass catches a module-scope import, and the subprocess blocker catches a lazy one by making
# the name unimportable while the contract runs.
PRIVATE = {"entroptics"}

BLOCKED_IN_CONTRACT = HEAVY | PRIVATE


def _eager_imports(path: pathlib.Path) -> set[str]:
    """Top-level (module-scope) imports only — an import inside a function is not an install cost."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {id(n) for n in tree.body}
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) not in top:
            continue
        if isinstance(node, ast.ImportFrom) and node.level:      # relative — intra-package
            continue
        mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""])
        out |= {m.split(".")[0] for m in mods if m}
    return out


@pytest.mark.parametrize("module", CONTRACT)
def test_contract_module_has_no_heavy_eager_import(module):
    found = _eager_imports(PRISM / f"{module}.py") & BLOCKED_IN_CONTRACT
    assert not found, (
        f"prism/{module}.py imports {sorted(found)} at module scope. The contract must be "
        f"importable on a dependency-free install — move it inside the function that needs it, or "
        f"the module out of the contract.")


def test_package_init_does_not_eagerly_import_a_runtime_surface():
    """The package init is the one file that can break the install on its own.

    Importing any submodule runs `__init__.py` first, so a single eager `from .trust import …` here
    makes every one of the tests above irrelevant: `import prism.canonical` would still pull jose."""
    eager = _eager_imports(PRISM / "__init__.py")
    assert not (eager & HEAVY), f"prism/__init__.py eagerly imports {sorted(eager & HEAVY)}"

    tree = ast.parse((PRISM / "__init__.py").read_text(encoding="utf-8"))
    relative = {n.module for n in tree.body
                if isinstance(n, ast.ImportFrom) and n.level and n.module}
    relative |= {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    forbidden = relative & {"trust", "host", "server"}
    assert not forbidden, (
        f"prism/__init__.py eagerly imports {sorted(forbidden)}. These are EXTRAS — reach them "
        f"through the `__getattr__` lazy table so the base install stays dependency-free.")


def test_the_contract_imports_in_a_subprocess_with_the_heavy_packages_blocked():
    """Imports the contract for real, with every extra made unimportable.

    The checks above read source. Source analysis cannot see an import that happens through
    `importlib`, a `__getattr__` that fires on module load, or a transitive pull from a sibling.
    This blocks each heavy package outright — a `meta_path` finder that raises for them — and then
    imports the contract. If anything reaches for fastapi, this fails with a traceback pointing at
    the line that did.

    Runs in a subprocess because the packages are installed in this environment: blocking them in
    the current interpreter would not survive the modules already in `sys.modules`."""
    program = f"""
import sys

BLOCKED = {sorted(BLOCKED_IN_CONTRACT)!r}

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError(
                'BLOCKED BY THE TEST: the contract reached for %r, which is an extra' % name)
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in BLOCKED:
        del sys.modules[m]

import prism
from prism.canonical import canonical_string
from prism.crystal_model import *          # noqa: F401,F403
from prism import Prism, Capability, PrismError
from prism.instrument import Instrument, Conservation, require, InstrumentRequired

assert canonical_string({{'b': 1, 'a': 2}}) == '{{"a":2,"b":1}}', 'canonical JSON is wrong'
try:
    require(None, 'absorb_transmit', contract='embodiment', at='the check')
except InstrumentRequired:
    pass
else:
    raise AssertionError('the empty slot did not refuse')
print('CONTRACT OK')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "CONTRACT OK" in r.stdout, (
        "the contract could not be imported with the extras blocked:\n"
        + (r.stderr or r.stdout)[-2500:])


def test_the_derivations_import_with_numpy_blocked_too():
    """The derivations are in `CONTRACT` on the strength of a measurement, and this is it.

    `numpy`, `entroptics` and `scipy` are blocked at the meta-path, the modules are imported for
    real, and their public surface is then exercised — an import that resolves nothing proves only
    that the file parses. The control runs first: a `meta_path` finder that silently does not fire
    would report a numpy-dependent module as stdlib-floored.

    `adaptive_cut.is_available()` answers False here rather than raising. Its contract with the
    serve path is "no instrument → defer to the caller's baseline", so a host that cannot measure
    says so on the way to that answer."""
    program = """
import sys

BLOCKED = ('numpy', 'entroptics', 'scipy')

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError('BLOCKED BY THE TEST: %r' % name)
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in BLOCKED:
        del sys.modules[m]

for probe in BLOCKED:                       # the control — the blocker must bite first
    try:
        __import__(probe)
    except ImportError:
        pass
    else:
        print('CONTROL-FAILED', probe)
        raise SystemExit(2)

from prism.resolution import signal_end, partition, separated, exact_limit, estimator_limit
from prism import adaptive_cut
from prism.rounding import accumulated_rounding, split_walk_operations, split_walk_rounding

# The rounding law, exercised with numpy gone. This is the module mantle's beacon reaches for on a
# numpy-only install, and an import that resolves nothing would prove only that the file parses.
assert accumulated_rounding(3, 2.0, 0.5) == 3.0, 'the law is not eps * total * n'
assert accumulated_rounding(3, -2.0, 0.5) == 0.0, 'a negative total granted slack'
assert split_walk_operations(4, splits=1) == 16, 'the operation count moved'
assert split_walk_rounding(4, 1.0, 1.0, splits=1) == 16.0
assert split_walk_rounding(4, 1.0, 2.0 ** -23) > split_walk_rounding(4, 1.0, 2.0 ** -52), \\
    'a coarser epsilon did not earn a wider band'

assert signal_end([10.0, 9.0, 8.0, 1.0, 0.9]) == 3, 'the Otsu split did not find the cliff'
assert signal_end([5.0] * 50) == 50, 'a flat series was cut'
assert not separated([5.1, 5.0, 4.9, 4.8]), 'a featureless ramp read as structure'
assert abs(exact_limit(20) - 0.95) < 1e-12
assert abs(estimator_limit(99) - 0.99) < 1e-12
assert partition([9.0] * 20 + [0.5] * 20)[0] == 20

assert adaptive_cut.mode() == 'on'          # the default INTENT; the three below are why
                                            # intent cannot produce a cut without an instrument
assert adaptive_cut.is_available() is False, 'claimed an instrument with numpy unimportable'
assert adaptive_cut.cut([-3.0, -2.0, -1.0]) is None, 'guessed a cut with no instrument'
assert adaptive_cut.cut([-1.0]) == 1
adaptive_cut.record_shadow('q', [-1.0, -2.0], 1, None)     # no sink set: silent, never raises
print('DERIVATIONS OK')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "CONTROL-FAILED" not in r.stdout, (
        "the blocker did not bite, so this test proves nothing:\n" + r.stdout)
    assert "DERIVATIONS OK" in r.stdout, (
        "prism's DERIVATIONS did not run on a bare stdlib base. They are in `CONTRACT` on exactly "
        "that measurement, so this is the dependency-free base install acquiring a dependency:\n"
        + (r.stderr or r.stdout)[-2500:])


@pytest.mark.parametrize("module", DERIVATIONS)
def test_a_derivation_never_imports_the_aperture(module):
    """A derivation reaches `resolvable` through the injected contract, never by importing L3.

    The short way to reach `resolvable` from prism is a direct import of the optics package, which
    would put a private, numpy-and-entroptics package on the published SDK's runtime path and point
    L1 at L3. The derivations resolve `instrument.require(..., contract='read')` instead — the same
    door `frames.absorb_at_tekton` uses.

    The name may not appear anywhere in the file, at module scope or inside a function, which is why
    this reads the whole tree rather than the module body."""
    tree = ast.parse((PRISM / f"{module}.py").read_text(encoding="utf-8"))
    named = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            named.add(node.module.split(".")[0])
    assert "beam" not in named, (
        f"prism/{module}.py imports `beam`. prism is L1 and publishes; beam is L3 and carries "
        f"entroptics, which is private. The aperture reach goes through `instrument.require(..., "
        f"contract='read')`, the same door `frames.absorb_at_tekton` uses.")


def test_the_instrument_contract_holds_no_implementation():
    """`prism.instrument` imports, and reports its empty slots, with numpy and the optics packages
    blocked.

    It is the contract for the measurement, so the way it fails is by quietly becoming an
    implementation: one `import numpy` for a default, one direct optics import for a fallback, and
    the base install has a dependency again.

    The blocker is proven to bite by importing a module that does reach for numpy (`prism.vector`)
    under the same finder and asserting it fails. Without that control, a blocker that matched
    nothing would report success for every module in the package.
    """
    program = f"""
import sys

BLOCKED = {sorted(SLOT_ONLY_BLOCKED | PRIVATE)!r}

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError('BLOCKED BY THE TEST: %r is not on a bare install' % name)
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in BLOCKED:
        del sys.modules[m]

# ── The control: the blocker must actually bite. `prism.vector` calls numpy.linalg.norm. ──
try:
    import prism.vector
except ImportError:
    pass
else:
    raise AssertionError(
        'the blocker did not fire on prism.vector, which imports numpy — every result below '
        'would be vacuous')

# ── The measurement ──
import prism.instrument as E

# it describes, and it reports what it lacks; the arithmetic lives in the host
assert E.INSTRUMENT_MEMBERS == ('absorb_transmit', 'next_by_coupling', 'membrane_screen')
assert E.READ_MEMBERS == ('correlated_null', 'read_ordered', 'resolvable', 'scales',
                          'accumulator', 'accumulated_read', 'screen_normalize')
assert E.DYNAMICS_MEMBERS == ('decay_profile', 'resolution_limit', 'embed', 'fit_dynamics',
                              'dynamics_state')
assert E.CONSERVATION_MEMBERS == ('energy', 'PathLedger', 'entropy_bits', 'joint_entropies')
assert E.members_of(None, 'embodiment') == ()
assert E.members_of(None, 'read') == ()
assert E.members_of(None, 'dynamics') == ()
assert E.members_of(None, 'conservation') == ()

class _Half:
    def absorb_transmit(self, rows, **kw): return None

assert E.members_of(_Half(), 'embodiment') == ('absorb_transmit',)
E.require(_Half(), 'absorb_transmit', contract='embodiment', at='x')
for slot, contract, member in (
        (None, 'conservation', 'energy'),
        (None, 'conservation', 'entropy_bits'),
        (None, 'read', 'read_ordered'),
        (None, 'dynamics', 'fit_dynamics'),
        (_Half(), 'embodiment', 'membrane_screen'),
        (_Half(), 'embodiment', 'next_by_coupling'),
        (_Half(), 'read', 'resolvable'),
        (_Half(), 'dynamics', 'decay_profile')):
    try:
        E.require(slot, member, contract=contract, at='x')
    except E.InstrumentRequired as exc:
        assert exc.member == member, (exc.member, member)
        assert exc.contract == contract, (exc.contract, contract)
    else:
        raise AssertionError('an unfilled member did not refuse: %s.%s' % (contract, member))

# ── The contract must name every member the wire calls ──
# `isinstance` against a runtime_checkable Protocol checks member presence, so an instrument that
# fills only the enumerated members conforms — and then raises at the first call to a member the
# wire makes but the contract omits. `require()` reports an absence for any member the slot lacks,
# declared or not, so a runtime test sees the right answer and misses the gap. These two lines are
# where it is visible.
class _PreD5:
    def absorb_transmit(self, rows, **kw): return None
    def membrane_screen(self): return object

class _Whole(_PreD5):
    def next_by_coupling(self, rows, bases, **kw): return None

assert not isinstance(_PreD5(), E.Instrument), (
    'an instrument filling only the pre-D5 member set is still accepted as an Instrument — the '
    'contract must NAME every member the wire calls, or conformance means nothing')
assert isinstance(_Whole(), E.Instrument)
assert E.members_of(_Whole(), 'embodiment') == E.INSTRUMENT_MEMBERS

# ── `Instrument` is the propagation surface, and stays three members wide ──
# The read and dynamics measurements live in their own contracts rather than on this one. A
# 14-member `Instrument` is one no beacon could satisfy — mantle's domain is a set of vectors, and
# several of those measurements need a lag. `_Whole` fills exactly the propagation surface and is a
# complete `Instrument`; appending a read or a dynamics member here fails these lines rather than
# silently turning crystal's stub non-conforming.
assert isinstance(_Whole(), E.Instrument) and not isinstance(_Whole(), E.Read), (
    'the propagation surface alone must be a complete Instrument and NOT a Read — if it is both, '
    'the two contracts do not describe different things')
assert not isinstance(_Whole(), E.Dynamics)
assert len(E.INSTRUMENT_MEMBERS) == 3, (
    'Instrument grew. Every member here is a member D6 must build into beacon, and beacon can only '
    'ever fill this contract if it stays the propagation surface')

# ── `Conservation` spans two real deployments, and names all four members ──
# The arithmetic is split: `prism.conservation` has numpy and no entroptics, `ember.optics` has
# entroptics and no ledger. Both are real hosts, so both must read as partial rather than as
# conforming, and the result must say which name is missing. Asserted in both directions, so that
# neither a removal of a member nor a widening back to two passes silently.
class _Accountant:                          # the shape `prism.conservation` has: numpy, no entroptics
    def energy(self, frame): return 0.0
    def PathLedger(self, incident, **kw): return None

class _EntropyOnly:                         # the shape `ember.optics` has: entroptics, no ledger
    def entropy_bits(self, weights): return 0.0
    def joint_entropies(self, fx, fy, mx=None, my=None): return {{}}

class _WholeAccountant(_Accountant, _EntropyOnly):
    pass

assert E.members_of(_Accountant(), 'conservation') == ('energy', 'PathLedger'), (
    'a numpy-only accountant must report exactly what it fills — members_of is the MEASURED extent')
assert E.members_of(_EntropyOnly(), 'conservation') == ('entropy_bits', 'joint_entropies')
assert E.members_of(_WholeAccountant(), 'conservation') == E.CONSERVATION_MEMBERS
assert not isinstance(_Accountant(), E.Conservation), (
    'an accountant filling only energy + PathLedger is still accepted as a Conservation — the '
    'contract must NAME every member a consumer calls, or conformance means nothing. This is the '
    'next_by_coupling defect, and it is what `entropy_bits` was declared to close.')
assert not isinstance(_EntropyOnly(), E.Conservation)
assert isinstance(_WholeAccountant(), E.Conservation)
assert len(E.CONSERVATION_MEMBERS) == 4, (
    'Conservation moved. Membership here is a DEPENDENCY fact — the arithmetic lives somewhere '
    "prism's base install cannot reach — never a divergence one; a name added for any other reason "
    'belongs on Instrument, Read or Dynamics.')

# The result names the missing member, as well as the contract. A partial accountant is a real
# deployment (numpy without entroptics), so what it cannot do is legible from outside.
try:
    E.require(_Accountant(), 'entropy_bits', contract='conservation', at='the check')
except E.InstrumentRequired as exc:
    assert exc.member == 'entropy_bits' and exc.contract == 'conservation'
    assert 'energy' in str(exc) and 'PathLedger' in str(exc), (
        'a partial accountant must be told what it DOES fill, or an operator cannot tell a '
        'constrained host from an unwired one: %s' % exc)
    assert exc.http_status == 503
else:
    raise AssertionError('a numpy-only accountant computed an entroptics-floored entropy')
# …and the two members it does fill still resolve, so the host runs everything it can measure.
E.require(_Accountant(), 'energy', contract='conservation', at='the check')
E.require(_Accountant(), 'PathLedger', contract='conservation', at='the check')

# ── The four contracts are disjoint ──
# They are separate contracts because no consumer function reaches two families. A name appearing in
# two tuples would make `require(slot, m, contract=…)` answer differently for the same member
# depending on which contract the caller named — a contract that disagrees with itself about where a
# member lives.
_all_members = [m for _c, ms in sorted((k, v[1]) for k, v in E._CONTRACTS.items()) for m in ms]
assert len(_all_members) == len(set(_all_members)), (
    'a member is enumerated in two contracts: %r' % sorted(
        m for m in set(_all_members) if _all_members.count(m) > 1))

# ── Every contract is reachable and nameable ──
# `require()` on an empty slot quotes `_FILLED_BY[contract]`. A contract added without an entry
# there raises `KeyError` on the way to reporting the absence, so an unfilled slot arrives as a
# crash instead of as `InstrumentRequired`.
assert set(E._FILLED_BY) == set(E._CONTRACTS), (
    'a contract has no stated filler: %r' % sorted(set(E._CONTRACTS) ^ set(E._FILLED_BY)))
for _c in sorted(E._CONTRACTS):
    try:
        E.require(None, E._CONTRACTS[_c][1][0], contract=_c, at='x')
    except E.InstrumentRequired as exc:
        assert E._FILLED_BY[_c] in str(exc), (_c, str(exc))
    else:
        raise AssertionError('an empty %s slot did not refuse' % _c)

# ── The companion object models are in no tuple ──
# `Screen`/`Ledger`/`SpectralRead`/`Accumulator`/`Propagator`/`DiffractionLimit` describe what a
# member returns. Enumerating one would make `require()` demand a slot fill a name no caller reaches
# for, and `members_of` report a complete embodiment as partial.
for _companion in ('Screen', 'Ledger', 'SpectralRead', 'Accumulator', 'Propagator',
                   'DiffractionLimit'):
    assert _companion not in _all_members, (
        '%s is an object model, not a member — it is returned, never called on the slot'
        % _companion)

print('SLOT OK')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "SLOT OK" in r.stdout, (
        "the embodiment contract could not be imported with numpy/beam/entroptics blocked:\n"
        + (r.stderr or r.stdout)[-2500:])


def test_the_instrument_contract_declares_and_never_computes():
    """Every Protocol member is a declaration — a docstring and nothing else.

    A helpful default is the seam this closes: a `return 0.0` where a measurement belongs reads as
    working code and is a fabricated reading. Checked by AST over the function bodies, so it holds
    for a member added later by someone who never read this file.

    The declared members are also checked to be the enumerated ones. The member tuples are what
    `members_of()` reports and what `require()` checks against, and they are typed separately from
    the `class` a few lines above them, so the two can drift in either direction without raising: a
    member declared but not enumerated is invisible to `members_of` (a filled member reported as
    unfilled), and a member enumerated but not declared is `isinstance`-invisible (an implementation
    that conforms and then fails). The tuple is therefore derived-checked against the class.

    Every `Protocol` in the file is swept rather than a hand-written list, so a protocol added later
    — with a `return 0.0` in it — is looked at too. The protocols are discovered from the bases
    (`Protocol` in the class's base list) and the hand-written set is asserted to be a subset of
    what was found, which is the control: if discovery matches nothing, the four contracts go
    missing and the assertion fires."""
    src = (PRISM / "instrument.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _is_protocol(cls: ast.ClassDef) -> bool:
        return any((isinstance(b, ast.Name) and b.id == "Protocol")
                   or (isinstance(b, ast.Attribute) and b.attr == "Protocol")
                   for b in cls.bases)

    contracts = {"Instrument", "Read", "Dynamics", "Conservation"}
    companions = {"Ledger", "Screen", "SpectralRead", "Accumulator", "Propagator",
                  "DiffractionLimit"}
    seen = set()
    declared: dict[str, set[str]] = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and _is_protocol(n)]:
        seen.add(cls.name)
        declared[cls.name] = set()
        for fn in [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            declared[cls.name].add(fn.name)
            body = [s for s in fn.body if not (isinstance(s, ast.Expr)
                                               and isinstance(s.value, ast.Constant)
                                               and isinstance(s.value.value, str))]
            assert all(isinstance(s, (ast.Pass, ast.Expr)) and not isinstance(s, ast.Return)
                       for s in body), (
                f"{cls.name}.{fn.name} has a body. A protocol member that computes is an "
                f"implementation, and an implementation here is a dependency.")
    # The control: discovery must find at least the ten protocols known to be here. A matcher that
    # matched nothing would report every module in the file clean.
    assert (contracts | companions) <= seen, (
        f"protocol discovery lost a declared protocol: {sorted((contracts | companions) - seen)}")

    from prism.instrument import _CONTRACTS  # noqa: PLC2701 — the tuples are the contract's data

    assert set(_CONTRACTS) == {"embodiment", "read", "dynamics", "conservation"}
    for key, (proto, members) in sorted(_CONTRACTS.items()):
        cls_name = proto.__name__
        assert cls_name in contracts, f"{cls_name} is registered as a contract but not named one"
        # A `@property` is a declaration too (`Screen.placed`), so compare on names, not on order:
        # the tuple's order is "the order a consumer reaches for them" and is deliberately free of
        # the order the class happens to be written in.
        assert declared[cls_name] == set(members), (
            f"{cls_name} declares {sorted(declared[cls_name])} but the contract enumerates "
            f"{sorted(members)}. A member in one and not the other is a contract that disagrees "
            f"with itself: `members_of`/`require` read the tuple, `isinstance` reads the class.")
        assert len(set(members)) == len(members), f"{cls_name} enumerates a member twice"

    # Every protocol is either a contract or an object model. A protocol that is neither is a
    # declaration nobody can inject and nobody can be handed — dead surface in the one file whose
    # job is to say exactly what a host must supply.
    assert seen == contracts | companions, (
        f"an undeclared protocol appeared: {sorted(seen - contracts - companions)}. Register it in "
        f"`_CONTRACTS` if a host fills it, or say in its docstring which member RETURNS it.")

    # An object model is never a contract: `require()` would demand a slot fill a name that is only
    # ever a return value.
    registered = {p.__name__ for p, _m in _CONTRACTS.values()}
    assert not (registered & companions), (
        f"an object model is registered as an injectable contract: {sorted(registered & companions)}")


def test_the_retired_spellings_are_bindings_and_never_a_second_declaration():
    """`prism/embodiment.py` binds the retired spellings; it never re-declares them.

    It is an alias module for crystal and chorus. The way an alias module goes wrong is not that it
    stops working — it is that someone writes `class Embodiment(Protocol): ...` in it so the old
    name keeps its own docs, and from that moment two Protocol objects exist with two member sets.
    `isinstance(stub, Embodiment)` in crystal's suite and `isinstance(stub, Instrument)` in prism's
    would then answer questions about different contracts while reading identically, and a member
    added to one would not appear in the other.

    Compared with `is`, not `==`: two Protocol classes with the same members compare unequal but
    would both pass an `isinstance` test written against either, so equality of the member tuples
    would not catch the fork. Identity does.

    The control: `_RETIRED` is asserted non-empty and every entry is asserted to name a real
    attribute of `prism.instrument`. A shim that had lost its table would otherwise iterate nothing
    and pass.
    """
    import prism.embodiment as old
    import prism.instrument as new

    assert old._RETIRED, "the alias table is empty — this test would prove nothing"
    for retired, current in sorted(old._RETIRED.items()):
        assert hasattr(new, current), (
            f"`prism.embodiment` maps {retired} onto {current}, which `prism.instrument` does not "
            f"have. The alias points at nothing.")
        assert getattr(old, retired) is getattr(new, current), (
            f"prism.embodiment.{retired} is not prism.instrument.{current} — the shim RE-DECLARED "
            f"it instead of binding it, so there are now two of whatever it describes.")

    # The module is a bridge, not a surface: it may forward names and it may retire names, but it
    # holds none of its own. A name here that `prism.instrument` has never heard of is a name that
    # would be lost with the file.
    forwarded = {n for n in old.__all__ if n not in old._RETIRED}
    unknown = {n for n in forwarded if not hasattr(new, n)}
    assert not unknown, (
        f"`prism.embodiment` exports {sorted(unknown)}, which does not exist in "
        f"`prism.instrument`. The alias has grown a surface of its own and can no longer be "
        f"deleted with the lane that retires it.")

    # `prism.instrument` holds both halves — the declaration and the registry — so that one file
    # answers both what an instrument is and where to get one.
    for half in ("Instrument", "Read", "Dynamics", "Conservation", "require", "members_of",
                 "set_default", "get_default", "clear_default", "resolve"):
        assert hasattr(new, half), f"prism.instrument lost {half} in the fold"


def test_asking_for_a_runtime_surface_without_its_extra_says_which_extra():
    """The lazy loader fails with an instruction, not `No module named 'fastapi'`.

    Exercised through the loader itself rather than by matching a string, so the message and the
    mechanism that produces it are both pinned."""
    program = """
import sys

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('fastapi', 'starlette'):
            raise ImportError('blocked')
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in ('fastapi', 'starlette'):
        del sys.modules[m]

import prism                      # must succeed: the contract does not need fastapi
try:
    prism.Host                     # must fail, and say how to fix it
except ImportError as e:
    assert 'agience-prism[host]' in str(e), 'the error does not name the extra: %s' % e
    print('MESSAGE OK')
else:
    print('NO ERROR RAISED')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "MESSAGE OK" in r.stdout, (r.stderr or r.stdout)[-2000:]


def test_the_declared_extras_cover_every_runtime_surface():
    """A surface with no extra is one nobody can install. Reads the manifest, not a memorised list."""
    try:
        import tomllib
    except ModuleNotFoundError:                                  # pragma: no cover
        import tomli as tomllib                                  # type: ignore[no-redef]
    pyproject = tomllib.loads(
        (PRISM.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [], (
        "the base install grew a dependency — that is the whole thing this file exists to prevent")
    extras = pyproject["project"]["optional-dependencies"]
    for surface in ("trust", "host", "server"):
        assert surface in extras, f"prism.{surface} has no `{surface}` extra to install it with"
        assert extras[surface], f"the `{surface}` extra is empty"
