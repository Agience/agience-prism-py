"""Provenance — how an artifact was obtained, and who is entitled to say so.

Mass — how much agreement stands behind an artifact — is counted in `prism.attestation`: how many
independent origins attest it, read from the attestations a node has verified. Because the quantity
is a count of origins, a replica adds nothing to it, and corroboration by repetition of one origin
is arithmetically the echo it always was.

This module holds the other question, and it is not an ordering. `Provenance` is a **channel**: how
one observer obtained one thing. Unranked. Two questions are asked of a channel:

  * **"May this principal say that?"** → a grant (`_GRANTS`), which is set membership.
    [[access-is-crudeasio-grants]].
  * **"Is there something to check?"** → `REFERENT`, a partition of the channels.

The partition is why `ontology_proposal` needs no carve-out. Asked whether it has a checkable
referent, it answers plainly — no — and sits in the partition with everything else. A queued
`proof_checked` lands the same way: a machine-checked derivation has a referent (the proof), so it
joins `REFERENT` and is never ranked against `human_validated`. Both are simply grounded, which is
the whole of what the partition says about either.

This module is dependency-free (stdlib only) and lives in `prism` so the server and the leaf read
provenance identically — one shared answer to "who may attest what" keeps authority single-valued at
the edge.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Provenance(str, Enum):
    """**A channel: how one observer obtained one thing.** Unordered.

    The model's role differs at every channel — parser, proposer, generator, oracle — and the
    distinction that matters is "is there anything to check". That is `REFERENT`, below. The model
    may say where to look and what things are called; belief rests on the referent, which is a
    property of the channel rather than a rank over channels.
    """

    HUMAN_VALIDATED = "human_validated"      # a person staked a claim on it
    OBSERVED = "observed"                    # an instrument / system of record
    SPAN_CITED = "span_cited"                # extracted FROM a source; provenance is the doc
    ONTOLOGY_PROPOSAL = "ontology_proposal"  # a proposed anchor; the density gate validates it
    HYPOTHESIS = "hypothesis"                # a distilled prior, no citable span
    UNKNOWN = "unknown"                      # provenance was never recorded — see below
    ASSERTION = "assertion"                  # "the caller said so" — marked, never grounded


# The provenance anchor for system-authored artifacts (the ontology, operators, collections, and
# the citations themselves). GENESIS §12: no artifact without provenance — every artifact carries
# a `cited_from`. Ingested artifacts cite their source (`cite.<dataset>`); system artifacts cite
# this. It is human_validated and self-anchored.
CITE_GENESIS = "cite.genesis"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# The one honest distinction — a partition of the channels
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Is there something to check behind this channel? A person who staked a claim, an instrument that
# recorded a reading, a document span you can go and read. That is a property of the channel and it
# is decidable; "which of two grounded channels is better" is not, and every attempt to answer it
# produced a band edge nobody could defend.
#
# How much to believe a grounded claim is the attestation count (`prism.attestation`), measured,
# and that is a different question from whether anything grounds it at all.
REFERENT: frozenset = frozenset({
    Provenance.HUMAN_VALIDATED,
    Provenance.OBSERVED,
    Provenance.SPAN_CITED,
})

# The ungrounded channels, likewise unordered among themselves:
#   * `hypothesis` — a distilled prior. You know what you are holding; nothing checks it.
#   * `ontology_proposal` — answers a different question entirely ("does this coordinate exist?"),
#     validated by the density gate rather than by a referent.
#   * `unknown` — provenance was never recorded. "Unlabeled" is a different claim from "fabricated",
#     and the remedy is migration: label it and it is re-read.
#   * `assertion` — the caller said so, and nothing else backs it. This is where an over-claim
#     lands (see `derive_provenance`) because it is the literally true description of one.


def has_referent(provenance) -> bool:
    """Does this channel claim a checkable referent?

    This reads a label, which is a claim rather than a measurement. `human_validated` says a person
    staked it; it does not say which person, and nothing here can go and look. `grounds()` below is
    the measured form, and where a store is in hand it is the one to call: a label always reads back,
    while a citation can dangle.

    Retained for the callers that hold no store — a bare signal envelope carries a claimed channel
    and a reference that cannot yet be resolved (see the note on `grounds`)."""
    if not isinstance(provenance, Provenance):
        try:
            provenance = Provenance(str(provenance).strip().lower())
        except (ValueError, TypeError):
            return False
    return provenance in REFERENT


def grounds(artifact: dict, resolve) -> Optional[str]:
    """**The artifact that grounds this one — resolved, not asserted.** `None` when nothing does.

    GENESIS §12: *"No artifact without provenance — every artifact carries a `cited_from`."* That
    field is populated across the live corpus (`cite.oewn`, `cite.conceptnet`, `cite.genesis`) and
    those citation artifacts are really in the store, so an artifact already carries a resolvable
    reference to what grounds it. A label states; a reference can be followed. That is the whole
    gain:

      * **no citation** → `None`. Nothing was recorded.
      * **a citation that does not resolve** → `None`. A dangling reference grounds nothing, and
        this is the state a label cannot express: `provenance="span_cited"` reads as grounded
        forever while the document it names has been gone since the day it was written.
      * **an artifact citing itself** → `None`. Otherwise anything could self-anchor and mint its own
        grounding, which is laundering with one extra step. `CITE_GENESIS` is exactly this shape and
        so reads as ungrounded — correctly: **an axiom is assumed, not grounded.** It still grounds
        everything that cites it, because those cite a different resolvable artifact.

    ``resolve`` is `id -> artifact | None` (duck-typed, so this stays stdlib-only and Mantle passes
    whatever store it holds). A resolver that raises is treated as not-resolving: an artifact whose
    grounding cannot be checked is not grounded, which is the fail-closed direction for a gate.
    """
    if not isinstance(artifact, dict):
        return None
    ref = str(artifact.get("cited_from") or "").strip()
    if not ref:
        return None
    if ref == str(artifact.get("id") or "").strip():
        return None                    # self-anchored: an axiom, not a grounding
    try:
        return ref if resolve(ref) is not None else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Who may attest what — a grant
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Who is asking to write. The channel a caller may claim is bounded by which of these they are — a
# channel is only as trustworthy as the principal that could set it.
HUMAN = "human"          # an authenticated person (e.g. via Facet)
SYSTEM = "system"        # a trusted service principal (crystal, an extraction pipeline)
CLIENT = "client"        # any authenticated caller with no special standing
_PRINCIPAL_KINDS = (HUMAN, SYSTEM, CLIENT)

# One grant per principal kind, held as a set. "May a CLIENT say `human_validated`?" is a membership
# question, so it is answered by looking in the set.
#
# Membership also carries the per-channel facts directly: `ontology_proposal` is a SYSTEM grant and
# nobody else's, which is one entry here rather than a branch beside the table.
_GRANTS: dict[str, frozenset] = {
    HUMAN: frozenset({Provenance.HUMAN_VALIDATED, Provenance.OBSERVED, Provenance.SPAN_CITED,
                      Provenance.HYPOTHESIS, Provenance.UNKNOWN, Provenance.ASSERTION}),
    SYSTEM: frozenset({Provenance.OBSERVED, Provenance.SPAN_CITED, Provenance.ONTOLOGY_PROPOSAL,
                       Provenance.HYPOTHESIS, Provenance.UNKNOWN, Provenance.ASSERTION}),
    CLIENT: frozenset({Provenance.HYPOTHESIS, Provenance.UNKNOWN, Provenance.ASSERTION}),
}
# `span_cited` is earned by presenting a span. It appears in two grants, and it is conditional in
# both: the grant is necessary, and the span is what earns it.


def principal_kind_of(principal_type: str, *, is_delegated: bool) -> str:
    """Classify an auth principal into HUMAN / SYSTEM / CLIENT for provenance authority.

    Kept as plain strings (not an AuthContext) so it lives in `prism` without depending on any
    server package — Mantle passes the two fields it reads off its own context.

    The one subtlety, and it is the confused-deputy trap: **a delegation token carries the
    user's `user_id`**, because a persona/bot is acting *on behalf of* a person. So "has a user_id"
    means a person is implicated, and only a **direct, non-delegated** interactive user is HUMAN; a
    bot acting for you is a SYSTEM at best. That boundary is what keeps a persona from minting
    `human_validated` under your identity — the impersonation the delegation model exists to contain.
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
    # standing. Untrusted for provenance.
    return CLIENT


