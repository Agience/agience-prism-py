# CANONICAL HOME (2026-07-29): the CAPABILITY VOCABULARY lives in PRISM — the prism is what
# physically offers and enforces these, so it owns the names. `crystal.operator_schema` re-exports
# this; ember reaches it through crystal. ONE home, no copy — the same rule `prism.crystal_model`
# already follows for the crystal contract. Stdlib-only (no imports beyond typing) so a bare host,
# or a generator emitting the language-neutral JSON for prism-js / prism-c, can read it without
# pulling in the Prism runtime.
"""THE CAPABILITY VOCABULARY — the names an environment can offer, and a pattern can require.

A capability is a named, prism-provided AFFORDANCE: a PROBE (is it present *here*?) + a HANDLE
(how to do it) — see `prism.environment`. This module is only the NAMES and what each one means;
the measurement lives next door, deliberately, so the vocabulary stays inert and shareable.

The permission boundary and the hardware boundary are the SAME boundary: each kind names something
a Prism can physically offer AND enforce as a sandbox edge on its platform. That is why the list is
versioned and grown deliberately rather than extended ad hoc at a call site.
"""
from __future__ import annotations

from typing import Dict

# ── Layer 1: the capability vocabulary (versioned; grow deliberately) ─────────
CAPABILITY_KINDS: Dict[str, str] = {
    # storage / filesystem
    "fs.read":       "read files within the granted scope",
    "fs.write":      "write files within the granted scope",
    "storage.kv":    "key-value storage (browser storage, small state)",
    # network — GET-only is a distinct kind on purpose (the read-only external-operator rule)
    "net.get":       "outbound HTTP GET (read-only web)",
    "net.request":   "outbound HTTP any-method (write-capable — higher trust rung required)",
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
    "actuator.control": "drive a physical actuator (higher trust rung required)",
}

# Families accepted by PREFIX (John, 2026-07-29: OPEN families win). Physical devices are unbounded,
# so a host advertises `sensor.temperature` or `actuator.relay` without waiting on a vocabulary
# release — that is what lets a prism be plug-and-play. The two spellings above are exemplars of
# these families, not the whole set. Mirrored in prism-c (`is_known_capability`) and prism-js
# (`OPEN_CAPABILITY_FAMILIES`); `agience-bundle/deploy/capability_drift.py` checks all three agree.
OPEN_FAMILIES = ("sensor.", "actuator.")


def is_known_capability(kind: str) -> bool:
    """Is `kind` a valid capability name — a base member, or a member of an OPEN family?

    Use this rather than `kind in CAPABILITY_KINDS`: bare membership rejects every real device
    (`sensor.temperature`), which is precisely the plug-and-play case. A bare family prefix is not
    itself a capability — `sensor.` names no device.
    """
    if kind in CAPABILITY_KINDS:
        return True
    return any(kind.startswith(p) and len(kind) > len(p) for p in OPEN_FAMILIES)


__all__ = ["CAPABILITY_KINDS", "OPEN_FAMILIES", "is_known_capability"]
