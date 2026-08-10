"""The embodiment slot: what an instrument must do, and how the wire asks for one.

entroptics is the generic instrument. Each domain wraps it with what that domain knows, and the
wrapper — the embodiment — is where the domain knowledge lives:

    the aperture (ember)   domain: the signal — an ordered (T, F) frame
                           knows: ontology coordinates are sparse; evidence rows are correlated
                           needs: entroptics + numpy
    beacon (mantle)        domain: the corpus — a set of vectors
                           knows: its own corpus statistics
                           needs: numpy

The slot reads two ways. As a package, prism holds this file — the contract, stdlib-only — while the
implementations live with their domain. At runtime the slot holds whichever embodiment the host
injected at assembly, so the same crystal runs on a full node and on a constrained store.

Nothing here computes a measurement. prism's base install is `dependencies = []`
(`tests/test_contract_install_is_pure.py`), so this module imports neither numpy nor entroptics.

The four contracts:

`Instrument`, `Read` and `Dynamics` each hold members that two embodiments can legitimately
disagree about; `Conservation` holds members that are the same arithmetic everywhere and are
injected only because prism's base install cannot reach the dependency that computes them.

    Instrument     acts on the signal — splits frames, chooses addresses. Its output re-enters the
                   system as signal.
    Read           states something about the signal — how much is structure, against what null, at
                   what scale.
    Dynamics       the ordered axis — lag, delay embedding, and the propagator fitted along it. A
                   set of vectors has no lag, so a corpus embodiment does not fill this and is
                   complete without it.
    Conservation   energy accounting and entropy — no domain knowledge at all.

No function across chorus, crystal, ember and prism reaches two of these families, so injecting one
and not another is a real deployment rather than a degenerate one.

Member names and signatures are those of `ember.optics`, parameter for parameter, so that module
satisfies `Instrument`, `Read` and `Dynamics` with no adapter. `Conservation` is filled by two
modules: `prism.conservation` provides `energy` and `PathLedger` on numpy alone, and `ember.optics`
provides `entropy_bits` and `joint_entropies` on entroptics. `require()` checks per member, so a
host that fills part of a contract runs everything it can and names by member exactly what it
does not fill.

The companion object models (`Screen`, `Ledger`, `SpectralRead`, `Accumulator`, `Propagator`,
`DiffractionLimit`) declare the shape of what a member returns. They appear in no member tuple and
are checked by no `require()`, because nothing calls them as members — they tell an implementation
what its return value must carry. Their attribute lists are the demand consumers actually read, not
an implementation's full field set.

Usage:

    from prism.instrument import Instrument, Read, Dynamics, Conservation
    import ember.optics, prism.conservation

    crystal = Crystal(spec, embodiment=ember.optics, conservation=prism.conservation)

One keyword per contract, duck-typed, resolved by the host at assembly — the same mechanism as
`prism.runner`'s host seams. Which module fills a seam is the host's answer, and a seam nobody
fills fails loudly rather than reaching.
"""
from __future__ import annotations

import threading
from typing import (Any, Callable, Dict, Optional, Protocol, Tuple,
                    runtime_checkable)

from .errors import PrismError

__all__ = [
    "Instrument",
    "Read",
    "Dynamics",
    "Conservation",
    "Ledger",
    "Screen",
    "SpectralRead",
    "Accumulator",
    "Propagator",
    "DiffractionLimit",
    "InstrumentRequired",
    "require",
    "members_of",
    "INSTRUMENT_MEMBERS",
    "READ_MEMBERS",
    "DYNAMICS_MEMBERS",
    "CONSERVATION_MEMBERS",
    "set_default",
    "get_default",
    "clear_default",
    "resolve",
]


# ── The instrument ────────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class Screen(Protocol):
    """The two-way membrane's object model — where sides are placed and their coupling is read.

    A `Screen` holds registered sides (`Lens`es), places signals on them, renders them back out, and
    reports the coupling between two sides. The coupling is measured at the screen rather than
    declared. Every method here is on the object an `Instrument`'s `membrane_screen()` factory
    produces.
    """

    def register(self, side: str, **kwargs: Any) -> Any: ...
    def place(self, side: str, surface: Any) -> Any: ...
    def render(self, side: str, concept: Any) -> Any: ...
    def couple(self, a: str, b: str) -> float: ...
    def coupling(self, a: str, b: str) -> Any: ...
    def transfer(self, a: str, b: str) -> Any: ...
    def certify(self, side: str, surface: Any) -> Any: ...
    def read(self) -> Any: ...
    def balance(self) -> Any: ...
    def clear(self, side: Optional[str] = None) -> None: ...

    @property
    def placed(self) -> Any: ...


