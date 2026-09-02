"""Demurrage — held value dissipates unless re-verified (the 2nd law, read as accounting).

Demurrage acts on energy, never on belief.

`mass.provenance_of()` answers "why should I believe this?" — which channel an artifact was
obtained through (`prism.mass.Provenance`, unranked), together with how many independent origins
attest it (`prism.attestation`). A human-validated fact from ten years ago is still true, so this
module never touches provenance or attestation. It computes a separate quantity:

    energy — the live economic value of holding an artifact right now.

Belief is the artifact's rest mass: provenance and attestation, conserved. Energy is its hot mass,
deposited by useful work (consumption, the PoUW meter) and dissipated by the 2nd law between
deposits. A caller asking "should I believe this?" reads `mass.provenance_of` and
`prism.attestation`; one asking "what is holding this worth now?" reads `energy` here. Keeping them
apart is what lets demurrage drive a never-consumed fact's energy to zero without touching whether
it is true.

An accumulator, not a reset clock.

The meter is consumption: a claim's energy is its useful work downstream. Each time an artifact does
work (`evolution.record_use`) it receives a deposit sized by its rest mass, so energy cannot be
minted faster than provenance permits ([[inertial-learning]]). Between deposits the standing heat
cools by `exp(-dt/tau)`. Frequent consumption is hot and valuable; never consumed is cold and
worthless to hold. It is an exponentially-weighted accumulator:

    heat ← heat·exp(-dt/tau) + deposit

This is `forgetting.py`'s cooling amplitude applied to the corpus's stored value rather than to a
screen's attention — the same physics over a different conserved quantity.

Every dt is clamped at 0, so cooling is monotone and re-warming happens only through a real deposit.
A read whose `now` is smaller than the last update therefore cannot mint energy through clock skew.

Dependency-free (stdlib only), so the server and the leaf value an artifact identically — the same
reason `mass.py` lives here.

`tau` is the economy's clock and it is measured rather than chosen. There is no default constant:
with nothing measured, value is carried forward undissipated. See the block below `slow_rate`.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

from . import law as _law

# ── the 2nd-law clock is measured, and there is no constant ──────────────────────────────────────
# In frames: deposited energy cools by exp(-dt/tau). One frame is one change-feed step (mesh `_seq`),
# the same monotone axis `mass.age_frames` counts, and not a wall clock.
#
# The screen is the market and its rates are measured ([[universal-economics]], canon §12-13).
# Demurrage is the 2nd law applied to deposited energy and forgetting is the 2nd law applied to
# attention — one measured timescale, read off live data rather than two constants asserted equal.
# The value varies stream to stream and conversation to conversation, which is the point: it is a
# reading, not a constant.
#
# No measured cooling rate means no cooling. Energy nobody has measured a dissipation rate for has
# not been measured to dissipate ([[absence-is-not-an-affirmative-claim]]), so `tau=None` carries
# heat forward unchanged and accrues no new realized value. It self-corrects the moment a rate
# resolves, and it is the same shape as an unmeasured Screen holding every trace at full amplitude.
#
# The measuring Screen lives in `ember.signal.forgetting`, above prism in the DAG, so prism declares
# the socket and the runner fills it at boot — the same shape as
# `ember.runtime.boot._wire_peer_signal_delivery`.

# The runner installs a callable returning the measured slow timescale (frames), or None when
# nothing has measured one yet. It reads a measurement; a lambda returning a constant would be a
# chosen number.
_SLOW_RATE_SOURCE = None


def set_slow_rate_source(fn) -> None:
    """Install the measurement this economy's clock is read from. Called by the runner at boot."""
    global _SLOW_RATE_SOURCE
    _SLOW_RATE_SOURCE = fn


def slow_rate() -> Optional[float]:
    """The measured slow timescale, in frames — or None when nothing has measured one.

    `None` says nobody has measured the economy's clock, which is a different statement from any
    particular rate ([[absence-is-not-an-affirmative-claim]]). A caller that needs a number to keep
    running falls back explicitly and can see that it did."""
    if _SLOW_RATE_SOURCE is None:
        return None
    try:
        r = _SLOW_RATE_SOURCE()
    except Exception:
        return None
    try:
        r = float(r)
    except (TypeError, ValueError):
        return None
    return r if (r > 0.0 and r == r and r != float("inf")) else None


