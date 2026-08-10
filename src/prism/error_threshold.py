"""The error threshold — Eigen's constraint, made observable (MANTLE-LEARNING.md §2).

Above a critical mutation rate a genome dissolves: information is destroyed faster than
selection preserves it (**error catastrophe**). The corpus has the same failure mode — ungated
generation makes a denser junk drawer, and the system gets *dumber* the more it produces. The
biology turns the warning into a law with a number in it:

> **You cannot mine faster than you can verify.** If low-mass writes arrive faster than the gates
> (citation, corroboration, human validation, eviction) can absorb them, the validated fraction
> of the corpus falls monotonically. That is error catastrophe, and it is currently invisible —
> you would discover it by noticing the corpus had already rotted.

This module is the meter. It is a **flow balance**, not a tuned model: over an observation
window, artifacts are *minted dark* (a new ghost / unknown / hypothesis — mutation load) and the
gates *clear* some of the standing dark pool by either **promoting** it to real mass or
**evicting** it (stale, demoted, GC'd). The ratio of clearing to minting is the whole story, and
its critical value is **exactly 1.0** — a conservation boundary, not a fitted constant.

What is physical vs advisory
----------------------------
* `CRITICAL_RATIO = 1.0` is **physical**: below it the dark pool grows without bound relative to
  validated content. There is nothing to tune.
* `STRAIN_RATIO` (a margin above 1.0) is **advisory**: a warning band so "approaching" is visible
  *before* "over". It is a chosen constant, and the only chosen number here.

The signals it consumes exist per-artifact: an artifact that lands ungrounded is minted dark
(`prism.attestation.Ledger.read()` is `None`, or the provenance channel has no referent);
`provenance_history` records a promotion; stale, demoted and GC'd artifacts are evictions. The
aggregation is what this module adds. Wiring it to live counters is a Mantle concern (a handoff),
because the counts come from the write/describe/GC paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


CRITICAL_RATIO = 1.0     # Physical: clearing at least matches minting, or the pool grows.
# `STRAIN_RATIO` is the one chosen number in this file. `CRITICAL_RATIO = 1.0` is different in kind:
# it is a conservation boundary — clearing matches minting, or the dark pool grows without bound —
# and it is exactly 1 by the arithmetic of a ratio. The comparison it expresses is `x >= 1`.
#
# A warning margin has no derivation. "How much headroom before I want to be told" is a question
# about attention rather than about the corpus, and nothing measures it. The constant-free reading
# is already on this dataclass and is strictly more informative: `validation_ratio` is the continuous
# amplitude, and a reader watching it approach 1.0 sees strain coming with no band at all.
#
# `STRAIN_RATIO` stands because `Health.STRAINED` is a published enum member consumed outside this
# lane (`ember/runtime/worker.py` tallies windows into it). `STRAINED` is a hint; the gate is
# `CRITICAL_RATIO`.
STRAIN_RATIO = 1.25      # Chosen — see the note above. Advisory; the gate is CRITICAL_RATIO.


class Health(str, Enum):
    """The corpus's standing relative to the error threshold."""

    STABLE = "stable"            # clearing outpaces minting comfortably
    STRAINED = "strained"        # keeping pace, but with little margin — a leading warning
    CATASTROPHE = "catastrophe"  # minting outpaces clearing: the validated fraction is falling
    IDLE = "idle"                # no dark matter minted this window — nothing to balance


@dataclass(frozen=True)
class FlowWindow:
    """What happened to the corpus over one observation window.

    Deliberately just counts — the meter tallies the events the write/describe/GC paths already
    produce and leaves artifact state to be derived elsewhere. A window can be a minute, a day, or
    N writes; the ratio is scale-free.
    """

    minted_dark: int = 0     # new artifacts entering the low-mass/dark pool (mutation load)
    promoted: int = 0        # dark artifacts that climbed to real mass (a gate absorbed them)
    evicted: int = 0         # dark artifacts removed (stale / demoted / GC'd — also absorption)
    total_writes: int = 0    # all writes this window (for context: the mutation *fraction*)

    @property
    def cleared(self) -> int:
        """Dark matter the gates removed from the pool, by either route. Promotion and eviction
        are the same thing to the balance: both shrink the unvalidated pool."""
        return self.promoted + self.evicted

    @property
    def mutation_fraction(self) -> float:
        """Share of this window's writes that entered dark. Context, not the verdict — a high
        fraction is fine if clearing keeps up (a healthy corpus can mint a lot of hypotheses)."""
        return (self.minted_dark / self.total_writes) if self.total_writes else 0.0

    @property
    def validation_ratio(self) -> float:
        """cleared / minted_dark — the whole story. >= 1 shrinks (or holds) the pool; < 1 grows
        it. Infinite when nothing was minted (vacuously fine); that case is reported as IDLE."""
        if self.minted_dark == 0:
            return float("inf")
        return self.cleared / self.minted_dark

    @property
    def health(self) -> Health:
        if self.minted_dark == 0:
            return Health.IDLE
        r = self.validation_ratio
        if r < CRITICAL_RATIO:
            return Health.CATASTROPHE
        if r < STRAIN_RATIO:
            return Health.STRAINED
        return Health.STABLE

    @property
    def max_sustainable_mint(self) -> int:
        """The mining ceiling this window's validation throughput can support: you cannot mint
        more dark matter than you cleared and stay subcritical. 'Mine no faster than you verify'
        is literally ``minted_dark <= cleared``."""
        return self.cleared


def assess(*windows: FlowWindow) -> Health:
    """Health over one or several windows summed — a single window is noisy; a trend is the
    honest read. Summing counts (not averaging ratios) is correct: the balance is over the
    pooled flows, and averaging ratios would let one quiet window mask a catastrophic one."""
    total = FlowWindow(
        minted_dark=sum(w.minted_dark for w in windows),
        promoted=sum(w.promoted for w in windows),
        evicted=sum(w.evicted for w in windows),
        total_writes=sum(w.total_writes for w in windows),
    )
    return total.health


def is_supercritical(*windows: FlowWindow) -> bool:
    """True when the corpus is minting dark matter faster than it clears it — the actionable
    alarm. Distinct from IDLE (nothing minted) and STRAINED (keeping pace, thin margin)."""
    return assess(*windows) is Health.CATASTROPHE


__all__ = [
    "Health", "FlowWindow", "assess", "is_supercritical",
    "CRITICAL_RATIO", "STRAIN_RATIO",
]