@runtime_checkable
class Instrument(Protocol):
    """The domain's wrapping of the generic instrument — what a host injects at assembly.

    Filled by `ember.optics` on a full node (the aperture: entroptics + numpy, knowing that ontology
    coordinates are sparse and evidence rows correlated), and by a beacon-backed embodiment on a
    constrained store (numpy only, knowing its own corpus statistics).

    Members are checked separately, at the moment each is used. An embodiment that fills
    `absorb_transmit` and not `membrane_screen` is a real, partial deployment: it splits frames but
    cannot place them, naming the member it lacks. That is a constrained host reporting its
    constraint, not an optional member.
    """

    def absorb_transmit(self, rows: Any, *, basis: Any = None, null: Any = None,
                        seed: int = 0) -> Optional[Tuple[Any, Any, int]]:
        """Split an incident (T, F) frame at the membrane into the band that couples here and the
        residual that does not: `(absorbed, transmitted, k)`.

        Coupling is measured: the absorbed band is the frame's projection onto the resolved
        subspace, and the projector is orthogonal, so `‖incident‖² = ‖absorbed‖² + ‖transmitted‖²`
        holds by construction. `k == 0` means nothing coupled — `absorbed` is all-zero and the whole
        signal transmits on, intact.

        Returns `None` when the frame cannot carry a read (too few rows, one feature, all-zero).
        `None` is the computed null and it is a result: the caller propagates the frame unabsorbed.
        An implementation fills this slot by returning `None` there, not a zero split, a best-guess
        basis, or an exception.
        """

    def next_by_coupling(self, rows: Any, bases: Any, *, fired: Any = (), null: Any = None,
                         seed: int = 0, min_energy: Optional[float] = None,
                         incident_energy: Any = None) -> Optional[Dict[str, Any]]:
        """One hop of coupling-based routing: of the candidate tektons in `bases`
        (`{name: (F, k) coupling basis}`), which one absorbs the most of this `(T, F)` frame — and
        what would be left if it did::

            {"tekton": <name>, "transmitted": <(T, F) frame>, "absorbed_energy": float, "k": int}

        Returns `None` when nothing couples above the floor. That is the computed null and it is a
        result: the signal has finished its path and terminates here — not a fabricated hop, a
        default capability, or the first name in `bases`.

        `transmitted` is a preview: what would remain *after* the chosen tekton absorbs, computed
        only to rank the candidates. Route on `tekton` and forward the signal intact, because the
        receiving tekton takes its own split. Forwarding `transmitted` would absorb the same band
        twice and attenuate the signal at every hop, breaking the conservation the membrane model
        rests on.

        `fired` is the tektons already coupled (on the plane: the need artifact's `path`, carried in
        provenance because a distributed hop has no shared memory). Coupling is idempotent, so a
        revisit absorbs nothing — a derived termination rather than a hop cap.

        `min_energy=None` means the caller states no floor, and the implementation derives one from
        the arithmetic it actually performed: the level below which a difference in energy is
        floating-point noise rather than a coupling. That floor decides whether a tekton coupled at
        all, which is the routing decision itself, so it is measured rather than typed.
        `incident_energy` scopes the floor to the original incident signal when the caller knows it;
        omitted, the floor is this residual's own energy and rises as the signal is absorbed, so a
        long chain terminates slightly earlier than an in-process walk.
        """

    def membrane_screen(self) -> Any:
        """The `Screen` class — a factory, not an instance, so the host's construction kwargs stay
        the caller's. Call it, then call the result with those kwargs.

        Separate from the measurement surface. A projection read has no placement or coupling
        concept and cannot stand in here; this screen folds the feature axis, which destroys a
        sparse carrier, so it is not used to measure structure.
        """


