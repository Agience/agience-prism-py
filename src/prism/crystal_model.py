# Canonical home: the crystal contract lives in prism — the host owns the wire format it grounds,
# and `activates_on` is the prism junction gate. Stdlib-only so a bare host validates, hashes and
# verifies a crystal before grounding it (client-side integrity, computed locally rather than taken
# from the server). crystal (=> prism) re-exports this; ember reaches it through crystal. One home.
"""The crystal — the shareable unit of structure (OPERATOR-ARCHITECTURE §12).

    CRYSTAL = FACETS (signal conduits) + TEKTONS (condensors) + ORGANONS (invoked by
              condensation) ... grown on a LATTICE (the seed shard is inside the crystal).

A crystal is pure structure — inert, content-addressed, shareable: an artifact. An ember is
energized crystals (grounded on a prism, energy flowing, the lattice filling). Structure ships,
state grows: you share the crystal, and the charge stays where it was raised.

Signal flow through one crystal: signal enters a facet (conduit in) → a tekton condenses it →
threshold → organons fire (the discharge) → result exits a facet. This is the capacitor model
(§10) with named parts: facets are the terminals, the tekton the condensing process, the organon
the discharge element.

The prism junction is bidirectional and gated by named capabilities (the operator/capability
vocabulary): a prism activates a crystal (grounds it), and a crystal activates through a prism
(actuates the world). `activates_on` answers both with one subset check — any crystal, any prism,
capability-permitting.

Stdlib-only on purpose (json/hashlib): a bare host must be able to validate and hash a crystal
before deciding to ground it — same rule as bundle_manifest.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from .canonical import canonical_json as _canonical_json
from .capabilities import OPEN_FAMILIES  # stdlib-only sibling; keeps the bare-host guarantee

CRYSTAL_CONTENT_TYPE = "application/vnd.agience.crystal+json"

#: A facet is a signal conduit, bidirectional. A human view is a facet whose far side is a
#: human; a webhook is one whose far side is a machine. `direction` declares the conduit's
#: allowed flow; "both" is the general case.
#:
#: The binding is the waveform (Sec.12 closure): a facet's contract is the signal itself, in
#: its ordered waveform, rather than a declared schema. Compatibility at a channel is measured
#: (does the waveform couple - impedance/K_signal at the joint frame) rather than gated by
#: type, which keeps a conduit from becoming a step-I/O pipeline stage. A facet's one
#: structural obligation is order-preservation: the Screen is ordered, so a conduit carries
#: the order it was given. The content type is born at the tekton - condensation is "signal
#: to content type" - so an optional `content_type` on a facet is a descriptive hint for
#: discovery. Waveform before condensation (continuous, measured); typed artifact after it
#: (discrete, signed) - the waveform-provenance boundary, with the tekton as the crossing point.
FACET_DIRECTIONS = ("in", "out", "both")

_REQUIRED = ("name", "facets", "tektons", "created_by")


def canonical_json(obj: Any) -> bytes:
    """RFC 8785 (JCS) canonical JSON bytes — re-exported from the one source, `prism.canonical`.

    Available under this name because importers reach it as `crystal_model.canonical_json`; the
    implementation lives in `prism/canonical.py`, which is now the only copy of it in the workspace
    — the last vendored copy was deleted 2026-08-25 (see that module's header).
    """
    return _canonical_json(obj)


#: The fields a bundle's sha256 covers, in the order the payload is built.
#:
#: A bundle's manifest shape is a contract, so it lives here beside `crystal_sha`, which does the
#: same job for a crystal. A publisher implements against this tuple.
BUNDLE_SHA_FIELDS = ("group", "entry_module", "register_fns", "host_seams", "modules")


def bundle_canonical(bundle: Dict[str, Any]) -> bytes:
    """The bytes a BUNDLE's sha256 is taken over — the manifest fields, canonically serialized.

    Raises KeyError on a malformed bundle rather than hashing a partial payload: a sha over four of
    five fields is a valid-looking hash of the wrong thing."""
    payload = {k: bundle[k] for k in BUNDLE_SHA_FIELDS}
    return canonical_json(payload)


def crystal_sha(crystal: Dict[str, Any]) -> str:
    """Content-address the structure: everything except the sha field itself."""
    body = {k: v for k, v in crystal.items() if k != "sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def validate(crystal: Dict[str, Any]) -> List[str]:
    """Schema check — returns the problems list ([] = valid). Every problem is collected rather
    than stopping at the first, so one pass names everything a caller has to fix, and a crystal
    grounds only once the list is empty.

    Shape:
      name         : the crystal id
      facets       : [{name, direction, content_type?}]     — the conduits (≥1: a crystal with
                     no facet is sealed glass, and nothing enters or leaves)
      tektons      : [{name, domain}]                       — the condensors (≥1: condensation
                     happens in a tekton)
      organons     : [{name, requires?: [capability, ...]}] — the invoked instruments (op.*).
                     May be empty: a pure-conduit crystal routes without transforming.
      lattice_seed : {artifacts?: [...], collections?: [...]} — optional seed shard; the lattice
                     a shared crystal starts from. State grows from here and stays local.
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
        else:
            from .capabilities import is_known_capability
            for o in organons:
                for r in o.get("requires") or []:
                    if not is_known_capability(r):
                        p.append("organon %s: unknown capability kind %s" % (o.get("name"), r))
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


def _family_of(kind: str) -> Any:
    """The open family a capability belongs to (`sensor.` / `actuator.`), or None. Membership needs
    something after the prefix — a bare `sensor.` names no device."""
    for p in OPEN_FAMILIES:
        if kind.startswith(p) and len(kind) > len(p):
            return p
    return None


def capability_reach(required: List[str], advertised: List[str]) -> List[Dict[str, Any]]:
    """Measure the junction instead of testing membership: for each required capability, the
    nearest thing this prism affords, and how far away it is.

    Returns one entry per requirement: `{"required", "matched", "basis", "hops"}` where basis is
    `"exact"` (0 hops), `"family"` (1 hop — a different member of the same open family, e.g. the
    crystal wants `sensor.temperature` and the prism affords `sensor.capture`), or `None` (out of
    reach entirely). This is what lets a gap be reported as a reach gap rather than a spelling gap.

    """
    adv = [a for a in (advertised or [])]
    adv_set = set(adv)
    out: List[Dict[str, Any]] = []
    for r in required:
        if r in adv_set:
            out.append({"required": r, "matched": r, "basis": "exact", "hops": 0})
            continue
        fam = _family_of(r)
        near = sorted(a for a in adv if fam is not None and _family_of(a) == fam)
        if near:
            out.append({"required": r, "matched": near[0], "basis": "family", "hops": 1})
        else:
            out.append({"required": r, "matched": None, "basis": None, "hops": None})
    return out


def activates_on(crystal: Dict[str, Any], prism_capabilities: List[str]) -> bool:
    """The bidirectional prism junction. Grounding-in and actuating-out are the same question.

    Answered by measuring reach (`capability_reach`) rather than by a subset test: the gate requires
    every requirement to be met exactly, and the near miss stays measurable and reportable instead of
    collapsing to a bare False. 1-hop family nearness is measured but does not satisfy the gate.
    """
    return all(m["basis"] == "exact"
               for m in capability_reach(required_capabilities(crystal), prism_capabilities))


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
    """Re-hash a crystal artifact's content and raise ValueError on mismatch — the integrity gate,
    checked before grounding as the bundle runner does. Returns the parsed crystal on success."""
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
    "required_capabilities", "activates_on", "capability_reach", "crystal_artifact", "verify",
]