def tau_now() -> Tuple[Optional[float], str]:
    """`(tau, source)` — the clock to cool by, and whether anyone measured it.

    `(None, "unmeasured")` when nobody has, rather than a constant. A caller receiving `None` carries
    heat forward undecayed, which is what every function here does."""
    r = slow_rate()
    return (r, "measured") if r is not None else (None, "unmeasured")

# Where the accumulator rides on an artifact. Additive, in `context` — the label-blind store keeps
# it without a schema change, exactly as provenance rides there (`mass.provenance_of`). Two scalars:
# the standing (last-cooled) heat, and the frame it was last updated. Everything else is derived.
HEAT_FIELD = "energy_heat"
FRAME_FIELD = "energy_frame"
# The realized-value integral ∫energy·dt through the last-settled frame — the settlement basis (the
# P7 payout). Distinct from the instantaneous `heat` stock: heat dissipates, earned only ever grows.
EARNED_FIELD = "energy_earned"


def _tau(tau: Optional[float]) -> Optional[float]:
    """Resolve the clock: an explicit `tau` wins, otherwise the measured one, otherwise None.

    `None` means nobody has measured a dissipation rate, and every caller below then carries value
    forward untouched. There is no number to fall back to."""
    if tau is None:
        return slow_rate()
    try:
        t = float(tau)
    except (TypeError, ValueError):
        return None
    return t if t > 0.0 else None


def cool(heat: float, last_frame: int, now: int, *, tau: Optional[float] = None) -> float:
    """The standing heat carried forward to `now` — the raw 2nd-law step, no deposit.

    The decay itself is `prism.law.cool` (`exp(-dt/tau)`, dt clamped ≥0, tau kept >0) — the one
    attenuation law forgetting and the propagator also obey, so the three cannot drift. This is
    `energy` for a read, and `deposit` calls it before adding work, so the read path and the write
    path demurrage through one identical function.

    With no measured clock the heat is carried forward unchanged, since there is no measured rate to
    dissipate it against."""
    h = max(0.0, float(heat))
    t = _tau(tau)
    return h if t is None else h * float(_law.cool(now - last_frame, tau=t))


def _integral(heat: float, dt_frames: float, tau: float) -> float:
    """Closed-form area under one decay segment: ∫₀^dt heat·exp(-t/τ) dt = heat·τ·(1−exp(-dt/τ)).

    The value realized by holding `heat` for `dt` frames. As dt→∞ it converges to `heat·τ` — a single
    deposit's total lifetime payout is finite (`rest_mass·τ`), so value is conserved, not conjured;
    what rewards frequency is having many deposits, not one that pays forever. It is the closed-form
    integral of the same `prism.law.cool` curve this module's `cool` decays along, so stock and its
    realised area cannot describe different physics. dt clamped ≥0 (a backwards clock earns nothing)."""
    return _law.cooled_integral(heat, dt_frames, tau=tau)


def accrue(heat: float, last_frame: int, now: int, earned: float,
           *, tau: Optional[float] = None) -> float:
    """Advance the realized-value integral from `last_frame` to `now` (no deposit): add the area the
    standing `heat` sweeps out over that span. **Monotone non-decreasing** — realized value is never
    un-earned, the accounting counterpart of the 2nd law only ever dissipating the stock.

    With no measured clock nothing new accrues, and what was already earned is untouched. `earned`
    is the realized value of holding heat under demurrage, so with no measured rate there is no
    basis to realize it against: accruing would mint value on an unmeasured clock (the undecayed
    integral `heat·dt` is unbounded) and zeroing would destroy value already realized. Carrying it
    forward asserts neither. The gap is not back-filled when a rate later resolves, so a span nobody
    could price stays unpriced."""
    t = _tau(tau)
    prior = max(0.0, float(earned))
    return prior if t is None else prior + _integral(heat, now - last_frame, t)