# ── The structure read ────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class SpectralRead(Protocol):
    """What `Read.read_ordered` returns — the read, and the continuous evidence behind its integer.

    Every field here was measured to produce `k_signal` and is reported alongside it, so a caller
    can see how far the count stands from the noise floor rather than receiving a bare integer.

    The attributes are the demand consumers actually read (`ophan/market_frame.py`,
    `lumen/reasoning.py`, `ember/signal/projection.py`), not an implementation's full field list.
    `Optional[float]` is load-bearing throughout: `None` means not measured (a `with_screen=False`
    read never runs the screen half), and it is reported as `None` rather than 0.0, which would read
    as an affirmative measurement.
    """

    k_signal: int              #: modes above the noise floor of the feature-correlation spectrum
    k_lo: int                  #: the Weyl-certified interval's floor …
    k_hi: int                  #: … and its ceiling; `k_lo == k_hi == k_signal` is certified
    k_margin_last: Optional[float]   #: how far the marginal resolved mode stands above the floor
    k_margin_next: Optional[float]   #: how far the first unresolved mode falls below it
    contrast: float            #: λ₁ / noise floor — > 1 means there is structure at all
    top_share: float           #: the dominant mode's power fraction
    coherence: Optional[float]  #: the ordered-axis lag-1 z-score; `None` when it was not measured

    @property
    def k_certain(self) -> Any: ...


@runtime_checkable
class Accumulator(Protocol):
    """What `Read.accumulator` returns — a pooling screen, fed one plane per turn.

    The instrument accumulates. A single turn's frame is too short for the certified interval to
    collapse, so evidence is pooled across turns: `T` grows, the band shrinks as √(F/T), and the
    count becomes a measurement rather than a fit.
    """

    T: int                     #: pooled rows seen so far — the band tightens as this grows
    F: int                     #: the fixed feature width every plane must share

    def add(self, plane: Any) -> Any:
        """Pool one intact `(T_p, F)` plane, keeping its within-plane correlation. Planes are added
        whole rather than row by row, because flattening them discards the correlation the read is
        about."""

    def band(self) -> float:
        """The current concentration band — a progress reading rather than a verdict."""

    def spectral(self) -> Any:
        """The pooled spectrum over everything added."""

    def merge(self, other: "Accumulator") -> "Accumulator":
        """Combine two accumulations without exchanging a raw frame — only the pooled covariance
        travels, so a peer contributes its evidence while its observations stay its own."""