def derive_provenance(claimed, principal_kind: str, *, has_verified_span: bool = False) -> Provenance:
    """The channel a write actually earns — derived server-side from the authenticated principal.

    Provenance rides in client-supplied `context`, which is stored blind, so a raw request can *say*
    `human_validated`. That claim is worth nothing until an authority backs it. Here the authority is
    the authenticated principal, and the test is grant membership:

    * **claim in the principal's grant → granted.**
    * **`span_cited` additionally requires a verified span** — the span IS the evidence, so this
      channel is earned by showing it, not by being trusted.
    * **claim outside the grant → `ASSERTION`.**

    `assertion` is the literally true description of an unbacked claim: the caller said so, and
    nothing else backs it. It is the accurate channel for that state rather than a lower rung.

    The write still lands. A caller over-claiming is ordinary traffic, and `stamp` records the
    over-claim in `provenance_history`, so the correction is auditable.

    Same principle as the token issuer (`ISSUER-FIX.md`): the server derives identity from what it
    can verify and ignores what the client asserts. Fidelity is enforced at the copy.
    """
    # Validate the principal first: it comes from the auth layer, so a bad value is a server bug and
    # raises even when the client claimed nothing, which would otherwise short to UNKNOWN and hide
    # the misconfiguration.
    if principal_kind not in _PRINCIPAL_KINDS:
        raise ValueError(f"unknown principal kind {principal_kind!r}; expected {list(_PRINCIPAL_KINDS)}")
    if isinstance(claimed, Provenance):
        want = claimed
    elif claimed:
        try:
            want = Provenance(str(claimed).strip().lower())
        except (ValueError, TypeError):
            want = Provenance.UNKNOWN
    else:
        want = Provenance.UNKNOWN

    grant = _GRANTS[principal_kind]
    if want is Provenance.SPAN_CITED:
        # Earned by presenting the span. Without a span, whatever the principal's standing, what is
        # left is that they said so.
        return want if (has_verified_span and want in grant) else Provenance.ASSERTION
    return want if want in grant else Provenance.ASSERTION