def deposit(heat: float, last_frame: int, now: int, rest_mass: float,
            *, work: float = 1.0, tau: Optional[float] = None) -> Tuple[float, int]:
    """Record useful work at frame `now`: cool the standing heat to now, then add a deposit of
    `rest_mass · work`. Returns `(new_heat, now)` to store back. **No arbitrary ceiling** — the
    accumulator is left honest; the bound on repetition is a derived quantity, not a hand-set clamp.

    Two things set the deposit, and only the first is settled here:

    * **`rest_mass`** sizes it — a unit of work on a human-validated artifact is worth more than the
      same work on a hypothesis: *you cannot mint energy faster than provenance permits*
      (`inertial-learning`). A ghost (rest_mass ~0) deposits ~0, so belief's anti-laundering carries
      straight into value at the per-event level.

    * **`work` ∈ (0, 1]** is the independence of this consumption event, and it is the seam through
      which repetition is bounded. The same consumer calling `record_use` repeatedly is an echo
      rather than evidence — the same failure `prism.attestation` guards against by counting
      distinct origins rather than repeated observations: a replica of one origin adds nothing to
      the count. A caller measuring the independence of the consumer set (distinct principals or
      contexts) hands it in here, and repeated self-consumption derives `work → 0` and adds nothing.
      `work` defaults to 1.0, the un-derived reading, rather than being clamped."""
    rm = max(0.0, float(rest_mass))
    w = max(0.0, min(1.0, float(work)))
    cooled = cool(heat, last_frame, now, tau=tau)
    return (cooled + rm * w, int(now))


# ── artifact-level helpers: energy rides in context, copies never mutate (mass.stamp discipline) ────
def _read_ctx(artifact: dict) -> dict:
    ctx = artifact.get("context")
    if isinstance(ctx, str):
        import json
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = None
    return dict(ctx) if isinstance(ctx, dict) else {}