@runtime_checkable
class Read(Protocol):
    """The structure read — how much of this is signal, against what null, at what scale.

    A contract separate from `Instrument`. `Instrument` acts on the signal, returning frames and
    addresses whose output re-enters the system as signal; `Read` returns a statement about the
    signal. No function reaches both, so injecting one and not the other is a real deployment.

    Filled by `ember.optics` on a full node. A beacon-backed store fills it too, holding three of
    the members in substance (`signal_rank`, `structure_rank`/`spectrum_stats`, and the permutation
    path behind `correlated_null`). This is the contract the two embodiments legitimately disagree
    on.
    """

    def correlated_null(self, *, draws: Optional[int] = None, far: Optional[float] = None) -> Any:
        """The noise provider for correlated rows — what retrieved evidence always is.

        A member rather than a keyword, because the null is the domain's knowledge: an RF embodiment
        has dense carriers and different nulls. The false-alarm level travels with the null rather
        than as a second argument beside it, so one cutoff is one decision and the provider owns
        both the threshold and the α it is drawn at. A caller with an opinion about how often it
        will call noise a coupling states it by handing over a null that holds that opinion.

        `draws=None` and `far=None` mean the caller stated neither, so the implementation uses its
        own published value. `draws` is compute rather than a modelling choice — it fixes the finest
        p the empirical null can resolve (`1/draws`) and costs CPU linearly, so it is answered from
        the measured resource envelope.
        """

    def read_ordered(self, rows: Any, *, null: Any = None, seed: int = 0,
                     window: Optional[int] = None, with_screen: bool = True) -> "SpectralRead":
        """Screen an ordered `(T, F)` frame — axis 0 ordered, axis 1 feature. Deterministic per
        `seed`. A `set` is not an ordered frame and carries no sequence to read.

        `null=None` runs on the implementation's derived default, which is correct for an i.i.d.
        bulk and optimistic for correlated rows; read retrieved evidence against `correlated_null()`.

        `window=None` reads the whole frame. An implementation reads exactly the window asked for,
        so a caller can see what was measured.

        `with_screen=False` skips the expensive half when only the invariant count is wanted. The
        skipped fields then read `None` rather than 0.0 or False, so an absent measurement is
        distinguishable from a measured one.
        """

    def resolvable(self, rows: Any, *, null: Any = None, seed: int = 0,
                   require_certain: bool = False) -> Optional[int]:
        """`k_signal` alone — the count of modes above the noise floor of the feature-correlation
        spectrum. A projection of `read_ordered`, which is why it shares this contract: nothing can
        fill it without being able to take the read.

        Which matrix is the whole content of this declaration. This is `#{k : λ_k > λ₊}` on the
        unit-diagonal correlation matrix, not the entropy-folded screen statistic that shares the
        name `K_signal` in the paper. Three distinct quantities are called "coherence" or "K_signal"
        across this system, so the one meant here is named exactly
        ([[pick-the-read-by-which-axis]]).

        `require_certain=True` returns the count only when the certified interval has collapsed onto
        it. `None` is the computed null and it is a result: the frame cannot carry a read (too few
        rows, one feature, all-zero), which is a different statement from a resolved count of 1. A
        caller receiving `None` defers rather than substituting a keep-everything default, which
        would report a silent no-op as a derived decision.
        """

    def scales(self, rows: Any, windows: Any = None) -> Optional[list]:
        """Structure against observation window — the same read taken at several apertures, so a
        caller can see whether the structure is a property of the signal or of how much of it was
        looked at.

        `windows=None` lets the implementation choose its own ladder. What "a window" means is the
        domain's: trailing windows of the ordered axis for a signal, nested subsets for a corpus.
        `None` when the frame cannot carry a read.
        """

    def accumulator(self, n_features: int, *, whiten: bool = False) -> "Accumulator":
        """An empty `Accumulator` of fixed feature width — a factory, so the caller owns the object
        and its lifetime. `F` is constant across planes by construction, which is what a fixed
        coordinate basis provides."""

    def accumulated_read(self, acc: Any) -> Optional[Dict[str, Any]]:
        """What a pooled `Accumulator` currently resolves::

            {"T", "F", "band", "k_signal", "interval", "certified"}

        `certified` is True only when the interval has collapsed onto the count. `band` and
        `interval` are reported beside it so a caller can see how far certification is, not merely
        that it has not happened. The band shrinks as evidence accumulates, so this is a progress
        reading: certification is reached by adding evidence.

        `k_signal == 0` means unmeasurable — a frame that resolves no modes has no rank that could
        have stopped moving, and a sparse ontology coordinate reads this way. `None` when the
        accumulator holds nothing.
        """


    def screen_normalize(self, rows: Any, mask: Any = None) -> Any:
        """Give every feature channel a common noise scale — robust (MAD) whitening on the screen.

        Required whenever a frame co-registers heterogeneous planes. `chorus/ophan/market_planes.py`
        puts log returns beside article counts on one frame; read raw, the covariance is ~10⁷ times
        larger on the counts block, so the leading mode is the unit mismatch and the read reports a
        confident number about arithmetic. Whitening first makes the read a statement about the
        signal.

        On the screen, never on a vector. Dividing an individual vector by its norm produces cosine
        similarity, which this domain does not use, and discards the magnitude the conservation
        certificate is stated over.

        Both embodiments fill it. `ember.optics` and `mantle/search/beacon/engine.py::whiten`
        implement the identical estimator — same median/MAD·MAD_SCALE, same `_shrink_mad` pooling —
        and beacon's own `noise_floor` depends on it, being measured on the whitened matrix. Across
        five frames (i.i.d., heterogeneous units, planted rank-3, a dead channel, and a short 8×16)
        the two agree to max |difference| 0.0. Their agreement is evidence, as with `shannon_bits`,
        rather than a shared dependency.

        Whitening can amplify: per-channel MAD rescales a frame with heterogeneous channel occupancy
        by up to ~1e12, and a sparse coordinate can have zero MAD in every channel. Read the
        amplification the spectral read reports to know whether the frame came back comparable.

        Returns the whitened `(T, F)` frame, or `None` when the frame cannot carry one. A partially
        scaled frame is never returned, because it would read as measured.
        """


# ── The ordered axis ──────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class DiffractionLimit(Protocol):
    """What `Dynamics.resolution_limit` returns — how far along the ordered axis this signal stays
    correlated with itself. `xi` is the integral correlation length, and it supplies every lag,
    embedding depth and hop budget in a propagation, because a step count measures the walk rather
    than the signal."""

    xi: float


