"""The wire is an extra; the base install is still the contract.

Sixteen modules make up the wire — reach · plane · streams · carriers · frames · propagation ·
mcp_bridge · schema · demurrage · minting · settlement · pump · minhash · error_threshold ·
extraction · conservation. The aperture is not among them: it needs entroptics, which is private and
cannot ship in a published SDK. `resolution` and `adaptive_cut` are not among them either — they
need neither numpy nor cryptography, so they sit in the dependency-free base, and
`tests/test_contract_install_is_pure.py` owns their floor.

Four properties are pinned here.

  1. **The base install has no dependencies.** `numpy` and `cryptography` are real dependencies of
     part of the wire, and the short way to make sixteen modules work is two lines in
     `[project.dependencies]`. `tests/test_contract_install_is_pure.py` owns the base assertion;
     this file adds the wire's half.

  2. **The wire does not drag the aperture.** `frames` and `reach` each take exactly one measurement
     through the aperture, and the short way to keep them working is a direct import — which would
     invert the DAG and put a private, numpy-and-entroptics package on the published SDK's install
     path. `test_the_wire_imports_with_the_aperture_unimportable` makes the aperture unimportable
     and imports the whole wire anyway.

  3. **The stdlib majority stays stdlib.** Nine of the sixteen import on a bare base install. An
     `import numpy` added to the top of `carriers.py` would be invisible in this environment, where
     numpy is installed, and would surface as an edge node that cannot install.
     `test_the_stdlib_only_wire_modules_need_no_extra` blocks numpy and cryptography and imports
     those nine for real.

  4. **The blockers bite.** Every subprocess check here rests on the `meta_path` finder firing, and
     a blocker that never bites reports success for everything. Each check runs a control first that
     imports a module known to reach for the blocked package and asserts it fails.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

PY = pathlib.Path(__file__).resolve().parents[1]

#: The wire, named as data so a module dropped from one of the lists below is caught here.
WIRE = ["reach", "plane", "streams", "carriers", "frames", "propagation", "mcp_bridge", "schema",
        "demurrage", "minting", "settlement", "pump", "minhash", "error_threshold", "extraction",
        "conservation"]

#: The wire modules that import on a bare base install, with no extra at all. Measured by AST over
#: module-scope imports, resolved transitively through `prism.law` and `prism.plane`, and re-checked
#: at runtime by `test_the_stdlib_only_wire_modules_need_no_extra`.
STDLIB_ONLY = ["carriers", "pump", "minhash", "minting", "settlement", "extraction", "schema",
               "error_threshold", "mcp_bridge"]

#: The rest, with the floor each one has. `propagation` and `demurrage` need numpy only transitively,
#: through `prism.law`, which is why they are listed here rather than inferred from their own import
#: lines.
NEEDS_NUMPY = ["frames", "conservation", "propagation", "demurrage"]
NEEDS_CRYPTOGRAPHY = ["plane", "streams", "reach"]


def _blocked_run(blocked, body: str) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter with `blocked` made unimportable by a `meta_path` finder.

    Runs in a subprocess because the packages are installed in this environment: blocking them here
    would not survive what is already in `sys.modules`. `sys.path` is handed over in-band so this
    works from a bare `pytest` with no PYTHONPATH exported.
    """
    prelude = f"""
import sys, json
sys.path[:0] = {sys.path!r}

BLOCKED = {sorted(blocked)!r}

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
"""
    return subprocess.run([sys.executable, "-c", prelude + body],
                          capture_output=True, text=True, cwd=str(PY), timeout=300)


# ── 1 · The manifest ─────────────────────────────────────────────────────────────────────────────

