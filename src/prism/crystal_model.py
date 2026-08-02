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

from .canonical import canonical_json as _canonical_json
from .capabilities import OPEN_FAMILIES  # stdlib-only sibling; keeps the bare-host guarantee

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
    """RFC 8785 (JCS) canonical JSON bytes — re-exported from the ONE source, `prism.canonical`.

    Kept as a name here because every existing importer uses `crystal_model.canonical_json`; the
    implementation lives in `prism/canonical.py` so beam and the bare-environment installer can vendor
    a byte-identical copy (their vendoring is gated — see that module's header).
    """
    return _canonical_json(obj)


#: The fields a BUNDLE's sha256 covers, in the order the payload is built.
#:
#: ⚠ THE PUBLISHER AND THE VERIFIER MUST AGREE, AND ONE OF THEM NO LONGER EXISTS.
#: `ember/runtime/runner.py::_canonical` carried this tuple with the docstring "build_bundles.
#: canonical, reproduced exactly (keys, ordering, separators) — the runner must recompute the SAME
#: payload the publisher hashed, or verification means nothing." `build_bundles.py` is GONE from the
#: tree, so what remained was a reproduction of an absent original: nothing to check it against, and
#: no definition for a future publisher to build to.
#:
#: It lives here because a bundle's manifest shape is a CONTRACT, next to `crystal_sha` which does
#: the same job for a crystal. Anyone writing the publisher back should implement it against this.
BUNDLE_SHA_FIELDS = ("group", "entry_module", "register_fns", "host_seams", "modules")


def bundle_canonical(bundle: Dict[str, Any]) -> bytes:
    """The bytes a BUNDLE's sha256 is taken over — the manifest fields, canonically serialized.

    Raises KeyError on a malformed bundle rather than hashing a partial payload: a sha over four of
    five fields is a valid-looking hash of the wrong thing."""
    payload = {k: bundle[k] for k in BUNDLE_SHA_FIELDS}
    return canonical_json(payload)


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
        else:
            # 🔴 THE SPELLING CHECK WAS MISSING HERE AND PRESENT IN prism-js (added 2026-07-29,
            # Contract Builder). Measured: on a crystal requiring `totally.bogus`, JavaScript reported
            # the unknown kind and Python reported nothing — so **Python, which is the canonical
            # implementation AND the side that SIGNS crystals** (`crystal_artifact`), would validate and
            # sign a requirement no platform will honour. prism-js's own comment names this exact
            # failure mode: *"an unknown kind here would be signed into an artifact and then refused by
            # the platform (how prism-c shipped `webgpu`)"* — and the signer was the one without the
            # guard.
            # SPELLING, NOT MATCHING: `is_known_capability` accepts open-family members
            # (`sensor.*` / `actuator.*`) by prefix, so this refuses typos without refusing real
            # devices. Matching is propagation's job (`capability_reach`), never this function's.
            # Message text is byte-identical to prism-js's so the shared vectors can pin both.
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
    """The OPEN family a capability belongs to (`sensor.` / `actuator.`), or None. A bare prefix is
    not a member of its own family — `sensor.` names no device."""
    for p in OPEN_FAMILIES:
        if kind.startswith(p) and len(kind) > len(p):
            return p
    return None


def capability_reach(required: List[str], advertised: List[str]) -> List[Dict[str, Any]]:
    """MEASURE the junction instead of testing membership: for each required capability, the
    NEAREST thing this prism affords, and how far away it is.

    Returns one entry per requirement: `{"required", "matched", "basis", "hops"}` where basis is
    `"exact"` (0 hops), `"family"` (1 hop — a different member of the same OPEN family, e.g. the
    crystal wants `sensor.temperature` and the prism affords `sensor.capture`), or `None` (out of
    reach entirely). This is what lets a refusal name a REACH gap rather than a spelling gap.

    ⚠ SEAM (flagged, honest default — [[no-arbitrary-caps]]). A 1-hop family neighbour is REPORTED
    but does NOT satisfy the gate below, and that is deliberate: `sensor.thermal` is not a
    substitute for `sensor.temperature` just because both are sensors, and inventing a
    "near enough" threshold here would be fitting. Whether family-nearness may SATISFY is John's
    call and belongs AFTER the grant gate lands (`NEXT.md §Q` — discharge is authorized by the grant
    on the energy, not by owning a name), because loosening the match before authorization moves is
    a straight widening of the permission surface.

    ⚠ Note the STRUCTURAL limit: this module is stdlib-only on purpose, so a bare host can verify a
    crystal BEFORE grounding it. Geodesic/measured propagation (`match.select`, `spread_graph`)
    needs the geometry store and therefore cannot run here — the true propagation match belongs on
    the side that carries the lattice (ember/chorus), with this junction reporting structural reach.
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

    Answered by MEASURING reach (`capability_reach`) rather than by a subset test — the gate itself
    still requires every requirement to be met EXACTLY, so this is not a behaviour change; what it
    buys is that the near-miss is now measurable and reportable instead of collapsing to a bare
    False. See `capability_reach` for the flagged seam on whether 1-hop family nearness should ever
    satisfy (it must not, until discharge is grant-authorized — `NEXT.md §Q`).
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
    "required_capabilities", "activates_on", "capability_reach", "crystal_artifact", "verify",
]