@runtime_checkable
class Propagator(Protocol):
    """What `Dynamics.fit_dynamics` and `Dynamics.dynamics_state` return — the fitted operator.

    The propagator is the answer. When a trajectory is compact the operator is the law governing it,
    and there is nothing further to recover: an operator measured from the data is a stronger result
    than a human-readable equation in a guessed basis.
    """

    def update(self, frame: Any) -> Any:
        """Ingest one ordered frame."""

    def update_block(self, X: Any) -> Any:
        """Ingest a whole ordered block at once."""

    def resolved(self, *, null: Any = None) -> int:
        """How many modes of the fitted operator stand above `null`. `0` means nothing resolved, and
        scores distinctly from a maximally compact fit so that noise is not read as deterministic."""

    def rates(self) -> Any:
        """The operator's own spectrum — the decay rates its horizon is read off."""

    def rollout(self, z: Any, h: int) -> Any:
        """Propagate a state `h` steps. `h` is the operator's horizon, read off its spectrum: the
        distance past which it can say nothing further."""

    def merge(self, other: "Propagator") -> "Propagator":
        """Combine two fits over the same coordinate without exchanging raw trajectories."""


@runtime_checkable
class Dynamics(Protocol):
    """The ordered axis — lag, delay embedding, and the propagator fitted along it.

    A contract separate from `Instrument` and `Read`. Every member here is a statement about lag: an
    autocorrelation over τ, a Takens delay, a Koopman/DMD operator over consecutive frames. The two
    embodiments differ on exactly this axis — the aperture's domain is an ordered (T, F) frame,
    beacon's is a set of vectors, and a set has no lag. A shuffled trajectory has no dynamics to
    fit, though a fit will still return something ([[entroptics-screen-is-ordered]]).

    An embodiment that does not fill this is a complete embodiment of a domain that does not pose
    the question, which is why it is a separate contract rather than five members a corpus store
    could only ever leave unfilled. `isinstance(beacon, Instrument)` stays True for what beacon is.

    Order is the whole signal here. A frame too short to carry the measurement returns no
    measurement, rather than being padded to fit.
    """

    def decay_profile(self, W: Any) -> Any:
        """C(τ) — the signal's own ordered-axis autocorrelation, its optical transfer function.
        `None` when the frame cannot carry the read. The instrument's own minimum is the one that
        governs, so a caller does not state a second one."""

    def resolution_limit(self, profile: Any) -> Optional["DiffractionLimit"]:
        """The correlation length ξ read off a decay profile. Cannot be filled without
        `decay_profile`, whose output it consumes — which is why it sits beside it."""

    def embed(self, X: Any, d: int) -> Any:
        """Takens delay embedding — `d` lagged copies of the trajectory. Returns `X` unchanged when
        the series is too short to embed at that depth. The feasibility limit is `T`, measured by
        the instrument rather than set as a margin below it."""

    def fit_dynamics(self, X: Any, *, forgetting: float = 1.0,
                     rank: Any = None) -> Optional["Propagator"]:
        """Fit the propagator of an ordered trajectory. `forgetting=1.0` remembers everything; below
        1.0 the past decays, which is forgetting as a rate rather than a deletion. `rank=None` lets
        the read decide the rank rather than the caller asserting it."""

    def dynamics_state(self, n_features: int, *, forgetting: float = 1.0,
                       rank: Any = None) -> "Propagator":
        """An empty `Propagator` of the given width, for a caller that ingests frame by frame rather
        than fitting a whole trajectory at once. The streaming counterpart of `fit_dynamics`."""


# ── The accounting ────────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class Ledger(Protocol):
    """The running account of one signal's journey through a path of absorbing elements.

    Opened on the incident frame, `absorb()`ed at each element crossed, closed with `emit()` if a
    residual leaves as output. `certificate()` is the verdict.
    """

    def absorb(self, absorbed: Any, transmitted: Any, *, at: Optional[str] = None,
               k: Optional[int] = None) -> "Ledger":
        """Record one element's split. The ledger measures the frames it is handed rather than
        trusting a reported number, so a membrane that miscomputes its own split shows up as a
        discrepancy instead of confirming itself."""

    def emit(self, *, at: Optional[str] = None) -> "Ledger":
        """Close the path: the residual still travelling leaves as output and is accounted for. One
        of the two legitimate endings, recorded as distinct from the elements having absorbed
        everything — calling it claims the residual was handed to someone."""

    def certificate(self) -> Any:
        """The full 0 → 1 → 0 account and whether it closes: `incident`, `absorbed`, `emitted`,
        `unaccounted`, `loss`, `tolerance`, `closed`, `terminated`, `balanced`, `curve`, `why`.

        `tolerance` is derived from the arithmetic actually performed rather than set as a constant,
        so the check proves conservation instead of proving its own threshold. Per-hop conservation
        certifies nothing on its own, which is why `closed` is the prefix identity at every hop and
        `balanced` is the claim about the whole path.
        """