def _pyproject() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:                                  # pragma: no cover
        import tomli as tomllib                                  # type: ignore[no-redef]
    return tomllib.loads((PY / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_base_install_still_has_no_dependencies():
    """Sixteen wire modules exist, four needing numpy and three cryptography; the base declares none
    of them."""
    assert _pyproject()["project"]["dependencies"] == [], (
        "the wire landed in the BASE install. It belongs in the `wire` extra — the contract is what "
        "`agience-beam` and `agience-bundle` stopped vendoring `canonical.py` because of.")


def test_the_wire_extra_exists_and_names_exactly_what_the_wire_imports():
    """The extra names what the modules import, checked against the measured floors above."""
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "wire" in extras, "the wire has no extra, so nobody can install it"
    names = {req.split(">")[0].split("[")[0].split("=")[0].strip() for req in extras["wire"]}
    assert names == {"numpy", "cryptography"}, (
        "the `wire` extra declares %s. Measured, the wire needs exactly numpy (frames, conservation, "
        "and propagation/demurrage through prism.law) and cryptography (plane, and streams/reach "
        "through it) — nothing else, and nothing less." % sorted(names))
    assert "wire" in extras["all"][0], "`all` does not include the wire"


# ── 2 · The wire does not drag the aperture ──────────────────────────────────────────────────────

def test_the_wire_imports_with_the_aperture_unimportable():
    """The whole wire imports with the aperture packages made unimportable.

    That includes `frames` and `reach`, the two modules that take a measurement through the
    aperture. They reach it through the injected instrument contract, so blocking the aperture
    changes nothing about whether they import.

    The control runs first: the aperture module is imported under the same finder and must fail.
    Without it, a finder that matched nothing would report every module below as aperture-free.
    """
    body = f"""
# ── The control: the blocker must actually bite. ──
try:
    import beam.optics
except ImportError:
    pass
else:
    raise AssertionError(
        'the blocker did not fire on `beam.optics` — every result below would be vacuous')

# ── The measurement: the whole wire, with the aperture unreachable. ──
import importlib
for m in {WIRE!r}:
    importlib.import_module('prism.' + m)

# and the two straddling modules report no reading rather than reaching for what is not there
import numpy as np
from prism.frames import absorb_at_tekton, encode_frame, decode_frame
from prism.instrument import InstrumentRequired
from prism import instrument

instrument.clear_default()
W = np.arange(24, dtype=float).reshape(6, 4)

# encoding is the wire, and works with no instrument at all
assert np.array_equal(decode_frame(encode_frame(W)), W), 'the frame did not round-trip'

try:
    absorb_at_tekton(W)
except InstrumentRequired as e:
    assert e.member == 'absorb_transmit', e.member
    assert e.http_status == 503
else:
    raise AssertionError(
        'absorb_at_tekton returned a value with NO instrument injected. An unmeasured split must '
        'refuse, never degrade to a zero split or a None that reads as "nothing coupled".')

print('WIRE OK')
"""
    r = _blocked_run({"entroptics", "beam"}, body)
    assert "WIRE OK" in r.stdout, (
        "the wire could not be imported with the aperture blocked:\n" + (r.stderr or r.stdout)[-3000:])


# ── 3 · Nine of the sixteen need no extra at all ─────────────────────────────────────────────────

def test_the_stdlib_only_wire_modules_need_no_extra():
    """A bare `pip install agience-prism-py` carries two thirds of the wire.

    Checked by blocking numpy and cryptography together and importing the nine for real, with a
    control on each blocked package."""
    body = f"""
# ── The controls, one per blocked package, because a finder can match one name and miss another. ──
for probe in ('prism.vector', 'prism.plane'):
    try:
        __import__(probe)
    except ImportError:
        pass
    else:
        raise AssertionError(
            'the blocker did not fire on %s — the result below would be vacuous' % probe)

import importlib
for m in {STDLIB_ONLY!r}:
    importlib.import_module('prism.' + m)

# they are not merely importable — the pure-stdlib wire works
from prism.carriers import InMemoryCarrier, _leaf_order
c = InMemoryCarrier()
c.put({{'id': 'b', 'hlc': '2'}})
c.put({{'id': 'a', 'hlc': '1'}})
c.put({{'id': 'b', 'hlc': '2'}})                       # content-addressed -> idempotent
assert [l['id'] for l in c.poll()] == ['b', 'a'], 'the append-only log lost its order'
assert c.ids() == {{'a', 'b'}}
assert sorted([{{'id': 'b', 'hlc': '2'}}, {{'id': 'a', 'hlc': '1'}}], key=_leaf_order) \\
    == [{{'id': 'a', 'hlc': '1'}}, {{'id': 'b', 'hlc': '2'}}], 'the cross-language order broke'
from prism.minhash import _band_bytes
assert isinstance(_band_bytes((1, 2)), bytes)

print('STDLIB WIRE OK')
"""
    r = _blocked_run({"numpy", "cryptography"}, body)
    assert "STDLIB WIRE OK" in r.stdout, (
        "a wire module that must import on the bare base install reached for numpy or "
        "cryptography:\n" + (r.stderr or r.stdout)[-3000:])


@pytest.mark.parametrize("module", NEEDS_NUMPY + NEEDS_CRYPTOGRAPHY)
def test_every_wire_module_is_classified_and_the_classification_is_true(module):
    """A module classified as needing numpy or cryptography fails when that package is blocked.

    This is the direction that keeps the lists above a measurement. Without it, moving a module from
    `STDLIB_ONLY` into `NEEDS_NUMPY` would weaken the check above unnoticed, and the classification
    would drift into whatever made the suite green.
    """
    blocked = {"numpy"} if module in NEEDS_NUMPY else {"cryptography"}
    r = _blocked_run(blocked, "import prism.%s\nprint('IMPORTED')\n" % module)
    assert "IMPORTED" not in r.stdout, (
        "`prism.%s` is classified as needing %s, and it imported without it. Either the "
        "dependency is gone — move it to STDLIB_ONLY and the `wire` extra shrinks — or the "
        "blocker is not reaching it." % (module, sorted(blocked)[0]))


def test_the_classification_covers_the_whole_wire():
    """A module in neither list is a module nobody measured."""
    classified = set(STDLIB_ONLY) | set(NEEDS_NUMPY) | set(NEEDS_CRYPTOGRAPHY)
    assert classified == set(WIRE), (
        "unclassified wire modules: %s; classified but not in the wire: %s"
        % (sorted(set(WIRE) - classified), sorted(classified - set(WIRE))))


# ── 4 · The instrument slot ──────────────────────────────────────────────────────────────────────

def test_the_instrument_slot_prefers_the_call_over_the_process_default():
    """The `embodiment=` keyword wins over the process default.

    A process default is a convenience for a node that registers one instrument at startup; the
    keyword is how a caller that knows better says so, so the keyword takes precedence."""
    from prism import instrument

    class _A:
        def absorb_transmit(self, rows, **kw):
            return "A"

    class _B:
        def absorb_transmit(self, rows, **kw):
            return "B"

    try:
        instrument.set_default(_A())
        assert instrument.resolve(None, "absorb_transmit", at="t")(None) == "A"
        assert instrument.resolve(_B(), "absorb_transmit", at="t")(None) == "B"
    finally:
        instrument.clear_default()


def test_an_empty_slot_refuses_and_names_what_it_could_not_do():
    """An empty slot has no reading to give, and says which member and which operation.

    That is what lets a caller discriminate "this host cannot measure" from "nothing coupled"."""
    from prism import instrument
    from prism.instrument import InstrumentRequired

    instrument.clear_default()
    with pytest.raises(InstrumentRequired) as e:
        instrument.resolve(None, "absorb_transmit", at="absorb_at_tekton")
    assert e.value.member == "absorb_transmit"
    assert e.value.at == "absorb_at_tekton"
    assert e.value.http_status == 503


def test_a_partly_filled_instrument_refuses_only_what_it_lacks():
    """A constrained host runs what it can. `require()` is checked per member, so an instrument that
    splits frames but cannot route does the first and has no reading for the second, by name."""
    from prism import instrument
    from prism.instrument import InstrumentRequired

    class _SplitOnly:
        def absorb_transmit(self, rows, **kw):
            return None

    try:
        instrument.set_default(_SplitOnly())
        instrument.resolve(None, "absorb_transmit", at="absorb_at_tekton")   # runs
        with pytest.raises(InstrumentRequired) as e:
            instrument.resolve(None, "next_by_coupling", at="Provider._route_next")
        assert e.value.member == "next_by_coupling"
    finally:
        instrument.clear_default()


def test_every_member_the_wire_resolves_is_one_the_contract_declares():
    """Every member the wire resolves is one `Instrument` enumerates.

    The check has to be structural. `require()` reports an absence for any member the slot lacks,
    declared or not, so a member the wire calls and the contract does not name still yields the
    right answer at runtime — while `isinstance(x, Instrument)` stays True for an implementation
    that fills only the declared members and then breaks at the first hop needing the undeclared
    one. A runtime test sees the right answer and misses the gap entirely.

    So the members are read from the call sites by AST — every `instrument.resolve(slot, "<name>",
    …)` in the wire — and checked against the tuple the contract enumerates. A new straddle added
    without declaring its member fails here, in the repo that owns the contract, rather than on a
    host that filled the contract exactly as written.
    """
    import ast

    from prism.instrument import INSTRUMENT_MEMBERS

    resolved: dict[str, set[str]] = {}
    for module in WIRE:
        tree = ast.parse((PY / "src" / "prism" / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "resolve" and len(node.args) >= 2):
                continue
            name = node.args[1]
            assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
                f"prism/{module}.py resolves a member through a computed name. The member has to be "
                f"a literal or no static check can tell whether the contract declares it.")
            resolved.setdefault(module, set()).add(name.value)

    # The control, because a scan that matched nothing would pass for every possible contract.
    # Measured: exactly two wire modules straddle, at exactly one call site each.
    assert resolved == {"frames": {"absorb_transmit"}, "reach": {"next_by_coupling"}}, (
        "the measured straddle changed: %r. That is not a failure — it is a re-measurement. Update "
        "this control deliberately, and check the contract declares whatever moved." % resolved)

    called = set().union(*resolved.values())
    missing = called - set(INSTRUMENT_MEMBERS)
    assert not missing, (
        "the wire calls %s, which `prism.instrument.Instrument` does not declare. A member the wire "
        "CALLS but the contract does not NAME lets a conforming implementation be written that "
        "passes every check and then fails at runtime on a method nobody told it about."
        % sorted(missing))


def test_an_instrument_that_fills_only_the_old_member_set_refuses_at_the_routed_hop():
    """An instrument missing `next_by_coupling` has no reading at the routed hop, and names it.

    Checked at the point of use: an embodiment filling only `absorb_transmit` and `membrane_screen`
    is handed to a real `Provider` that routes by coupling, and a real need carrying a real frame is
    driven through it. Three wrong answers are possible, and each is asserted against:

      · `AttributeError` from inside the flow — the gap surfacing as a bug in the plane rather than
        as a statement about the host;
      · a silent `None` hop — what `_route_next` returns for an unreadable frame, which reads at the
        requester as a signal that terminated rather than a host that could not measure;
      · `InstrumentRequired` naming some other member.

    The control is what ties the result to routing. `_route_next` resolves the instrument before it
    decodes the frame, so the same absence would be reported on a fixture whose frame was nonsense.
    The same provider, need and bases are therefore run with an instrument that fills the third
    member, and the hop it measures must reach the plane as a next need addressed to the tekton it
    named.
    """
    import numpy as np

    from prism.carriers import InMemoryCarrier
    from prism.instrument import Instrument, InstrumentRequired
    from prism.frames import FRAME_KEY, encode_frame
    from prism.plane import HLC, Keyring, Lightcone
    from prism.reach import NEED_CT, Absorption, Provider, reach as place_need

    ROOT, CAP, NEXT = b"fleet-root-secret", "cap.a", "cap.b"
    W = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 0.0]])
    BASES = {NEXT: np.array([[1.0], [0.0]])}
    # The frame-native handler shape (`frames.absorb_need`'s): the residual rides encoded inside the
    # response, which is what a sealed JSON payload can carry across a process boundary.
    RESPONSE = {FRAME_KEY: encode_frame(W)}

    class _PreD5:
        """An embodiment that splits frames and screens, but cannot route."""

        def absorb_transmit(self, rows, *, basis=None, null=None, seed=0):
            return None

        def membrane_screen(self):
            return object

    class _Routes(_PreD5):
        """The same instrument, plus the member. The signature is the declared one, keyword for
        keyword — if the protocol described something other than what the wire calls, this call
        would fail with a TypeError instead of routing."""

        seen: list = []

        def next_by_coupling(self, rows, bases, *, fired=(), null=None, seed=0,
                             min_energy=None, incident_energy=None):
            _Routes.seen.append((tuple(fired), sorted(bases)))
            return {"tekton": NEXT, "transmitted": rows, "absorbed_energy": 1.0, "k": 1}

    def _run(embodiment):
        kr = Keyring(ROOT)
        lc = Lightcone().join("node", CAP)
        carrier = InMemoryCarrier()
        prov = Provider(CAP, lambda need: Absorption(evidence=dict(RESPONSE), residual=None),
                        keyring=kr, lightcone=lc, principal="node", node="node", hlc=HLC("node"),
                        outbound=None, bases=BASES, embodiment=embodiment)
        place_need(carrier, {"q": 1}, to=CAP, keyring=kr, node="requester", hlc=HLC("requester"))
        prov.pump(carrier)
        return carrier

    assert isinstance(_PreD5(), Instrument) is False, (
        "the pre-D5 member set still satisfies the protocol, so the refusal below is a courtesy "
        "rather than a contract")

    with pytest.raises(InstrumentRequired) as e:
        _run(_PreD5())
    assert e.value.member == "next_by_coupling", e.value.member
    assert e.value.at == "Provider._route_next", e.value.at
    assert e.value.contract == "embodiment" and e.value.http_status == 503

    # ── The control: the same fixture, with the member filled, really does route. ──
    assert isinstance(_Routes(), Instrument)
    carrier = _run(_Routes())
    assert _Routes.seen == [((CAP,), [NEXT])], (
        "the wire did not hand the instrument the frame, the bases and the fired path: %r"
        % (_Routes.seen,))
    assert [l["to"] for l in carrier.poll() if l["content_type"] == NEED_CT] == [CAP, NEXT], (
        "the measured hop never reached the plane, so the refusal above proved nothing about "
        "routing")


def test_the_default_factory_is_not_called_until_a_measurement_is_taken():
    """A registered default is a factory, and the factory runs on first measurement, not at
    registration.

    An optics package registers a factory rather than the module itself, so a node that only carries
    frames never pays the import cost of an instrument it does not use. Resolved once per process
    thereafter."""
    from prism import instrument

    calls = []

    class _Late:
        def absorb_transmit(self, rows, **kw):
            return None

    def _factory():
        calls.append(1)
        return _Late()

    try:
        instrument.set_default(factory=_factory)
        assert calls == [], "the factory ran at registration"
        instrument.resolve(None, "absorb_transmit", at="t")
        assert calls == [1], "the factory did not run on first use"
        instrument.resolve(None, "absorb_transmit", at="t")
        assert calls == [1], "the factory ran twice — it must resolve once per process"
    finally:
        instrument.clear_default()
