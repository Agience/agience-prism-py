# CANONICAL HOME (2026-07-24): the crystal CONTRACT lives in PRISM — the host owns the
# wire-format it grounds, and `activates_on` IS the prism junction gate. Stdlib-only so a bare host
# validates/hashes/verifies a crystal BEFORE grounding it (client-side integrity, never trusting the
# server). crystal (=> prism) re-exports this; ember reaches it through crystal. ONE home, no copy.
"""THE CRYSTAL — the shareable unit of structure (OPERATOR-ARCHITECTURE §12).

    CRYSTAL = FACETS (signal conduits) + TEKTONS (condensors) + ORGANONS (invoked by
              condensation) ... grown on a LATTICE (the seed shard is INSIDE the crystal).

A crystal is PURE STRUCTURE — inert, content-addressed, shareable: an artifact. An ember is
ENERGIZED crystals (grounded on a prism, energy flowing, the lattice filling). Structure ships,
state grows: you share the crystal, never the charge.

Signal flow through one crystal: signal enters a FACET (conduit in) → a TEKTON condenses it →
threshold → ORGANONS fire (the discharge) → result exits a facet. This is the capacitor model
(§10) with named parts: facets are the terminals, the tekton the condensing process, the organon
the discharge element.

The prism junction is BIDIRECTIONAL and gated by NAMED capabilities (beam's operator/capability
vocabulary): a prism ACTIVATES a crystal (grounds it), and a crystal ACTIVATES THROUGH a prism
(actuates the world). `activates_on` answers both with one subset check — any crystal, any prism,
capability-permitting.

Stdlib-only on purpose (json/hashlib): a bare host must be able to validate and hash a crystal
before deciding to ground it — same rule as bundle_manifest.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

CRYSTAL_CONTENT_TYPE = "application/vnd.agience.crystal+json"

#: A facet is a signal CONDUIT, bidirectional. A human view is a facet whose far side is a
#: human; a webhook is one whose far side is a machine. `direction` declares the conduit's
#: allowed flow; "both" is the general case.
#:
#: THE BINDING IS THE WAVEFORM (Sec.12 closure): a facet's contract is the signal itself, in
#: its ordered waveform - NEVER a declared schema. Compatibility at a channel is MEASURED
#: (does the waveform couple - impedance/K_signal at the joint frame), not gated by type;
#: a typed gate at the conduit would be a step-I/O pipeline contract, which the propagation
#: rule forbids. A facet's one structural obligation is ORDER-PRESERVATION (the Screen is
#: ordered; a conduit that scrambles is a destroyer, not a conduit). The content TYPE is BORN
#: at the tekton - condensation IS "signal to content type" - so an optional `content_type`
#: on a facet is a descriptive HINT for discovery, never a gate. Waveform before condensation
#: (continuous, measured); typed artifact after it (discrete, signed) - the waveform-provenance
#: boundary, with the tekton as the crossing point.
FACET_DIRECTIONS = ("in", "out", "both")

_REQUIRED = ("name", "facets", "tektons", "created_by")


def canonical_json(obj: Any) -> bytes:
    """Sorted-keys, no-whitespace JSON bytes — the same logical crystal always hashes the same
    on any host (the property that makes the sha a stable cross-environment ref)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def crystal_sha(crystal: Dict[str, Any]) -> str:
    """Content-address the STRUCTURE: everything except the sha field itself."""
    body = {k: v for k, v in crystal.items() if k != "sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def validate(crystal: Dict[str, Any]) -> List[str]:
    """Schema check — problems list ([] = valid). Loud on shape errors: an invalid crystal must
    refuse to ground, never half-load.

    Shape:
      name         : the crystal id
      facets       : [{name, direction, content_type?}]     — the conduits (≥1: a crystal with
                     no facet is sealed glass — nothing can enter or leave)
      tektons      : [{name, domain}]                       — the condensors (≥1: nothing
                     condenses without one)
      organons     : [{name, requires?: [capability, ...]}] — the invoked instruments (op.*).
                     MAY be empty: a pure-conduit crystal routes without transforming.
      lattice_seed : {artifacts?: [...], collections?: [...]} — optional seed shard; the lattice
                     a shared crystal starts from. State GROWS from here; it never ships back.
      created_by   : resolvable creator (provenance gates grounding — the Higgs rule)
    """
    p: List[str] = []
    for k in _REQUIRED:
        if not crystal.get(k):
            p.append("missing required field: %s" % k)
    facets = crystal.get("facets") or []
    if not isinstance(facets, list) or (facets and not all(isinstance(f, dict) for f in facets)):
        p.append("facets must be a list of objects")
    else:
        for f in facets:
            if not f.get("name"):
                p.append("every facet needs a name")
            if f.get("direction") not in FACET_DIRECTIONS:
                p.append("facet %r: direction must be one of %s" % (f.get("name"), (FACET_DIRECTIONS,)))
        if isinstance(crystal.get("facets"), list) and not facets:
            p.append("a crystal needs at least one facet (a sealed crystal conducts nothing)")
    tektons = crystal.get("tektons") or []
    if not isinstance(tektons, list) or not all(isinstance(t, dict) and t.get("name") for t in tektons):
        p.append("tektons must be a non-empty list of named objects (nothing condenses without one)")
    organons = crystal.get("organons")
    if organons is not None:
        if not isinstance(organons, list) or not all(isinstance(o, dict) and o.get("name") for o in organons):
            p.append("organons must be a list of named objects")
    seed = crystal.get("lattice_seed")
    if seed is not None and not isinstance(seed, dict):
        p.append("lattice_seed must be an object {artifacts?, collections?}")
    return p


def required_capabilities(crystal: Dict[str, Any]) -> List[str]:
    """The union of every organon's named capability requirements — what a prism must advertise
    for this crystal to fully activate. Sorted for determinism."""
    caps: set = set()
    for o in crystal.get("organons") or []:
        caps.update(o.get("requires") or [])
    return sorted(caps)


def activates_on(crystal: Dict[str, Any], prism_capabilities: List[str]) -> bool:
    """The bidirectional prism junction, as one subset check: every capability any organon
    requires must be NAMED in the prism's advertised set. Grounding-in and actuating-out are the
    same gate — actuator.* / sensor.* capabilities are names like any other."""
    return set(required_capabilities(crystal)) <= set(prism_capabilities or [])


def crystal_artifact(crystal: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the store artifact: the crystal (structure) is the content, the sha is stamped,
    the manifest summary rides in context. The one place the wire shape is built."""
    problems = validate(crystal)
    if problems:
        raise ValueError("invalid crystal: " + "; ".join(problems))
    body = dict(crystal)
    body["sha256"] = crystal_sha(body)
    return {
        "id": body["name"],
        "name": body["name"],
        "content_type": CRYSTAL_CONTENT_TYPE,
        "context": json.dumps({
            "sha256": body["sha256"],
            "facets": [f["name"] for f in body.get("facets", [])],
            "tektons": [t["name"] for t in body.get("tektons", [])],
            "organons": [o["name"] for o in body.get("organons") or []],
            "requires": required_capabilities(body),
            "created_by": body["created_by"],
        }),
        "content": json.dumps(body, sort_keys=True),
    }


def verify(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Re-hash a crystal artifact's content and refuse on mismatch — the integrity gate, same
    refuse-before-grounding rule as the bundle runner. Returns the parsed crystal on success."""
    body = json.loads(artifact["content"])
    claimed = body.get("sha256")
    actual = crystal_sha(body)
    if claimed != actual:
        raise ValueError("crystal integrity failure: claimed sha256=%s but structure hashes to %s "
                         "— refusing to ground unverified structure" % (claimed, actual))
    return body


__all__ = [
    "CRYSTAL_CONTENT_TYPE", "FACET_DIRECTIONS",
    "canonical_json", "crystal_sha", "validate",
    "required_capabilities", "activates_on", "crystal_artifact", "verify",
]