@runtime_checkable
class Conservation(Protocol):
    """The energy accountant — arithmetic over frames, with no domain knowledge.

    Injected because the arithmetic needs a dependency prism's base install does not carry, not
    because it varies by domain. That dependency rule is this contract's membership test, and it is
    what separates it from `Instrument`, `Read` and `Dynamics`, whose members are declared because
    two embodiments can legitimately hold different opinions about them.

    Filled by two modules. `prism.conservation` fills `energy` and `PathLedger` on numpy alone;
    `ember.optics` fills `entropy_bits` and `joint_entropies` on numpy plus entroptics. A full node
    has both and hands over whichever the call site needs; a numpy-only host fills what it can and
    names the rest by member. `require()` is checked per member for exactly this reason.
    """

    def energy(self, frame: Any) -> float:
        """`‖frame‖²` — the sum of squares over every element.

        `None` is silence, a frame that never formed, and its energy is 0.0. A path whose incident
        signal is silence conserves trivially, which is a reading rather than an error."""

    def PathLedger(self, incident: Any, *, at: Optional[str] = None) -> Ledger:
        """Open a `Ledger` on an incident frame. CamelCase because it is a class in the
        implementation these names are derived from.
        """

    def entropy_bits(self, weights: Any) -> float:
        """`H(w) = −Σ p log₂ p` in bits over a non-negative weight array, `p = w / Σw`. Normalised
        internally, so the caller hands over raw weights. A single weight or an all-zero array is
        0.0; a flat array of n weights is log₂(n), which is what a caller divides by to put a spread
        onto [0, 1].

        A `Conservation` member because membership here is a dependency fact. `−Σ p log₂ p` is
        arithmetic that cannot vary by domain — mantle's beacon computes it under entroptics' own
        name `shannon_bits` (`mantle/search/beacon/engine.py`), and the two agree — so it is not an
        embodiment member. It is declared rather than implemented in prism because the
        implementation is an adapter onto `entroptics.entropy.shannon_bits`, the same entropy
        entroptics uses internally for geometry marginals, mode weights and spectra. That identity
        is its value: a caller's entropy and the instrument's own cannot drift. prism may never
        import entroptics (the publication boundary,
        `tests/test_contract_install_is_pure.py::PRIVATE`), so the name is declared here and filled
        by `ember.optics`.

        An absent `entropy_bits` is a capacity fact rather than a wiring one. `prism.conservation`
        fills `energy` and `PathLedger` on numpy and does not fill this member; `ember.optics` fills
        this one. A host injects both.

        Non-finite and non-positive entries are dropped rather than clamped: a negative weight is
        not a reading. Nothing left after dropping has no honest 0.0 to report here, because 0.0 is
        the honest reading of a single weight and of a perfectly concentrated spread.
        """

    def joint_entropies(self, frame_x: Any, frame_y: Any,
                        mask_x: Any = None, mask_y: Any = None) -> dict:
        """The three entropies of two co-registered frames, and the three differences, all from one
        joint table: `{"H_X", "H_Y", "H_XY", "I_XY", "H_X_given_Y", "H_Y_given_X"}` in bits.

        `I_XY` is the mutual information — how much of one frame's channel structure the other
        determines. `H_X_given_Y` is Shannon's equivocation, the uncertainty about the first frame
        that survives knowing the second, and it answers a question no energy read can: a receiver
        may absorb every joule a signal carried and still leave which signal it was ambiguous,
        because absorption is a statement about energy and this is a statement about which.

        One member rather than three, because every number here is a difference of the same three
        entropies and taking them from one table makes `I_XY = H_X + H_Y − H_XY` and
        `I_XY = H_X − H_Y(X)` hold exactly rather than to float noise. One table also fixes a single
        answer for normalisation, the clip, and which cells were absent. A caller wanting two of the
        six pays for one table.

        Co-registration is enforced and a mismatch raises. Two frames ordered by their own private
        axes superpose into noise, so a joint read over them would measure the misalignment rather
        than either signal. `H_X_given_Y` and `H_Y_given_X` are different numbers: the read is
        directed, and both are returned under their own names so a call site takes the one it means.

        Same membership rule as `entropy_bits`: a dependency fact. The floor is entroptics, which
        prism does not import, and the instrument's own marginals use the same implementation.
        """


