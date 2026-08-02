"""Mass — what an artifact weighs, and why (MANTLE-MASS.md).

⚠ MOVED FROM `beam.mass` TO PRISM ON 2026-07-31. It is a CONTRACT, not a measurement: provenance
rungs, `Weight`, `Revision` and the `may_revise` rule are the vocabulary every layer must agree on
before anything can be weighed. Pure stdlib — dataclasses, enum, typing — so it lands in prism's
dependency-free contract core and costs nobody anything.

The move was forced by the declared layering, and the audit that found it is worth recording:
`agience-beam/tests/test_dependency_dag.py` says mantle may reach only origin and prism —
**mantle must not import beam** — yet mantle's shard and mesh need exactly this module
(`shard/cache.py`, `shard/local_collection.py`, `mesh/mantle_bridge.py`). beam and mantle are
SIBLINGS, not a stack, so a shared vocabulary between them cannot live in either; it has to sit
below both. That is what prism is.

Its own specification is MANTLE-MASS.md — the store's document — which is the tell that this was
never beam's to own.

A new artifact is **dark matter**: mass, a timestamp, no edges. It embeds, it lands in a cell,
it bends routing — before anything can be reasoned about it.

THE LOAD-BEARING RULE
---------------------
**An embedding is not mass.** Every string embeds; anything written down acquires coordinates.
If mass meant "has an embedding" then every hallucination would be dark matter, and this model
would legitimise precisely what it exists to prevent. Dark matter's *defining* property is that
its mass is **real** — measurable, which is how we know it is there at all.

So mass is a function of **how an item was obtained** (its provenance rung), never of the fact
that it exists. A bare model assertion has coordinates and ~zero mass: it is not dark matter,
it is a **ghost** — noise with a position.

This module is deliberately dependency-free (stdlib only) and lives in `core` so that the
server and the leaf weigh artifacts **identically** — if Mantle and Ember disagreed about what
a thing weighs, belief would fork at the edge and the whole model would be decorative. It
computes `ShardItem.consensus`, which `MANTLE-MESH.md` already specifies as the "provenance
weight".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Provenance(str, Enum):
    """How an item was obtained. First-class: promotion depends on the rung, not the content.

    Ordered by how much trust each rung requires. The model's role differs at every rung —
    parser, proposer, generator, oracle — and only the last one is disallowed as a basis for
    belief. The model may say where to look and what things are called; it may not be the
    reason you believe something.
    """

    HUMAN_VALIDATED = "human_validated"      # a person staked a claim on it
    OBSERVED = "observed"                    # an instrument / system of record
    SPAN_CITED = "span_cited"                # extracted FROM a source; provenance is the doc
    ONTOLOGY_PROPOSAL = "ontology_proposal"  # a proposed anchor; the density gate validates it
    HYPOTHESIS = "hypothesis"                # a distilled prior, no citable span
    UNKNOWN = "unknown"                      # provenance was never recorded — see below
    ASSERTION = "assertion"                  # "the model said so" — marked, never believed


# The provenance anchor for SYSTEM-authored artifacts (the ontology, operators, collections, and
# the citations themselves). GENESIS §12: NO artifact without provenance — every artifact carries
# a `cited_from`. Ingested artifacts cite their source (`cite.<dataset>`); system artifacts cite
# this. It is HUMAN_VALIDATED and self-anchored.
#
# It lives HERE, beside the ladder, because it is the same law: `Provenance` says what rungs
# exist, this says what a system artifact's citation IS. It was previously a literal in
# `ember/grounding.py` — a runner's module — which put the law downstream of a runtime and made
# every reader that needed it import one. (`ember.grounding` re-exports this name, so its callers
# are unchanged; this is now the definition, not a copy.)
CITE_GENESIS = "cite.genesis"


# (base, ceiling) per rung. The gap between SPAN_CITED and HYPOTHESIS is deliberate and large:
# one has a checkable referent, the other has none. ASSERTION is not zero only so that it can
# be stored, counted and aged — never so that it can accumulate its way to canonical.
#
# THE LADDER INVARIANT: every rung's CEILING sits strictly below the next rung's BASE. So no
# amount of corroboration, coherence or luck can lift an item into a higher rung's territory.
# Corroboration strengthens a claim *within its band*; it never re-rungs it.
#
# The path upward still exists — it just isn't volume. An item climbs by acquiring better
# PROVENANCE: a hypothesis that earns a citation becomes SPAN_CITED and is re-weighed there.
# That is the point: belief follows how a thing was obtained, not how often it was repeated.
# (Without this, 8 corroborated guesses outweighed a direct observation — laundering via
# corroboration rather than via assertion. Same disease, different door.)
# ══════════════════════════════════════════════════════════════════════════════════════════════
# ⛔ AUDIT 2026-08-01 — EVERY MAGNITUDE BELOW IS UNDEFENDED. ORDERING IS DECLARED; VALUES ARE NOT.
# ══════════════════════════════════════════════════════════════════════════════════════════════
# [John, 2026-08-01: *"NO PREDETERMINATION"* / *"GET RID OF THE CONSTANTS"*.] The commentary above
# defends the ORDER of the rungs and the LADDER INVARIANT (each ceiling strictly below the next
# base), and both of those are declared semantics — legitimate, and they survive. It defends no
# single NUMBER, and there are fourteen of them here, plus `GHOST_FLOOR`, `DARK_AGE_FRAMES`, and the
# five coefficients in `weigh` (`0.6 ** min(corroborations, 8)`, `0.5 + 0.5·clumping`, `*= 0.5`,
# `max(0.5, min(1.25, 1.0 + 0.25·coherence))`). Nothing measures any of them. They ARE the belief
# scale, so every downstream "measured" mass in the system inherits them.
#
# ⭐ THE DERIVATION THAT REPLACES THEM, STATED EXACTLY SO IT CAN BE APPLIED. The declared facts are:
# (a) `CLAIM_LADDER` is a total order over N rungs; (b) each rung's ceiling sits strictly below the
# next rung's base; (c) mass lies in [0, 1]. Those three determine the bands UNIQUELY once one adds
# the only honest statement about the gaps — that nothing is known to distinguish them. Partition
# [0, 1] into N equal, ordered, non-overlapping intervals by ladder index: rung `i` of `N` (0 =
# best) occupies `[(N−1−i)/N, (N−i)/N]`. No magnitude is chosen; spacing follows from the ordering
# and from having no further information (the maximum-entropy assignment). Corroboration then moves
# mass WITHIN a band, which it already does, and the ladder invariant holds by construction rather
# than by fourteen hand-checked numbers. `GHOST_FLOOR` becomes the top of the lowest band — a
# CONSEQUENCE of the partition, not a sixteenth constant.
#
# ⚠ IT IS NOT APPLIED IN THIS AUDIT, AND THAT IS A SCOPE JUDGEMENT, NOT A DEFENCE OF THE NUMBERS.
# Changing these re-prices EVERY artifact already written — mass is persisted and compared, so this
# is a corpus migration with a re-weigh pass, not an edit to a formula. Applying it unilaterally
# from the beam/prism lane would silently move every stored belief while three other lanes are
# mid-flight in the same tree. It needs to land as its own change, with the re-weigh, together.
# Recorded here so the next reader inherits the derivation and not the numbers' apparent authority.
#
# ⚠ `DARK_AGE_FRAMES = 64` IS THE WEAKEST OF ALL AND HAS ITS OWN ANSWER. It is a TIME, and the
# system now measures its own timescales (`beam.demurrage.slow_rate`, the screen's measured decay
# — 13.02 / 14.85 / 14.24 / 81.56 / 91.04 on live streams and conversations, never 64). An age gate
# should read that measurement and hold NO number; where nothing has measured a rate, the honest
# reading is that nothing is stale yet, exactly as `demurrage` now carries heat forward undecayed.
_BANDS: dict[Provenance, tuple[float, float]] = {
    Provenance.HUMAN_VALIDATED: (1.00, 1.00),
    Provenance.OBSERVED: (0.90, 0.98),
    Provenance.SPAN_CITED: (0.75, 0.88),
    Provenance.HYPOTHESIS: (0.20, 0.55),          # never past a cited claim's floor
    Provenance.UNKNOWN: (0.12, 0.18),             # unlabeled — weak, but NOT a ghost
    Provenance.ASSERTION: (0.02, 0.02),           # a ghost's floor IS its ceiling
    Provenance.ONTOLOGY_PROPOSAL: (0.30, 0.70),   # OFF-LADDER — see below
}

# UNKNOWN is where every artifact written before provenance was recorded lands, and it sits
# BELOW hypothesis deliberately: with a hypothesis you at least know what you are holding.
# It stays ABOVE GHOST_FLOOR because "we never wrote down where this came from" is not the
# same claim as "a model made this up" — unlabeled is not fabricated, and conflating them
# would slander the corpus instead of describing it. The fix is migration, not judgement:
# label an artifact and it is re-weighed on its real rung.

# QUEUED — a `proof_checked` rung (Lean/machine-checked derivation). NOT simply "above 1.0":
# a proof certifies the DERIVATION, not the INTERPRETATION — a wrong formalisation proves a true
# theorem about the wrong thing. So proof_checked and human_validated are complementary, not
# ordered (kernel certifies the step; a person certifies the statement says what was meant).
# It may want OFF_LADDER treatment, like ontology_proposal — which the invariant test forced,
# and this smells the same. See memory: first-domains-and-vscode.
#
# The ladder is over CLAIMS: "why should I believe this?". Totally ordered, invariant enforced.
CLAIM_LADDER: tuple[Provenance, ...] = (
    Provenance.HUMAN_VALIDATED,
    Provenance.OBSERVED,
    Provenance.SPAN_CITED,
    Provenance.HYPOTHESIS,
    Provenance.UNKNOWN,
    Provenance.ASSERTION,
)

# ONTOLOGY_PROPOSAL is deliberately NOT on that ladder. It answers a different question —
# "does this coordinate exist?" — and is validated by a different mechanism: the density gate
# (does real data clump here?), not corroboration. Ranking "this concept exists" against "this
# statement is true" would invent an ordering that means nothing, and would then leak into
# consensus as if it did. Anchors have their own promotion axis (CANDIDATE → WORKING →
# CANONICAL in anchors/anchorset.py); this rung exists so a proposal can be weighed and aged
# like anything else, not so it can be compared to a claim.
OFF_LADDER: frozenset[Provenance] = frozenset({Provenance.ONTOLOGY_PROPOSAL})

# A rung that cannot promote itself no matter how much corroboration is claimed for it.
# Corroboration of an assertion by more assertions is not evidence, it is an echo.
_NEVER_SELF_PROMOTING = {Provenance.ASSERTION}

GHOST_FLOOR = 0.10        # at/below this, mass is not real: a position without substance
DARK_AGE_FRAMES = 64      # unlinked for this long without clumping => suspicious (see §5)


@dataclass(frozen=True)
class Weight:
    """The computed mass of an item, and the reading that follows from it."""

    mass: float
    provenance: Provenance
    edges: int
    age_frames: int
    clumped: bool
    # The continuous reading behind `clumped`, when the caller had one. `None` means the
    # caller only had the boolean — which is honest, not a zero. Defaulted so every existing
    # construction of `Weight` keeps working unchanged.
    clumping: Optional[float] = None

    @property
    def _did_clump(self) -> bool:
        """The clumping reading as a boolean, preferring the continuous channel.

        `clumped` is `entroptics has_signal`, which is literally `k_signal > 0` — ANY
        resolved mode above the noise floor. So the boolean reading of a continuous
        clumping degree is `> 0.0`, not a threshold anyone has to invent. When only the
        boolean was supplied, it is used directly.
        """
        if self.clumping is not None:
            return float(self.clumping) > 0.0
        return self.clumped

    @property
    def ghost(self) -> bool:
        """Coordinates without substance. Not dark matter — noise that happens to embed."""
        return self.mass <= GHOST_FLOOR

    @property
    def dark(self) -> bool:
        """Real mass, no edges yet: corroborated but unexplained. The valuable state."""
        return not self.ghost and self.edges == 0

    @property
    def stale(self) -> bool:
        """The discriminator that only time can supply.

        Without age, "genuinely novel, awaiting corroboration" and "noise nobody confirmed"
        are indistinguishable — both are mass with no edges. Old + edgeless + never clumped
        separates them without anyone adjudicating truth at write time.

        Staleness stays DISCRETE on purpose: it is a triage state ("look at this"), and a
        fractional one would not be actionable. It reads `_did_clump` so a caller that
        supplied a continuous clumping is not treated as never having clumped.
        """
        return self.edges == 0 and not self._did_clump and self.age_frames >= DARK_AGE_FRAMES


def weigh(
    provenance: Provenance,
    *,
    corroborations: int = 0,
    edges: int = 0,
    age_frames: int = 0,
    clumped: bool = False,
    coherence: Optional[float] = None,
    clumping: Optional[float] = None,
) -> Weight:
    """Compute an item's mass.

    Args:
        provenance: the rung it was obtained on. The dominant term, by design.
        corroborations: independent items supporting it. Diminishing, and capped — corroboration
            can strengthen a claim, never re-rung it. Ten citations do not make a hypothesis
            into an observation.
        edges: relations/describers attached. Edges are luminosity, not mass: they make an
            artifact *explicable*, so they do not inflate belief on their own.
        age_frames: frames since placement. Only ever used to *discount*, never to credit —
            surviving a long time is not evidence of anything.
        clumped: whether it coheres with other mass (entroptics `has_signal`). The
            THRESHOLDED reading; supply `clumping` instead when you have the continuous one.
        coherence: optional entroptics lag-1 coherence z-score, folded in gently. NOT the
            continuous companion of `clumped` — see the note at the discount site.
        clumping: optional CONTINUOUS clumping degree in [0, 1], the un-thresholded reading
            behind `clumped`. When supplied it replaces the hard 0.5 cliff with a ramp whose
            endpoints are exactly the old boolean's two outcomes, so nothing moves for a
            caller that has only the boolean.

    Returns:
        A `Weight` carrying the mass and the dark/ghost/stale reading.
    """
    if not isinstance(provenance, Provenance):
        provenance = Provenance(provenance)

    base, ceiling = _BANDS[provenance]
    mass = base

    # Corroboration: diminishing returns, asymptotic to this rung's CEILING — never to 1.0.
    # Lifting toward 1.0 is what let 8 corroborated guesses outweigh a direct observation.
    if corroborations > 0 and provenance not in _NEVER_SELF_PROMOTING:
        mass += (ceiling - base) * (1.0 - (0.6 ** min(corroborations, 8)))

    # Not clumping is evidence AGAINST: real dark matter is gravitationally coherent. Mass
    # that coheres with nothing is not matter. Only applied once there has been time to clump.
    #
    # ⛔ THE CLIFF, AND WHY THE OBVIOUS FIX IS THE WRONG ONE.
    # `clumped` is a boolean, so this was a hard `*= 0.5` step: an item that barely cohered
    # and an item that cohered with nothing at all were discounted identically, and an item
    # a hair the other side of the threshold paid nothing. That IS a real discretisation
    # loss and it is fixed below by accepting the continuous reading.
    #
    # It was proposed that the continuous reading is the `coherence` argument already folded
    # in a few lines down — i.e. that this double-counts a boolean derived from it. MEASURED,
    # IN `beam/optics.py`, THAT IS NOT TRUE. They come off two different doors of the same
    # read and are not thresholded versions of each other:
    #   * `clumped` is `OpticsRead.has_signal`, which is `k_signal > 0` — a count of modes
    #     above the Tracy-Widom edge on the CORRELATION eigenspectrum (`Aperture.spectral`).
    #     Scale-invariant, order-invariant.
    #   * `coherence` is `sc.coherence`, a lag-1 z-score off the ENTROPY-FOLDED Screen — the
    #     door `optics.py` documents as destroying a sparse carrier (measured f_eff 256 -> 1).
    #     It is order-DEPENDENT and is forced to 0.0 whenever it comes back non-finite.
    # Two consequences make the substitution actively unsafe. On the documented cheap path
    # (`read_ordered(..., with_screen=False)`) `coherence` is a hardcoded 0.0 placeholder
    # while `k_signal` is fully valid — so deriving the discount from `coherence` would apply
    # the FULL discount to a frame with real resolved structure. And when `scale_hazard`
    # fires, `coherence` is exactly the number the module says not to trust while `k_signal`
    # is the one it says to band on.
    # So the continuous companion is taken as its own argument, from whoever measured it.
    if age_frames >= DARK_AGE_FRAMES:
        if clumping is not None:
            # Continuous ramp. The endpoints ARE the old boolean: 0.0 -> *0.5 (exactly the
            # old `not clumped` branch), 1.0 -> *1.0 (exactly the old `clumped` branch).
            # Clamped, not scaled, because a degree outside [0, 1] is a caller bug and
            # rescaling one would silently redefine what "fully clumped" means.
            mass *= 0.5 + 0.5 * max(0.0, min(1.0, float(clumping)))
        elif not clumped:
            mass *= 0.5

    if coherence is not None:
        # Gentle: coherence is corroborating structure, not a licence to re-rung.
        mass *= max(0.5, min(1.25, 1.0 + 0.25 * float(coherence)))

    # Clamp to the RUNG's ceiling, not to 1.0 — this is what makes the ladder invariant hold
    # under every combination of inputs, including ones we haven't thought of.
    return Weight(
        mass=round(max(0.0, min(ceiling, mass)), 4),
        provenance=provenance,
        edges=edges,
        age_frames=age_frames,
        clumped=clumped,
        clumping=None if clumping is None else float(clumping),
    )


def surfacable(w: Weight, *, in_workspace: bool) -> bool:
    """May this item answer a query? (MANTLE-MASS.md §1 — the surfacing rule.)

    > **Mass gets you into the geometry. Edges get you into the answers.**

    An unlinked artifact still embeds, still lands in a cell, still bends routing — so it WILL
    be retrieved unless something stops it. This is that something.

    * **in a workspace → always visible.** You can find it because you know where you put it.
      That includes ghosts: hiding your own junk makes it unfixable, and the workspace is where
      a person cleans up (which is also where mass is minted — `MANTLE-LEARNING.md` §6).
    * **unscoped (asking the manifold) → needs real mass AND edges.** Dark matter has not earned
      a place in the answers yet; a ghost never will.

    Note both conditions are required and neither implies the other: `dark` is "real mass, no
    edges", so a ghost is *not* dark — checking only `dark` would let noise-with-coordinates
    answer questions, which is the exact failure this model exists to prevent.
    """
    if in_workspace:
        return True
    return not w.ghost and not w.dark


# Who is asking to write. The rung a caller may claim is bounded by which of these they are —
# a rung is only as trustworthy as the principal that could set it.
HUMAN = "human"          # an authenticated person (e.g. via Facet)
SYSTEM = "system"        # a trusted service principal (crystal, an extraction pipeline)
CLIENT = "client"        # any authenticated caller with no special standing
_PRINCIPAL_KINDS = (HUMAN, SYSTEM, CLIENT)

# The BEST rung each principal kind may assert. Anything a caller claims above its ceiling is
# not rejected — it is quietly demoted to what it has earned (see derive_provenance).
_MAX_CLAIM: dict[str, Provenance] = {
    HUMAN: Provenance.HUMAN_VALIDATED,   # a real person acted — the top of the ladder
    SYSTEM: Provenance.OBSERVED,         # a trusted service; may record observations/proposals
    CLIENT: Provenance.HYPOTHESIS,       # untrusted: may offer a guess, never a grounding
}
# span_cited is special: it is earned by PRESENTING a span, not by being trusted. A system that
# shows its citation may claim it; without the span, even a system caps at OBSERVED's band.


def principal_kind_of(principal_type: str, *, is_delegated: bool) -> str:
    """Classify an auth principal into HUMAN / SYSTEM / CLIENT for provenance authority.

    Kept as plain strings (not an AuthContext) so it lives in `core` without depending on any
    server package — Mantle passes the two fields it reads off its own context.

    The one subtlety, and it is the confused-deputy trap: **a delegation token carries the
    user's `user_id`**, because a persona/bot is acting *on behalf of* a person. So "has a
    user_id" is NOT "a human acted". Only a **direct, non-delegated** interactive user is HUMAN;
    a bot acting for you is a SYSTEM at best. Getting this wrong would let any persona mint
    `human_validated` under your identity — exactly the impersonation the delegation model exists
    to contain.
    """
    if is_delegated:
        # Acting on behalf of a human is not the human acting. A persona is a trusted service,
        # so SYSTEM (it can still record `observed`/proposals), never HUMAN.
        return SYSTEM
    if principal_type == "user":
        return HUMAN
    if principal_type in ("server", "service", "mcp_client"):
        return SYSTEM
    # api_key, grant_key, and anything unrecognised: an authenticated caller with no special
    # standing. Untrusted for provenance — capped at hypothesis.
    return CLIENT


def derive_provenance(claimed, principal_kind: str, *, has_verified_span: bool = False) -> Provenance:
    """The rung a write actually EARNS — derived server-side, never taken on the client's word.

    This is the authority the mass model needs. Provenance rides in client-supplied `context`,
    which is stored blind, so a raw request can *say* `human_validated`. That claim is worth
    nothing until an authority backs it. Here the authority is the authenticated principal:

    * `human_validated` requires a `HUMAN` principal — a real person acted.
    * `span_cited` requires a **verified span**, from any non-client principal — the span is the
      evidence, so this rung is earned by showing it, not by being trusted.
    * a `CLIENT` (untrusted) is capped at `hypothesis`: it may offer a guess, never a grounding.
    * anything above a principal's ceiling is **quietly demoted to what it earned**, not
      rejected — a caller over-claiming is normal, not an attack, and demotion is the honest
      response. (`assertion` and the off-ladder `ontology_proposal` a SYSTEM may set directly.)

    Same principle as the token issuer (`ISSUER-FIX.md`): the server derives identity from what
    it can verify and ignores what the client asserts. Fidelity is enforced at the copy.
    """
    # Validate the principal FIRST: it comes from the auth layer, so a bad value is a server
    # bug and must raise even when the client claimed nothing (which would otherwise short to
    # UNKNOWN and hide the misconfiguration).
    if principal_kind not in _PRINCIPAL_KINDS:
        raise ValueError(f"unknown principal kind {principal_kind!r}; expected {list(_PRINCIPAL_KINDS)}")
    # ⛔ A CLIENT TYPO WAS FATAL WHILE A CLIENT FORGERY WAS HANDLED GRACEFULLY.
    # This was a bare `Provenance(claimed)`, which raises on anything that is not an exact
    # lowercase member — and `claimed` comes straight off the wire (`ctx.get("provenance")` in
    # `authorize_and_stamp`). So `{"provenance": "HUMAN_VALIDATED"}` (right rung, wrong case) or a
    # JSON object raised an uncaught ValueError and 500'd the write, while a deliberate over-claim
    # of `"human_validated"` was correctly demoted. That directly violates this module's stated
    # contract — `test_derive_provenance_demotes_rather_than_rejects`: "Over-claiming is normal,
    # not an attack ... The honest response is demotion to what it earned, NEVER AN ERROR THAT
    # DROPS THE WRITE."
    # It was also inconsistent with the READ path: `provenance_of` does
    # `Provenance(raw.strip().lower())` inside a try and falls back to UNKNOWN, so the very same
    # string READS fine and WRITES a 500. Normalize and fall back identically.
    # Note this is NOT a new free rung: an unrecognized claim becomes UNKNOWN, and a normalized
    # over-claim still goes through the ceiling logic below exactly as before.
    if isinstance(claimed, Provenance):
        want = claimed
    elif claimed:
        try:
            want = Provenance(str(claimed).strip().lower())
        except (ValueError, TypeError):
            want = Provenance.UNKNOWN
    else:
        want = Provenance.UNKNOWN

    # A verified span earns span_cited for any principal that isn't an anonymous client.
    if want is Provenance.SPAN_CITED:
        return Provenance.SPAN_CITED if (has_verified_span and principal_kind != CLIENT)             else _demote_to_ceiling(principal_kind)

    ceiling = _MAX_CLAIM[principal_kind]
    # ontology_proposal is off the claim ladder; a SYSTEM may set it, others may not.
    if want is Provenance.ONTOLOGY_PROPOSAL:
        return want if principal_kind == SYSTEM else Provenance.UNKNOWN

    if want in CLAIM_LADDER and ceiling in CLAIM_LADDER:
        # Lower ladder index == stronger. Grant the claim only if it is at/below the ceiling.
        return want if CLAIM_LADDER.index(want) >= CLAIM_LADDER.index(ceiling) else ceiling
    return want


def _demote_to_ceiling(principal_kind: str) -> Provenance:
    return _MAX_CLAIM.get(principal_kind, Provenance.UNKNOWN)


def stamp(artifact: dict, provenance: Provenance, *, evidence: Optional[dict] = None) -> dict:
    """Record HOW this artifact was obtained — the write-side pair of `provenance_of`.

    This is the **proofreading** layer: fidelity at copy time, which is a different mechanism
    from the selection that acts later (density, aging, human validation). Both are needed —
    proofreading alone does not adapt; selection alone cannot keep up once the error rate rises.
    And fidelity is what *buys* corpus size: a store can only grow as large as its gates permit.

    Three deliberate choices:

    * **No default rung.** The caller knows how it got the content; this cannot guess. A default
      would hand every artifact a free rung, which is precisely how laundering starts.
    * **Copies, never mutates.** Artifacts are content-addressed. Editing one in place changes
      what it *is* while everything holding its id believes otherwise.
    * **Re-stamping is the promotion path, and it is recorded.** The ladder is climbed by
      acquiring better provenance (a hypothesis that earns a citation *becomes* `span_cited`),
      never by volume. So re-stamping is legitimate — but a silent rung change is not, so the
      prior rung is kept in the trail.

    ``evidence`` is the audit record (e.g. `extraction.describe(...)`): what was asked, what came
    back, what it earned. Stored so a future reader can **re-judge** the decision rather than
    inherit it.
    """
    if not isinstance(provenance, Provenance):
        provenance = Provenance(provenance)   # raises on nonsense: a write must not guess

    out = dict(artifact)
    ctx = out.get("context")
    if isinstance(ctx, str):
        import json
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = {}
    ctx = dict(ctx) if isinstance(ctx, dict) else {}

    prior = ctx.get("provenance")
    ctx["provenance"] = provenance.value
    if evidence:
        ctx["provenance_evidence"] = dict(evidence)
    if prior and prior != provenance.value:
        # A rung changed. Keep the trail: promotion must be auditable, and a silent demotion
        # would be indistinguishable from tampering.
        trail = list(ctx.get("provenance_history") or [])
        trail.append(prior)
        ctx["provenance_history"] = trail
    out["context"] = ctx
    return out


def authorize_and_stamp(context, *, principal_type: str, is_delegated: bool,
                        has_verified_span: bool = False,
                        evidence: Optional[dict] = None) -> dict:
    """The one call a server write path makes: take the client's context, DERIVE the rung it has
    actually earned from the authenticated principal, and stamp that — ignoring what the client
    claimed. Returns the context dict to store.

    This is the whole authority in one function. It composes `principal_kind_of` (who is
    writing, delegation-aware) with `derive_provenance` (what that principal may claim) and
    `stamp` (record it, immutably, with the promotion trail). A server calls this instead of
    trusting `context.provenance`, and a client can no longer forge a rung.

    `context` may be a dict, a JSON string, or None — servers store context as a JSON string, so
    both forms are accepted. The claimed rung is read from it and then overwritten with the
    derived one.
    """
    import json
    ctx = context
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = {}
    ctx = dict(ctx) if isinstance(ctx, dict) else {}

    claimed = ctx.get("provenance")   # what the client asked for — advisory only
    # ⛔ THE AUDIT TRAIL WAS CLIENT-WRITABLE, UNDER THE SERVER'S AUTHORITY.
    # Only `provenance` was treated as advisory and overwritten. `provenance_evidence` and
    # `provenance_history` were copied straight out of the client context and survived into the
    # stored artifact, because `stamp()` only ever writes the rung and appends to the trail.
    # Measured: posting
    #     {"provenance":"human_validated",
    #      "provenance_evidence":{"verified_by":"attacker"},
    #      "provenance_history":["human_validated"]}
    # as an api_key correctly demoted the RUNG to `hypothesis` — and then stored
    #     evidence: {'verified_by': 'attacker'}
    #     history : ['human_validated', 'human_validated']
    # i.e. a forged justification plus a fabricated promotion trail asserting the artifact was
    # once human_validated. The trail exists precisely because "a silent rung change would be
    # indistinguishable from tampering"; an attacker-writable trail supplies exactly the tampering
    # it was meant to detect, and `provenance_evidence` is documented as the record a future
    # reader uses to RE-JUDGE the decision.
    # These fields are SERVER-DERIVED. The client may not seed either one.
    ctx.pop("provenance_evidence", None)
    ctx.pop("provenance_history", None)
    # NOTE: `ctx["provenance"]` (the claim) is deliberately LEFT IN PLACE. `stamp()` moves it into
    # `provenance_history` as the prior, and on this path that is BY DESIGN — the trail records
    # the client's over-claim so the demotion is auditable rather than silent
    # (`test_authorize_and_stamp_is_the_whole_authority_in_one_call` asserts exactly that).
    # I removed it first and the core suite caught it; the test encodes intent, not a defect.
    # ⚠ Worth a design decision though, and NOT a unilateral one: `provenance_history` now holds
    # two different kinds of entry — a genuinely-held prior rung (the real promotion path in
    # `stamp`) and a REFUSED claim (this path) — with nothing in the data distinguishing them.
    # A reader cannot tell "this artifact was once human_validated" from "someone claimed
    # human_validated and was denied". Separating them is a schema change.
    kind = principal_kind_of(principal_type, is_delegated=is_delegated)
    earned = derive_provenance(claimed, kind, has_verified_span=has_verified_span)
    # Wrap the bare-dict artifact stamp() expects, then return just the stamped context.
    stamped = stamp({"context": ctx}, earned, evidence=evidence)
    return stamped["context"]


class Revision(str, Enum):
    """What a proposed write is ALLOWED to do to an existing artifact.

    A grant answers *may you touch this* (`check_access`). Mass answers a different question the
    grant cannot: *does your write carry enough authority to DISPLACE what is already there?*
    Those are orthogonal — the owner of a `human_validated` artifact still should not be able to
    silently overwrite it with a model's assertion, even though they plainly have the grant.
    """

    # Artifacts are IMMUTABLE — a write is always a new version under the same root_id, never an
    # edit in place. So this is not "overwrite vs not"; it is which version becomes the HEAD.
    REPLACE = "replace"    # >= standing mass: the new version becomes HEAD (old archived, kept)
    PROPOSE = "propose"    # < standing mass: committed as a NON-HEAD competing version to promote


# Re-asserting at effectively the same authority is a replace, not a proposal. The epsilon keeps
# float noise (a re-fit crosswalk, a rounding) from turning an equal-authority update into a
# spurious proposal.
_REVISE_EPS = 1e-6


def may_revise(current_mass: float, incoming_mass: float) -> Revision:
    """Inertia, literally: a revision must carry at least as much mass as what it displaces.

    **Mass is resistance to acceleration.** A high-mass artifact (human-validated, corroborated)
    resists being overturned; a ghost is displaced by a breath. So:

    Nothing is ever destroyed: both outcomes create a new immutable version under the artifact's
    root_id. The gate only decides which version is HEAD.

    * ``incoming >= current`` → **REPLACE.** Equal or greater authority: the new version becomes
      HEAD (the prior head is archived, not deleted). This keeps the ladder climbable — a
      hypothesis that earns a citation (span_cited, higher mass) takes head from its old self.
    * ``incoming < current`` → **PROPOSE.** Lower authority does not take head. The version is
      still committed (a rejected correction is not lost — it is simply a version that never
      became head) but stays a competing, non-head claim that a higher authority must promote.
      The same escalation as `extraction.needs_review`.

    Note this composes with the write-time authority: `incoming_mass` should be the mass of the
    write's **derived** rung (post `derive_provenance`), so a client's forged `human_validated`
    is already demoted to a hypothesis's mass *before* it is compared here. A client therefore
    cannot replace a validated artifact — 0.20 < 1.0 → PROPOSE — no matter what it claims.
    """
    return Revision.REPLACE if incoming_mass + _REVISE_EPS >= current_mass else Revision.PROPOSE


def provenance_of(artifact: dict) -> Provenance:
    """Read an artifact's provenance rung, defaulting to UNKNOWN.

    It rides in the artifact's ``context`` (``context.provenance``) rather than in a new
    column — Mantle is label-blind, so context is exactly where a property it must store but
    need not understand belongs. That means **no migration and no schema change**: artifacts
    written before this existed simply read as UNKNOWN, which is the honest answer for them.

    An unrecognised value is also UNKNOWN, not an error. A typo in a provenance label must
    never be able to *raise* the thing it labels — failing closed here means the worst a bad
    label can do is under-credit an artifact, never over-credit one.
    """
    ctx = artifact.get("context")
    if isinstance(ctx, str):
        import json
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = None
    if not isinstance(ctx, dict):
        return Provenance.UNKNOWN
    raw = ctx.get("provenance")
    if not isinstance(raw, str):
        return Provenance.UNKNOWN
    try:
        return Provenance(raw.strip().lower())
    except ValueError:
        return Provenance.UNKNOWN


def consensus_of(provenance: Provenance, **kw) -> float:
    """Mass as the scalar `ShardItem.consensus` wants — the mesh's 'provenance weight'.

    This is the seam that replaces the placeholder in `mantle_bridge.py`
    (`1.0 if len(content) > 8 else 0.5`), which weighed *length*: a property every
    hallucination has in abundance.
    """
    return weigh(provenance, **kw).mass


__all__ = [
    "Provenance", "CITE_GENESIS", "Weight", "weigh", "consensus_of",
    "CLAIM_LADDER", "OFF_LADDER", "GHOST_FLOOR", "DARK_AGE_FRAMES", "provenance_of", "stamp",
    "derive_provenance", "principal_kind_of", "authorize_and_stamp", "HUMAN", "SYSTEM", "CLIENT",
    "Revision", "may_revise",
    "surfacable",
]
