"""Grounding — the small, stable surface a runner and the migrating personas reach.

Code that lives in a persona (the conversation tekton `activation`→lumen; the `delegate`) reaches
these without importing the giant instrument op-table:

  * the provenance channels — `prism.mass.Provenance`, as the strings the stored rows carry.
  * `CITE_GENESIS` — the anchor system artifacts cite (`prism.mass`).

The names below are the enum's own `.value`, so they are the same strings already written to every
row, and the callers that import them from here (`genesis`, `seed_lattice`, `cuddler`,
`lumen/conversation`) read exactly what the store holds. `.value` rather than the member itself,
because a `str`-Enum formats as `Provenance.HUMAN_VALIDATED` under `%s`/`format()` in 3.11+ and
these values reach both.

What is genuinely a runner's, and stays here: the conversation-triple content type, the transducer
op-id prefix, and the UTC clock.

It lives in `prism` because `agience-mantle/src/mantle/shard/content_tier.py` needs `CITE_GENESIS`
and `_now()`, and the declared layering has mantle reaching origin and prism. A vocabulary that the
store, the runner and the personas all stamp into artifacts belongs below all three.
"""
from __future__ import annotations

from datetime import datetime, timezone

from prism.mass import CITE_GENESIS, Provenance   # a sibling module, so this is an in-package reach

# ── provenance channels — prism.mass.Provenance, spelled the way the stored rows spell it ─────
P_HUMAN = Provenance.HUMAN_VALIDATED.value
P_OBSERVED = Provenance.OBSERVED.value
P_SPAN_CITED = Provenance.SPAN_CITED.value
P_HYPOTHESIS = Provenance.HYPOTHESIS.value
P_ASSERTION = Provenance.ASSERTION.value

# ── what a runner actually owns ──────────────────────────────────────────────────────────────
# The conversation triple artifact (context/content/operator) the tekton recognizes/observes.
TRIPLE_TYPE = "application/vnd.agience.triple+json"

# ── the transducer op-id prefix ───────────────────────────────────────────────
# One place. Code and store both read `op.transducer.*`.
# Lives here (a leaf) rather than in `transducer.py` because `transducer` imports `wn_store`, so
# `wn_store` — which also names an op-id — reaches `grounding` instead, and both stay acyclic.
#
TRANSDUCER_OP = "op.transducer."

# This module is the runner's small surface: the provenance channels, the triple type, the op-id
# prefix, and the clock. `agience-ember/tests/test_grounding_is_not_the_law.py` fences `__all__` so
# it stays that size. Principal classification (`PROCESS_AUTHORS` / `is_process_author`) lives in
# `prism/principals.py`.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "P_HUMAN", "P_OBSERVED", "P_SPAN_CITED", "P_HYPOTHESIS", "P_ASSERTION",
    "CITE_GENESIS", "TRIPLE_TYPE", "TRANSDUCER_OP", "_now",
]