#: The members of each contract, in the order a consumer reaches for them. Stated as data so a test
#: can enumerate what an implementation must fill without re-typing the list.
#:
#: The companion object models (`Screen`, `Ledger`, `SpectralRead`, `Accumulator`, `Propagator`,
#: `DiffractionLimit`) appear in no tuple. They describe what a member returns, and nothing calls
#: them as members, so `require()` never demands a slot fill a name no caller reaches for.
INSTRUMENT_MEMBERS: Tuple[str, ...] = ("absorb_transmit", "next_by_coupling", "membrane_screen")
READ_MEMBERS: Tuple[str, ...] = ("correlated_null", "read_ordered", "resolvable", "scales",
                                 "accumulator", "accumulated_read", "screen_normalize")
DYNAMICS_MEMBERS: Tuple[str, ...] = ("decay_profile", "resolution_limit", "embed", "fit_dynamics",
                                     "dynamics_state")
CONSERVATION_MEMBERS: Tuple[str, ...] = ("energy", "PathLedger", "entropy_bits",
                                         "joint_entropies")

_CONTRACTS = {
    "embodiment": (Instrument, INSTRUMENT_MEMBERS),
    "read": (Read, READ_MEMBERS),
    "dynamics": (Dynamics, DYNAMICS_MEMBERS),
    "conservation": (Conservation, CONSERVATION_MEMBERS),
}

#: Which module fills each contract on a full node — quoted in the raised message so it says what
#: to inject rather than only what was missing. Advice a host acts on, so every name here is a
#: package that exists. Not an import and not a default: prism never reaches for these, and a
#: constrained host injects its own. `ember.optics` appears three times because the aperture is one
#: file by enforcement ([[one-aperture-enforced]]), not because the three measurements are one kind.
#:
#: `conservation` names two modules because two fill it. `prism.conservation` stands on numpy and
#: does not import entroptics, so `entropy_bits` and `joint_entropies` — adapters over
#: `entroptics.entropy` — come from `ember.optics`. Naming both sends a host to inject everything
#: the contract needs in one step.
_FILLED_BY = {
    "embodiment": "ember.optics",
    "read": "ember.optics",
    "dynamics": "ember.optics",
    "conservation": ("prism.conservation (energy, PathLedger) with "
                     "ember.optics (entropy_bits, joint_entropies)"),
}


# ── The refusal ───────────────────────────────────────────────────────────────────────────────────

class InstrumentRequired(PrismError):
    """The slot needed to answer this was never filled — raised at the point of measurement.

    A host that cannot measure says so at the moment it is asked, naming the contract, the missing
    member, and the operation that wanted it, so the answer is "this host is not equipped" rather
    than a number with nothing behind it.

    503 rather than 500: not equipped is the same class of fact as not available. Carries `contract`,
    `member` and `at` so a caller can discriminate without parsing the message.
    """

    http_status = 503
    code = "embodiment_required"

    def __init__(self, message: str, *, contract: str, member: str,
                 at: Optional[str] = None) -> None:
        super().__init__(message)
        self.contract = contract
        self.member = member
        self.at = at


def members_of(slot: Any, contract: str) -> Tuple[str, ...]:
    """Which members of `contract` this slot actually fills — the measured extent of an embodiment.

    Reports what is there. A slot of `None` fills nothing and returns `()`.
    """
    try:
        _proto, names = _CONTRACTS[contract]
    except KeyError:
        raise ValueError("no such contract: %r (have %s)"
                         % (contract, ", ".join(sorted(_CONTRACTS)))) from None
    if slot is None:
        return ()
    return tuple(n for n in names if callable(getattr(slot, n, None)))


def require(slot: Any, member: str, *, contract: str, at: str) -> Any:
    """Return `slot.<member>`, or refuse loudly — the one door every reach for the slot goes through.

    `contract` is one of `_CONTRACTS` — `"embodiment"`, `"read"`, `"dynamics"`, `"conservation"`;
    `at` names the operation that wanted it, so the message says what could not be done and not
    merely what was absent.

    Checked per member rather than per slot. A constrained host that fills `absorb_transmit` and not
    `membrane_screen` can still split frames, and the gap is reported here by name rather than
    surfacing as an `AttributeError` from inside the flow.
    """
    if contract not in _CONTRACTS:
        raise ValueError("no such contract: %r (have %s)"
                         % (contract, ", ".join(sorted(_CONTRACTS))))
    if slot is None:
        raise InstrumentRequired(
            "%s needs the %s contract and none was injected. The measurement is not part of this "
            "package — construct with `%s=<implementation>` (a full node injects `%s`; a "
            "constrained store injects its own). Nothing is assumed and nothing is defaulted: an "
            "unmeasured quantity has no honest value."
            % (at, contract, contract, _FILLED_BY[contract]),
            contract=contract, member=member, at=at)
    fn = getattr(slot, member, None)
    if not callable(fn):
        filled = members_of(slot, contract)
        raise InstrumentRequired(
            "%s needs `%s.%s`, and the injected %s does not provide it (it fills: %s). A partial "
            "embodiment is a real deployment — this host does what it can and refuses exactly what "
            "it cannot, rather than degrading the answer."
            % (at, contract, member, contract, ", ".join(filled) if filled else "nothing"),
            contract=contract, member=member, at=at)
    return fn


