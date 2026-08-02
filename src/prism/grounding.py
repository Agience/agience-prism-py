"""Grounding — the small, stable surface a RUNNER and the migrating personas reach.

Hoisted from the 3069-line `genesis.py` op-table (P0-remainder, 2026-07-29, ember→chorus migration) so
code that moves to a persona (the conversation tekton `activation`→lumen; the `delegate`) reaches these
WITHOUT importing the giant instrument op-table.

⭐ THE LAW IS NOT DEFINED HERE ANY MORE — IT IS IMPORTED (2026-07-30).
------------------------------------------------------------------
The provenance ladder and the system-authorship citation anchor are **law**: the same facts for
Mantle, for beam and for every leaf. Ember is a runner, and a runner that *defines* a law is the
shape where two copies drift apart — this module carried the five rung strings and `cite.genesis`
as literals while `prism.mass` carried the identical ladder as an enum, so the law had two homes and
neither was authoritative. `prism.mass` is now the single one:

  * `Provenance` — the rungs, with their bands and the ladder invariant (`beam/mass.py`).
  * `CITE_GENESIS` — the anchor system artifacts cite (`beam/mass.py`).

The names below are re-exported UNCHANGED and are the enum's own `.value`, so they are the same
strings that are already written to every row — nothing in the store moves, and the callers that
import them from here (`genesis`, `seed_lattice`, `cuddler`, `lumen/conversation`) are untouched.
`.value` rather than the member itself is deliberate: a `str`-Enum formats as
`Provenance.HUMAN_VALIDATED` under `%s`/`format()` in 3.11+, and these values reach both.

What is genuinely a RUNNER's, and stays: the conversation-triple content type, the transducer
op-id prefix, and the UTC clock.

⚠ MOVED FROM `ember/runtime/grounding.py` TO PRISM ON 2026-07-31. Everything in here is CONTRACT —
the provenance rung aliases, the triple content type, the transducer op prefix, and a UTC stamp —
and it already stood on `prism.mass`. It sat in the runner only because the runner hoisted it out of
`genesis.py` first.

The move was forced the same way `mass` was: `agience-mantle/src/mantle/shard/content_tier.py`
needs `CITE_GENESIS` and `_now()`, and the declared layering says mantle may reach only origin and
prism — never ember. A vocabulary that the store, the runner and the personas all stamp into
artifacts cannot live in any one of them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from prism.mass import CITE_GENESIS, Provenance   # sibling now, not a cross-repo reach

# ── provenance rungs — prism.mass.Provenance, spelled the way the stored rows spell it ────────
P_HUMAN = Provenance.HUMAN_VALIDATED.value
P_OBSERVED = Provenance.OBSERVED.value
P_SPAN_CITED = Provenance.SPAN_CITED.value
P_HYPOTHESIS = Provenance.HYPOTHESIS.value
P_ASSERTION = Provenance.ASSERTION.value

# ── what a runner actually owns ──────────────────────────────────────────────────────────────
# The conversation TRIPLE artifact (context/content/operator) the tekton recognizes/observes.
TRIPLE_TYPE = "application/vnd.agience.triple+json"

# ── the TRANSDUCER op-id prefix (option B — John, 2026-07-29: "Go B") ─────────
# ONE place. Code and store now BOTH read `op.transducer.*` (migrated 2026-07-30).
# Lives HERE (a leaf) rather than in `transducer.py` because `transducer` imports `wn_store`, so
# `wn_store` — which also names an op-id — cannot import it back without a cycle; both reach `grounding`.
# ⭐ FLIPPED 2026-07-30, WITH the migration, not before it. `node/transducer_rename.py --apply` renamed
# the stored artifact (`op.gauge.language.en` → `op.transducer.language.en`, 1 row on node 71) and this
# line moved in the same step.
#
# ⚠ THE TWO HALVES MUST LAND TOGETHER, AND A LAGGING HALF IS SILENT. `wn_store._keyed_ready()` only
# asks whether `TRANSDUCER_OP + "language.en"` EXISTS. So whichever half lands alone leaves the node on
# the SLOW UNKEYED PATH with no error and no log — a cold aperture that looks like a working node.
# Code-first is the worse order (it searches for an id no store holds); store-first is merely slow.
# The paired content-type `transducer.TRANSDUCER_CT` flips in the same step.
TRANSDUCER_OP = "op.transducer."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "P_HUMAN", "P_OBSERVED", "P_SPAN_CITED", "P_HYPOTHESIS", "P_ASSERTION",
    "CITE_GENESIS", "TRIPLE_TYPE", "TRANSDUCER_OP", "_now",
]
