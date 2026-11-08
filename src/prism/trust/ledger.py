"""The authority ledger's shared names, read by Origin (which writes the ledger) and Mantle (which
applies its feed): one place, so a label one repo writes is never matched by the other's own
literal (review 17).

`CREDENTIAL_KINDS` is every credential kind Origin records on an entry. `MANTLE_APPLIES` is the
subset Mantle's feed writes into its store, because Mantle did not make them:

  origin_session  a person's change in their Origin session (Facet's grants, invites, denies,
                  revocations, claims and edge changes)
  origin_page     a person's change at Origin's own page (job grants, a sign-out's edges)
  operator        the operator's, through the console (revocations, edge removals, retirements)

Every other kind is an entry Mantle submitted itself, already in its store when Origin co-signed
it: `access` and `delegation` (a person's token or delegation Mantle holds), `background` (the
system principal's retry), `bootstrap`, `seed`, and `narrowed` (Ember's, made through Mantle).
"""
from __future__ import annotations

import hashlib
from typing import Optional

CREDENTIAL_KINDS = frozenset({
    "access", "delegation", "background", "bootstrap", "seed", "narrowed",
    "origin_session", "origin_page", "operator",
})

MANTLE_APPLIES = frozenset({"origin_session", "origin_page", "operator"})

#: The ledger's entry kinds. `drop_key` is retired (an old one still verifies and applies nothing).
ENTRY_KINDS = frozenset({"grant", "edge.add", "edge.remove", "root", "drop_key", "root.retire",
                         "job_grant", "root.confirm_empty"})

#: The hash before entry 1, and the version of the envelope each entry hash is taken over.
GENESIS = "0" * 64
LEDGER_VERSION = 2

#: A collection key's id: `ck:<collection id>`.
COLLECTION_KEY_PREFIX = "ck:"


def target_digest(kind: Optional[str], value: Optional[str]) -> Optional[str]:
    """An invite target as the ledger carries it: a digest of the normalised value, never the
    value (an email or domain lower-cased). Facet computes the same (`api/authority.ts`)."""
    if not kind or not value:
        return None
    v = str(value).strip()
    if kind in ("email", "domain"):
        v = v.lower()
    return hashlib.sha256(f"agience-invite-target:{kind}:{v}".encode("utf-8")).hexdigest()


#: The CRUDEASIO actions, in the ledger's order; a mask carrying every one conducts all.
ACTIONS = ("create", "read", "update", "delete", "evict", "invoke", "add", "share", "admin")


def canonical_expiry(value) -> Optional[str]:
    """An expiry as both digests read it: UTC ISO-8601, None for none, `"unreadable"` for one that
    does not parse (which both sides treat as past)."""
    if value is None or value == "":
        return None
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return "unreadable"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).isoformat()


def canonical_reach(grants, edges) -> str:
    """The one canonical form Origin's replica and Mantle's store digest (review 19, M1).

    A grant is `[grant_id, grantee_id, grantee_type, resource_id, actions, effect, state,
    expires_at, target_kind, target_digest, max_claims]`, its expiry canonical UTC; an edge is
    `[src, dst, origin, propagate]`, a mask conducting every action null. Actions and masks are
    sorted, each list sorted, as compact JSON with sorted keys. Each grant is a mapping with those
    keys (`target` may stand for `target_kind`/`target_digest`); each edge a 4-tuple.

    What is left out, and why it widens nothing: a grant's `created_by` grants nothing
    (architecture §51); `claimed_from` records which invite a claim spent, and claims are decided
    at Origin alone, by its own count; a row's `seq` and an edge's `added_by` are Origin's
    bookkeeping (the creator's base case is decided at Origin); names and notes are not in the
    ledger at all."""
    import json

    def grant(x):
        t = x.get("target") or {}
        kind = x.get("target_kind", t.get("kind"))
        digest = x.get("target_digest", t.get("digest"))
        mc = x.get("max_claims")
        return [str(x["grant_id"]), str(x["grantee_id"]), str(x["grantee_type"]),
                str(x["resource_id"]), sorted(x.get("actions") or []), str(x["effect"]),
                str(x["state"]), canonical_expiry(x.get("expires_at")),
                str(kind) if kind else None, str(digest) if digest else None,
                int(mc) if mc is not None else None]

    def mask(p):
        if isinstance(p, str):
            p = json.loads(p) if p.strip().startswith("[") else p
        if p is None or (not isinstance(p, str) and set(p) >= set(ACTIONS)):
            return None
        return sorted(p) if not isinstance(p, str) else p

    g = sorted(grant(x) for x in grants)
    e = sorted([str(x[0]), str(x[1]), bool(x[2]), mask(x[3])] for x in edges)
    return json.dumps({"edges": e, "grants": g}, separators=(",", ":"), sort_keys=True,
                      ensure_ascii=False)