# ── The process default — the only state in this file ─────────────────────────────────────────────
# Everything above this line is a declaration. Below it is the one piece of mutable process state
# the package holds, kept separate so a caller importing the contract to learn what to fill needs no
# registry to exist, and a registry a host writes at assembly does not read as part of the contract.
#
# Two wire functions straddle the wire/aperture split — the only places the transport layer takes a
# measurement:
#
#     frames.absorb_at_tekton   ->  optics.absorb_transmit     (the membrane split)
#     reach.Provider.route_next ->  optics.next_by_coupling    (which tekton couples next)
#
# Everything else in the wire is transport, encoding and accounting, and needs no instrument. The
# straddle is two functions rather than two modules, so an injected slot carries it.
#
# Resolution order, most specific first:
#
#   1. the `instrument=` keyword handed to the call — the caller's answer wins;
#   2. the process default the host registered through `set_default()`;
#   3. nothing -> `InstrumentRequired`, raised at the measurement, naming the member and the
#      operation.
#
# There is no step 4. An unfilled slot does not degrade to a zero split, a guessed basis, or a route
# that quietly ends: a host that cannot measure says so.

_lock = threading.Lock()
_default: Optional[Any] = None
_factory: Optional[Callable[[], Any]] = None


def set_default(instrument: Any = None, *, factory: Optional[Callable[[], Any]] = None) -> None:
    """Register the process-wide instrument the wire falls back to. Called by a host, not by wire
    code itself.

    Pass `instrument=` for an object or module that is already imported, or `factory=` for a
    zero-argument callable resolved on first use. The factory form is what a package uses at import
    time: registering `lambda: importlib.import_module("ember.optics")` costs nothing until
    something takes a measurement, so a node that only carries frames never pays for the instrument
    it does not use.

    Passing both is a caller error. Passing neither clears the slot (see `clear_default`).
    """
    global _default, _factory
    if instrument is not None and factory is not None:
        raise ValueError("set_default takes an instrument OR a factory, not both")
    with _lock:
        _default = instrument
        _factory = factory


def clear_default() -> None:
    """Empty the slot. Used by tests that need to observe `InstrumentRequired` being raised."""
    set_default()


def get_default() -> Optional[Any]:
    """The registered default, resolving a factory on first use — or `None` if the slot is empty.

    `None` reports an empty slot, rather than raising or returning a stand-in instrument.
    """
    global _default, _factory
    with _lock:
        if _default is None and _factory is not None:
            _default = _factory()
            _factory = None
        return _default


def resolve(instrument: Any, member: str, *, at: str) -> Any:
    """Return the callable `member` of the instrument to use here, or refuse.

    `instrument` is whatever the call site was handed (usually `None`). `InstrumentRequired` is
    raised by `require` — one door, one message, one exception type — so a caller that already
    discriminates on
    `InstrumentRequired.member` sees no difference between a slot the host left empty and one it
    filled only partly.

    Resolves against the `"embodiment"` slot only. `Read` and `Dynamics` are reached by the
    consumers that take those measurements, which pass their own slot explicitly; the wire takes
    exactly two measurements and both are on this one.
    """
    slot = instrument if instrument is not None else get_default()
    if slot is None:
        raise InstrumentRequired(
            "%s needs an instrument and none was injected. Hand one to the call "
            "(`instrument=<implementation>`) or register a process default with "
            "`prism.instrument.set_default(...)`. A full node injects `%s`; a constrained "
            "host injects its own and refuses exactly what it cannot measure."
            % (at, _FILLED_BY["embodiment"]),
            contract="embodiment", member=member, at=at)
    return require(slot, member, contract="embodiment", at=at)