def _num(v, default: float) -> float:
    """A finite float, or `default`. bool is an int subclass but is never a reading; NaN/inf are
    poison in an accumulator and are rejected too."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    f = float(v)
    return f if math.isfinite(f) else default


# Rest mass is an argument here, never looked up. Mass is counted by `prism.attestation` — how many
# independent origins attest an artifact — and this module holds the demurrage law rather than the
# measurement layer, so whoever measured the mass supplies it ([[measurement-through-beam]]).
#
# It is required rather than defaulted to zero. A caller that does not know the mass says so and
# gets `None` back, because "this artifact has no attested mass" and "this artifact's mass was never
# measured" are different facts ([[absence-is-not-an-observation-of-zero]]). A zero default would
# size every unmeasured deposit at zero and report a corpus doing no work.


def energy(artifact: dict, now: int, *, tau: Optional[float] = None) -> float:
    """The live economic energy of an artifact at frame `now`: its standing heat, demurraged.

    Zero for anything never consumed (no `energy_heat`) or long untouched, so holding an artifact
    earns nothing on its own. Orthogonal to belief: `mass.provenance_of(artifact)` is untouched and
    still says how it was obtained."""
    ctx = _read_ctx(artifact)
    heat = ctx.get(HEAT_FIELD)
    frame = ctx.get(FRAME_FIELD)
    # bool is an int subclass; a stored True/False (or NaN/inf) is not a reading.
    if isinstance(heat, bool) or not isinstance(heat, (int, float)) or not math.isfinite(float(heat)) \
            or isinstance(frame, bool) or not isinstance(frame, (int, float)):
        return 0.0
    return round(cool(float(heat), int(frame), now, tau=tau), 6)   # honest accumulator, no arbitrary cap


def witness(artifact: dict, now: int, *, rest_mass: float,
            work: float = 1.0, tau: Optional[float] = None) -> dict:
    """Record that `artifact` did useful work at frame `now` — the write half of the meter.

    Returns a copy with the accumulator advanced (cool-then-deposit); the input is untouched, the
    same immutability discipline as `mass.stamp`. `work` is the consumption event's independence
    (see `deposit`). Wire this into `evolution.record_use`, the consumption event.

    `rest_mass` is required. The deposit is sized by the artifact's measured mass
    (`prism.attestation`: independent origins attesting it), which only the caller holding the
    ledger can supply."""
    rm = max(0.0, float(rest_mass))
    ctx = _read_ctx(artifact)
    h0 = _num(ctx.get(HEAT_FIELD), 0.0)
    f0 = int(_num(ctx.get(FRAME_FIELD), float(now)))
    e0 = _num(ctx.get(EARNED_FIELD), 0.0)
    # Settle the realized-value integral over [f0, now] on the old heat, then deposit — so the
    # integral follows the exact curve the heat traces, and the new work only earns going forward.
    earned_now = accrue(h0, f0, now, e0, tau=tau)
    new_heat, new_frame = deposit(h0, f0, now, rm, work=work, tau=tau)
    ctx[HEAT_FIELD] = round(new_heat, 6)
    ctx[FRAME_FIELD] = int(new_frame)
    ctx[EARNED_FIELD] = round(earned_now, 6)
    out = dict(artifact)
    out["context"] = ctx
    return out


def earned(artifact: dict, now: int, *, tau: Optional[float] = None) -> float:
    """Total value realized by this artifact through frame `now` — the settlement basis (the P7
    payout, and what a producer/observer is actually paid for the work their artifact did).

    The time-integral of `energy`, advanced to `now` from the last settled frame. Properties that
    make it a currency rather than a score:

    * **Monotone non-decreasing** — what is earned stays earned; only the live stock (`energy`)
      dissipates.
    * **Rewards frequency, unbounded in genuine work** — N independent deposits earn ≈ N·rest_mass·τ.
    * **Spam-proof without a cap** — a repeat by the same consumer derives `work→0`, deposits 0 heat,
      and adds 0 area. The `work`-independence seam (see `deposit`) does the bounding.
    * **Never touches belief** — `mass.provenance_of` is untouched, as for `energy`."""
    ctx = _read_ctx(artifact)
    heat = ctx.get(HEAT_FIELD)
    frame = ctx.get(FRAME_FIELD)
    e0 = _num(ctx.get(EARNED_FIELD), 0.0)
    if not isinstance(heat, (int, float)) or isinstance(heat, bool) \
            or not isinstance(frame, (int, float)) or isinstance(frame, bool):
        return round(e0, 6)                          # nothing standing to integrate; return what's booked
    return round(accrue(float(heat), int(frame), now, e0, tau=tau), 6)


# ── the heat reading, continuous and discrete ─────────────────────────────────────────────────────
def warmth(artifact: dict, now: int, *, rest_mass: Optional[float] = None,
           tau: Optional[float] = None) -> Optional[float]:
    """The continuous heat reading, with no constants in it.

    The artifact's standing energy as a fraction of its own rest mass: `energy / rest_mass`.
    Scale-free across rungs by construction, since it is measured against the artifact's own deposit
    size rather than an absolute level. 1.0 means it is carrying a full fresh deposit's worth of
    heat; 0.0 means it has fully dissipated.

    `None` when there is no rest mass to measure against — nothing attests it, so the ratio does not
    exist. That is an absence rather than a zero: "this artifact has no attested mass" and "this
    artifact has cooled to nothing" are different statements
    ([[absence-is-not-an-affirmative-claim]]). Passing no `rest_mass` reads the same way, because an
    unmeasured scale and an absent one both mean the ratio does not exist.

    Prefer this to `temperature`. A caller that needs a triage state derives it from a boundary it
    measured and can state."""
    if rest_mass is None:
        return None
    rm = float(rest_mass)
    if not (rm > 0.0):
        return None
    return energy(artifact, now, tau=tau) / rm


def temperature(artifact: dict, now: int, *, rest_mass: Optional[float] = None,
                tau: Optional[float] = None) -> str:
    """`hot` (freshly/frequently worked) · `warm` (cooling) · `cold` (dissipated, worthless to hold).

    A reported triage hint, published by `chorus/ophan/server.py` on its API surface. It is not a
    gate: the band edges `0.5 · rm` and `0.05 · rm` are cut points on the continuous reading rather
    than measured boundaries, and `cold` covers both an unattested artifact and a fully-dissipated
    one. Gate on `warmth()` above, which is constant-free and keeps those two cases apart as `None`
    and `0.0`.

    The scale is the artifact's own rest mass, so the bands are relative rather than absolute and a
    high-provenance artifact does not clear them automatically. `rest_mass is None` reads as `cold`
    because nothing attests the artifact, so there is no scale to measure heat against."""
    if rest_mass is None:
        return "cold"                  # nothing attests it; no scale, so nothing to be warm against
    rm = float(rest_mass)
    if not (rm > 0.0):
        return "cold"
    e = energy(artifact, now, tau=tau)
    if e >= 0.5 * rm:
        return "hot"
    if e >= 0.05 * rm:
        return "warm"
    return "cold"


__all__ = ["set_slow_rate_source", "slow_rate", "tau_now", "warmth",
           "HEAT_FIELD", "FRAME_FIELD", "EARNED_FIELD",
           "cool", "deposit", "accrue", "energy", "earned", "witness", "temperature"]
