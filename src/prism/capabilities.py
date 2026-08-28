# The capability vocabulary lives in prism — the prism is what physically offers and enforces these,
# so it owns the names. `crystal.operator_schema` re-exports this, and ember reaches it through
# crystal. One home, no copy, the same rule `prism.crystal_model` follows for the crystal contract.
"""The capability lexicon — spellings a host may sign into a manifest.

A capability is a prism-provided affordance: something the hardware can physically do. This module
holds spellings and what each one means, and answers one question: is this name well-formed enough
to sign?

Spelling and reach are separate concerns. The entries below are the lexicon the propagation runs
over rather than the set of legal capabilities. `sensor.temperature` reaches `sensor.capture` by
nearness, and `OPEN_FAMILIES` accepts a physical device the moment a host advertises it. Spec:
`agience-pharos/genesis/CAPABILITY-AS-ARTIFACT.md` — *"a capability is an artifact; matching is
propagation — nearest, hop the gap, propagate from there"*
([[capability-is-an-artifact-matched-by-propagation]]). Spelling is a typo check; reach is a
measurement.

Two mechanisms stand behind a capability, on two different boundaries:

  * **hardware** — what a prism can physically do. Found by propagation (`prism.propagation`:
    `screened_accumulate` for *nearest*, `spread_graph` for *hop the gap and propagate from there*).
  * **permission** — what the energy is granted. CRUDEASIO grants through the lightcone
    (`mantle/db/access.py`), which is the one decision point for access everywhere else in
    the system ([[access-is-crudeasio-grants]]).

Authorization follows the grant on the energy: holding the string `fs.write` grants nothing. Each
description below says what the capability does, which is what a lexicon knows.

Stdlib-only (no imports beyond typing) so a bare host, or a generator emitting the language-neutral
JSON for prism-js / prism-c, can read it without pulling in the Prism runtime.
"""
from __future__ import annotations

from typing import Dict

# ── The lexicon: known spellings, not the set of legal capabilities — see the header. ─────────
CAPABILITY_KINDS: Dict[str, str] = {
    # storage / filesystem
    "fs.read":       "read files within the granted scope",
    "fs.write":      "write files within the granted scope",
    "storage.kv":    "key-value storage (browser storage, small state)",
    # network — GET-only is a distinct kind on purpose (the read-only external-operator rule)
    "net.get":       "outbound HTTP GET (read-only web)",
    "net.request":   "outbound HTTP any-method (write-capable)",
    # compute
    "compute.local": "run the pattern in-process on the host runtime",
    "compute.wasm":  "run a wasm bundle in the host's wasm sandbox",
    "compute.gpu":   "GPU compute (webgpu / cuda-class)",
    # the store
    "store.read":    "read artifacts through the light-cone",
    "store.write":   "write artifacts through the light-cone",
    # presentation / human
    "ui.render":     "mount a UI surface (browser/facet card via the agience-card bridge field)",
    "human.ask":     "human-in-the-loop questionnaire (the Cuddler interface)",
    # physical world
    "sensor.capture":   "capture from a physical sensor (camera, mic, telemetry)",
    "actuator.control": "drive a physical actuator",
}

# Families accepted by prefix. Physical devices are unbounded, so a host advertises
# `sensor.temperature` or `actuator.relay` without waiting on a vocabulary release, which is what
# lets a prism be plug-and-play. The two spellings above are exemplars of these families rather than
# the whole set. Mirrored in prism-c (`is_known_capability`) and prism-js
# (`OPEN_CAPABILITY_FAMILIES`); `agience-cloud/deploy/capability_drift.py` checks all three agree.
OPEN_FAMILIES = ("sensor.", "actuator.")


def is_known_capability(kind: str) -> bool:
    """A spelling check. Is `kind` a name a host may sign into a manifest?

    Its job is to catch `webgpu` as a typo for `compute.gpu` at `prism init`. It is silent about
    whether a capability is present, reachable, or permitted, each of which is answered elsewhere:

      * **present / reachable** → propagation (`prism.propagation`), nearest and hop-the-gap. A
        crystal's `needs` seed a field over the prism's capability artifacts and the match is the
        nearest sufficiently-energised one, so `sensor.temperature` reaches `sensor.capture` by
        nearness. Deciding a match here would be the set-membership shape the propagation model
        replaces ([[signals-propagate]]).
      * **permitted** → the grant on the energy (`mantle/db/access.py`).

    Use this rather than `kind in CAPABILITY_KINDS`: bare membership excludes every real device
    (`sensor.temperature`), which is precisely the plug-and-play case. A bare family prefix is not
    itself a capability, since `sensor.` names no device — hence the length test below.
    """
    if kind in CAPABILITY_KINDS:
        return True
    return any(kind.startswith(p) and len(kind) > len(p) for p in OPEN_FAMILIES)


__all__ = ["CAPABILITY_KINDS", "OPEN_FAMILIES", "is_known_capability"]
