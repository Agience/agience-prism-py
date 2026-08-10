"""The 0 → 1 → 0 certificate — does a signal's whole journey conserve, or does it leak?

This is how an energy system or an emergent system is certified as balanced: whatever goes in
eventually comes out, travelling 0 → 1 → 0 without loss.

`absorb_transmit` conserves at a single membrane: the projector onto the resolved subspace is
orthogonal, so `‖incident‖² = ‖absorbed‖² + ‖transmitted‖²` exactly, per hop. That is the local
statement. A path can conserve at every individual boundary and still lose everything — each hop
hands on a residual that is exactly right, and then the last one is dropped on the floor. Every
local check passes; the energy is gone.

The global statement. A signal enters with energy `E₀ = ‖incident‖²`. Each element absorbs a band
and transmits the rest, so after N elements

    E₀ = Σᵢ ‖aᵢ‖²  +  ‖r_N‖²

Normalise by E₀ and the whole journey is two numbers moving in opposite directions: the cumulative
absorbed fraction climbing 0 → 1, and the residual falling 1 → 0. Balance is the claim that they
sum to exactly one *at every prefix*:

    ∀k:   Σ_{i≤k} αᵢ  +  ρ_k  =  1          where αᵢ = ‖aᵢ‖²/E₀ ,  ρ_k = ‖r_k‖²/E₀

Checking only the endpoints would accept a path that loses energy at hop 3 and manufactures it at
hop 7. The prefix identity is what makes the certificate a certificate.

Termination is where the teeth are. `Σα = 1` is the definition of having finished. A path that stops
while `ρ_N > 0` has a residual that was absorbed by nothing and handed back to no one, and that
residual is the loss. Every per-hop check passes over it, and it looks exactly like a working system:
answers come out, each membrane's arithmetic is exact, and a fraction of every signal evaporates at
the end of the line. Naming it is what this module is for.

So a path closes in exactly one of two ways, and it does one of them:
  · `absorb()` until the residual is zero          — everything was consumed by the elements, or
  · `emit()`                                        — the residual leaves as output, accounted for.
Anything else is `balanced == False`, and `loss` says how much.

The tolerance is derived. Comparing float sums to 1.0 needs a bound, and the bound here is the
standard forward-error bound for floating-point summation: recursively summing `n` non-negative
terms carries error at most `(n−1)·ε·Σ`, and each `‖X‖²` is itself a sum of `m` products carrying
error at most `m·ε·‖X‖²`. Both are counted as the path is walked, so the tolerance is a property of
the arithmetic actually performed — a longer path earns a wider band, and it widens by exactly the
amount the extra additions can be wrong by. `ε` is the machine epsilon of the frame's own dtype.

The law itself is `prism.rounding.accumulated_rounding`, in the dependency-free base; this module
counts the operations and reads the dtype. The error model that law assumes — accumulation, valid
because every term is a `‖·‖²` and therefore non-negative — is stated once, where the arithmetic is.
`conservation` sits behind `[wire]` because it needs numpy, which is why the law lives on the base:
a component running on numpy alone reaches `prism.rounding` directly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .rounding import accumulated_rounding

__all__ = ["PathLedger", "energy", "certify"]


def energy(frame: Any) -> float:
    """The energy of a frame: `‖frame‖²`, the sum of squares over every element.

    `None` — silence, a frame that never formed — is 0.0 energy. Silence is a real state that stays
    accountable: a path whose incident signal is silence conserves trivially, and the certificate
    says so."""
    if frame is None:
        return 0.0
    a = np.asarray(frame, dtype=float)
    if a.size == 0:
        return 0.0
    return float((a * a).sum())


def _elements(frame: Any) -> int:
    """How many products the energy sum performed — the `m` in the error bound."""
    if frame is None:
        return 0
    return int(np.asarray(frame).size)


class PathLedger:
    """The running account of one signal's journey through a path of absorbing elements.

    Open it on the incident frame, `absorb()` at each element the signal crosses, and close it with
    `emit()` if a residual leaves as output. `certificate()` is the verdict. The frames are read and
    left alone: this is a measurement of a propagation that already happened.

        led = PathLedger(incident, at="need")
        for element in path:
            absorbed, transmitted, k = absorb_transmit(carried, ...)
            led.absorb(absorbed, transmitted, at=element.name)
            carried = transmitted
        led.emit(at="answer")            # the residual is handed back, not dropped
        cert = led.certificate()
        assert cert["balanced"], cert["why"]
    """

    __slots__ = ("_e0", "_hops", "_terms", "_elems", "_eps", "_residual", "_emitted",
                 "_emitted_at", "_origin")

    def __init__(self, incident: Any, *, at: Optional[str] = None) -> None:
        a = None if incident is None else np.asarray(incident, dtype=float)
        self._eps = float(np.finfo(a.dtype).eps) if a is not None and a.size else float(np.finfo(float).eps)
        self._e0 = energy(a)
        self._origin = at
        self._hops: List[Dict[str, Any]] = []
        self._residual = self._e0          # what is still travelling, in absolute energy
        self._emitted: Optional[float] = None
        self._emitted_at: Optional[str] = None
        # Error accounting: every product and every addition this ledger will be judged on.
        self._terms = 1
        self._elems = _elements(a)

    # ── recording ────────────────────────────────────────────────────────────────────────────
    def absorb(self, absorbed: Any, transmitted: Any, *, at: Optional[str] = None,
               k: Optional[int] = None) -> "PathLedger":
        """Record one element's split of the signal it received.

        Pass the frames `absorb_transmit` returned. The ledger measures the frames themselves, so a
        membrane that miscomputes its own split is caught: a reported number would carry the same
        error as the split it describes, and the discrepancy would vanish."""
        ea, et = energy(absorbed), energy(transmitted)
        incident_here = self._residual
        self._hops.append({
            "at": at,
            "k": k,
            "absorbed": ea,
            "transmitted": et,
            # The local check, kept per hop so a break can be located as well as detected.
            "incident": incident_here,
            "local_loss": incident_here - (ea + et),
        })
        self._residual = et
        self._terms += 3
        self._elems += _elements(absorbed) + _elements(transmitted)
        return self

    def emit(self, *, at: Optional[str] = None) -> "PathLedger":
        """Close the path: the residual still travelling leaves as output and is accounted for.

        This is the second of the two legitimate endings. Calling it is a claim — that whatever
        `transmitted` remains was handed to a caller — so it is recorded as a distinct outcome from
        "the elements absorbed everything"."""
        self._emitted = self._residual
        self._emitted_at = at
        return self

    # ── the verdict ──────────────────────────────────────────────────────────────────────────
    @property
    def tolerance(self) -> float:
        """The derived error band, in absolute energy. See the module docstring.

        The counting is this ledger's — it knows how many frames it measured and how big each was —
        and the law is `prism.rounding`'s. `_e0` is a sum of squares, so the accumulation model the
        law assumes holds here by construction; a ledger opened on a quantity that can cancel would
        be using the wrong bound however carefully it counted."""
        return accumulated_rounding(self._terms + self._elems, self._e0, self._eps)

    def certificate(self) -> Dict[str, Any]:
        """The full 0 → 1 → 0 account, and whether it closes.

        Keys: `incident` (E₀), `absorbed` (Σ), `emitted`, `unaccounted`, `loss`, `tolerance`,
        `closed` (the prefix identity holds at every hop), `terminated` (the path ended legitimately),
        `balanced` (both), `curve` (the 0→1→0 pair per hop), `why` (what failed, when it did).

        A zero-energy path is balanced by construction and says so — with `incident == 0` there is
        nothing to lose, and silence reads as silence rather than as a leak."""
        tol = self.tolerance
        absorbed_total = float(sum(h["absorbed"] for h in self._hops))

        # ── the prefix identity, checked at every hop ────────────────────────────────────────
        curve: List[Dict[str, Any]] = []
        closed = True
        broke_at: Optional[int] = None
        running = 0.0
        for i, h in enumerate(self._hops):
            running += h["absorbed"]
            # Σ_{i≤k} aᵢ + r_k must equal E₀ — in absolute energy, so the check stays defined on a
            # silent path where E₀ is zero.
            defect = self._e0 - (running + h["transmitted"])
            if abs(defect) > tol:
                closed = False
                if broke_at is None:
                    broke_at = i
            curve.append({
                "at": h["at"],
                "cumulative": (running / self._e0) if self._e0 else 0.0,   # the 0 → 1 side
                "residual": (h["transmitted"] / self._e0) if self._e0 else 0.0,  # the 1 → 0 side
                "defect": defect,
            })

        # ── termination: absorbed to nothing, or emitted ─────────────────────────────────────
        if self._emitted is not None:
            unaccounted = 0.0
            terminated = True
        else:
            unaccounted = self._residual
            terminated = abs(self._residual) <= tol

        loss = self._e0 - (absorbed_total + (self._emitted if self._emitted is not None
                                             else self._residual))
        balanced = bool(closed and terminated and abs(loss) <= tol)

        why = None
        if not closed:
            h = self._hops[broke_at]
            why = ("prefix identity broke at hop %d (%s): cumulative absorbed + residual differs "
                   "from incident by %.6g, outside the derived band %.6g"
                   % (broke_at, h["at"], curve[broke_at]["defect"], tol))
        elif not terminated:
            why = ("path ended with %.6g of %.6g energy still travelling (%.2f%%) and never emitted "
                   "— that residual was absorbed by nothing and returned to no one"
                   % (self._residual, self._e0,
                      100.0 * self._residual / self._e0 if self._e0 else 0.0))
        elif abs(loss) > tol:
            why = ("energy is not conserved end to end: %.6g unaccounted against a derived band "
                   "of %.6g" % (loss, tol))

        return {
            "incident": self._e0,
            "origin": self._origin,
            "hops": len(self._hops),
            "absorbed": absorbed_total,
            "emitted": self._emitted,
            "emitted_at": self._emitted_at,
            "unaccounted": unaccounted,
            "loss": loss,
            "tolerance": tol,
            "closed": closed,
            "terminated": terminated,
            "balanced": balanced,
            "curve": curve,
            "why": why,
        }


def certify(incident: Any, splits, *, emitted: bool = False) -> Dict[str, Any]:
    """One-shot certificate over an already-walked path.

    `splits` is an iterable of `(absorbed, transmitted)` or `(absorbed, transmitted, k)` or
    `(at, absorbed, transmitted)` — whatever the caller recorded. `emitted=True` declares the final
    residual was handed back as output."""
    led = PathLedger(incident)
    for s in splits:
        at = k = None
        if len(s) == 2:
            a, t = s
        elif len(s) == 3 and isinstance(s[0], str):
            at, a, t = s
        else:
            a, t, k = s
        led.absorb(a, t, at=at, k=k)
    if emitted:
        led.emit()
    return led.certificate()