def stamp(artifact: dict, provenance: Provenance, *, evidence: Optional[dict] = None) -> dict:
    """Record how this artifact was obtained — the write-side pair of `provenance_of`.

    This is the **proofreading** layer: fidelity at copy time, which is a different mechanism
    from the selection that acts later (density, aging, human validation). Both are needed —
    proofreading alone does not adapt; selection alone cannot keep up once the error rate rises.
    And fidelity is what *buys* corpus size: a store can only grow as large as its gates permit.

    Three deliberate choices:

    * **No default channel.** The caller knows how it got the content; this cannot guess. A default
      would hand every artifact a free provenance, which is precisely how laundering starts.
    * **Copies, never mutates.** Artifacts are content-addressed. Editing one in place changes
      what it *is* while everything holding its id believes otherwise.
    * **Re-stamping is legitimate, and it is recorded.** A hypothesis that earns a citation
      *becomes* `span_cited`. So re-stamping is normal — but a silent channel change is not, so the
      prior value is kept in the trail.

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
        # The channel changed. Keep the trail: a re-stamp must be auditable, and a silent one
        # would be indistinguishable from tampering.
        trail = list(ctx.get("provenance_history") or [])
        trail.append(prior)
        ctx["provenance_history"] = trail
    out["context"] = ctx
    return out


def authorize_and_stamp(context, *, principal_type: str, is_delegated: bool,
                        has_verified_span: bool = False,
                        evidence: Optional[dict] = None) -> dict:
    """The one call a server write path makes: take the client's context, derive the channel it has
    actually earned from the authenticated principal, and stamp that — ignoring what the client
    claimed. Returns the context dict to store.

    This is the whole authority in one function. It composes `principal_kind_of` (who is
    writing, delegation-aware) with `derive_provenance` (what that principal may claim) and
    `stamp` (record it, immutably, with the trail). A server calls this in place of reading
    `context.provenance`, so a client's claimed channel stays advisory.

    `context` may be a dict, a JSON string, or None — servers store context as a JSON string, so
    both forms are accepted. The claimed value is read from it and then overwritten with the
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
    ctx.pop("provenance_evidence", None)
    ctx.pop("provenance_history", None)
    # `ctx["provenance"]` (the claim) stays in place. `stamp()` moves it into `provenance_history`
    # as the prior, so the trail records the client's over-claim and the correction is auditable.
    # The core suite asserts this, so the behaviour is pinned as intent.
    kind = principal_kind_of(principal_type, is_delegated=is_delegated)
    earned = derive_provenance(claimed, kind, has_verified_span=has_verified_span)
    # Wrap the bare-dict artifact stamp() expects, then return just the stamped context.
    stamped = stamp({"context": ctx}, earned, evidence=evidence)
    return stamped["context"]


class Revision(str, Enum):
    """What a proposed write does to an existing artifact.

    A grant answers *may you touch this* (`check_access`). Agreement answers a different question the
    grant cannot: *does your write carry enough standing to displace what is already there?* Those
    are orthogonal — holding the grant on a well-attested artifact is separate from carrying the
    standing to silently overwrite it with a claim nothing supports.
    """

    # Artifacts are immutable — a write is always a new version under the same root_id. So the
    # choice here is which version becomes the head.
    REPLACE = "replace"    # the new version becomes HEAD (old archived, kept)
    PROPOSE = "propose"    # committed as a NON-HEAD competing version, to be promoted


def provenance_of(artifact: dict) -> Provenance:
    """Read an artifact's channel, defaulting to UNKNOWN.

    It rides in the artifact's ``context`` (``context.provenance``) rather than in a new
    column — Mantle is label-blind, so context is exactly where a property it must store but
    need not understand belongs. That means **no migration and no schema change**: artifacts
    written before this existed simply read as UNKNOWN, which is the honest answer for them.

    An unrecognised value is also UNKNOWN rather than an error. Failing closed here bounds what a
    typo in a provenance label can do: it leaves an artifact ungrounded, and a read of the label
    stays a read rather than becoming a raise.
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


__all__ = [
    "Provenance", "CITE_GENESIS", "REFERENT", "has_referent", "grounds",
    "provenance_of", "stamp", "derive_provenance", "principal_kind_of", "authorize_and_stamp",
    "HUMAN", "SYSTEM", "CLIENT", "Revision",
]
