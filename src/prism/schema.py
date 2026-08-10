"""Types & schemas — strong typing bound by a content-addressed edge, and the context contract.

The principle that makes this different: the ontology is indexed on context, not content. Classic
systems index *content*: chunk the bytes, embed the chunks, retrieve over content. Agience indexes
*context* — the structured description. Content stays opaque (ciphertext, binary, a video); the
**context** is what anchors route on, what carries mass/provenance/edges, what the ontology reasons
about. Three consequences follow:

* **Blind replication works** because the ontology never needs the content — only the context.
  A leaf holds ciphertext it cannot read and still routes it (`ember`).
* **Dark matter is the un-described** — an artifact with no context yet has nothing to index on,
  so it does not surface (`mass.surfacable`). Describing it produces context (and edges), which
  is what turns it luminous. Edges are observations.
* A **describer is the content -> context adapter, and it is per content_type** — you observe a
  PDF differently than a Lean proof than a video. The describer is the observation operator for
  a type. So a type definition is one coherent contract:

      context_schema   the shape of the context (what the ontology indexes)
      describer        the handler that produces that context from the content
      operations       what you can do with the thing (crystal dispatch)

  `context_schema` constrains what the describer emits; the ontology indexes what it emits. The
  three are one object, per content_type — which is exactly the `type.json` already in the repo.

The system already has more type machinery than "content_type is a MIME label" suggests. A
persona's `type.json` carries `content_type`, `version`, `inherits`, `context_schema`, `ui`,
`operations`, `describer` — and these are meant to be artifacts (`application/vnd.agience.type+json`).
Three precise gaps make the typing weaker than it looks:

1. **`context_schema` is prose.** e.g. `"license_id": "string — license identifier"`. Human
   documentation, not a machine contract — nothing can validate against it.
2. **`version` is a mutable integer.** An artifact says it is `content_type X`; if X's schema
   changes, every existing artifact silently "conforms" to a *different* contract. There is no
   binding to a specific version.
3. **Binding is by the `content_type` string.** That string is the right key for *coarse
   dispatch* (crystal routes operations by it), but it is the wrong key for a *precise contract*:
   `application/json` tells you nothing about the fields, and one mutable schema is shared by all.

The binding is an edge to a content-addressed schema artifact — not carried in the artifact
(duplicating the schema across every artifact, with no shared point to migrate) and not the
`content_type` string alone (mutable, unversioned, coarse). The layering:

    content_type   the coarse type — routing / dispatch / operations (crystal). unchanged.
    schema edge    the precise, versioned structural contract. -> a schema artifact's id.
    inherits       schema composition via parent edges, formalizing what type.json already has.

Versioning falls out of content-addressing: a schema artifact's id is a hash of its content, so
"conforms to schema `abc…`" names an exact, immutable version. Change the schema → new content →
new id → a new artifact; the old one still exists, and artifacts bound to it still have their
contract. No silent drift, which the mutable `version: 1` cannot promise.

That follows for free from what already exists elsewhere in the system:

* A schema is an artifact, so it has **mass/provenance** — a `human_validated` schema is
  authoritative; a model-proposed one is a hypothesis until adopted. Stronger typing inherits the
  whole trust model (`prism.mass`) at no cost.
* **Migration = revision.** Re-pointing an artifact's schema edge from v1 to v2 is a revision, so
  `may_revise` already governs it: a low-authority schema change is a PROPOSE, not a silent
  REPLACE. The typing system reuses the inertia model verbatim.
* A schema is to artifacts what an **anchor** is to vectors: a shared structural reference,
  validated by *adoption* (a schema nothing conforms to does not promote, exactly like an anchor
  nothing clusters into). Same `ontology_proposal` rung, same density gate.

What this module is, and is not: the **binding + versioning** primitive. It builds a
content-addressed schema artifact, binds an artifact to one by edge, and reads the binding back. It
deliberately does not invent a validation format — production should adopt **JSON Schema** (a real,
permissive standard) rather than a home-grown one. `conforms()` here is a minimal structural check
for the seed and tests only, and says so.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .mass import Provenance
from .canonical import canonical_string as _jcs_string   # the one canonicaliser, used across prism

_SCHEMA_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "schemas.agience.ai")

SCHEMA_CONTENT_TYPE = "application/vnd.agience.type+json"   # a type/schema is itself an artifact
# The edge that binds an artifact to the exact schema version it conforms to. A *typed* edge,
# not a context field, because the binding is a relationship between two artifacts — and edges
# are how the graph already expresses that (a collection's membership is an edge, not a field).
SCHEMA_EDGE = "conforms_to"


def schema_id(content_type: str, fields: Dict[str, Any], inherits: Tuple[str, ...] = ()) -> str:
    """Deterministic id over the schema's content — so a changed schema is a different artifact.

    This is the whole versioning story: the id is `uuid5` of a canonical hash of
    `(content_type, fields, inherits)`. Two identical schemas get the same id (idempotent); any
    change — a new field, a tightened type, a different parent — yields a new id, and the old
    version keeps its own identity and its bound artifacts. `version: 1` (a mutable integer)
    cannot do this; content-addressing does it for free.
    """
    h = hashlib.sha256()
    h.update(b"agience/schema/v1")
    h.update(content_type.encode("utf-8"))
    h.update(_jcs_string(fields).encode("utf-8"))
    h.update(json.dumps(sorted(inherits), separators=(",", ":")).encode("utf-8"))
    return str(uuid.uuid5(_SCHEMA_NS, h.hexdigest()))


def type_definition(content_type: str, fields: Dict[str, Any], *,
                    describer: Optional[dict] = None,
                    inherits: Tuple[str, ...] = (), description: str = "") -> dict:
    """A type definition, as a content-addressed artifact — shaped for Mantle.

    It carries the whole per-type contract: the `context_schema` (`fields`), the **describer**
    (content -> context adapter for this type), and composition (`inherits`). `fields` should be
    a machine-checkable schema (JSON-Schema-shaped in production).

    Why the describer belongs here and not in a separate place: `context_schema` says what the
    context looks like, and the describer is what *produces* it — the two must version together,
    or the ontology indexes fields the describer no longer emits. Content-addressing binds them:
    the id covers the schema, so a describer change that changes the emitted shape is a new type
    version. A schema+describer that agree is one object.

    Provenance defaults to `hypothesis`: a freshly proposed type is a claim about how things
    *should* be structured and described. It earns authority by adoption and validation, not by
    declaration — a type nothing conforms to ages out, exactly like an anchor nothing clusters
    into. A person can `stamp` it `human_validated`.
    """
    return {
        "id": schema_id(content_type, fields, tuple(inherits)),
        "content_type": SCHEMA_CONTENT_TYPE,
        "name": content_type,
        "context": {
            "provenance": Provenance.HYPOTHESIS.value,
            "target_content_type": content_type,   # the type this definition constrains
            "inherits": list(inherits),            # parent type content_types (composition)
            "fields": fields,                      # the context_schema — the ontology indexes this
            "describer": describer,                # content -> context adapter for this type
            "description": description,
        },
        "content": "",
    }


# The type definition IS the schema artifact — a schema without its describer is half a contract.
schema_artifact = type_definition


def bind(artifact: dict, schema_artifact_id: str) -> dict:
    """Bind an artifact to the exact schema version it conforms to — a typed edge, recorded so a
    reader can verify the contract. Copies (artifacts are content-addressed); returns the bound
    copy. Re-binding to a new schema id is a revision, governed by `may_revise` upstream.
    """
    out = dict(artifact)
    edges = list(out.get("edges") or [])
    # Drop any prior conforms_to edge — an artifact conforms to exactly one schema version.
    edges = [e for e in edges if not (isinstance(e, dict) and e.get("rel") == SCHEMA_EDGE)]
    edges.append({"rel": SCHEMA_EDGE, "target": schema_artifact_id})
    out["edges"] = edges
    return out


def schema_ref(artifact: dict) -> Optional[str]:
    """The schema artifact id this artifact claims to conform to, or None. A missing binding is
    honest — the artifact is `application/json`-loose, not falsely precise. (This is the typing
    analogue of `provenance_of` defaulting to UNKNOWN: absence is not conformance.)"""
    for e in artifact.get("edges") or []:
        if isinstance(e, dict) and e.get("rel") == SCHEMA_EDGE and e.get("target"):
            return e["target"]
    return None


def effective_fields(content_type: str, lookup) -> Dict[str, Any]:
    """Resolve a type's full field set: its own fields plus every ancestor's, via `inherits`.

    `inherits` already exists in the type.json files, but nothing else walks it: a consumer that
    reads a type's own fields directly validates a type that inherits `document` only against its
    own extra fields. This composes the chain.

    `lookup(content_type) -> type_definition | None` is injected (crystal supplies its registry),
    so core owns the *algorithm* and never depends on crystal — the same pattern as the mesh
    transport and the anchor cross-walk.

    Semantics, and each is a real decision:
    * **child overrides parent** — a field redefined in a subtype wins. Specialization tightens.
    * **depth-first, parents applied before the child** — so the override direction is correct.
    * **cycle-safe** — inheritance graphs can be malformed (A inherits B inherits A). A naive walk
      would loop forever; a `seen` set makes a cycle a no-op, not a hang. A missing parent is
      skipped, not fatal — an unresolved ancestor should not erase the fields we *can* resolve.
    """
    resolved: Dict[str, Any] = {}
    seen: set = set()

    def walk(ct: str) -> None:
        if ct in seen:
            return                       # cycle or diamond already handled — do not recurse again
        seen.add(ct)
        td = lookup(ct)
        if not isinstance(td, dict):
            return                       # unknown/unresolvable parent: skip, keep what we have
        ctx = td.get("context") or {}
        for parent in ctx.get("inherits") or []:
            walk(parent)                 # parents first...
        resolved.update(ctx.get("fields") or {})   # ...then self, so the child overrides
    walk(content_type)
    return resolved


def conforms(context: Dict[str, Any], fields: Dict[str, Any]) -> List[str]:
    """Minimal structural check — seed only. Returns a list of violations (empty == conforms).

    Not a schema engine. Production must use **JSON Schema** (permissive, standard, far richer:
    nesting, enums, formats, patterns). This exists so the binding/versioning primitive is
    demonstrable end-to-end without pulling a dependency into `core` prematurely. It reads the
    compact convention already in the type.json files: a value like ``"string"`` requires the
    field; a trailing ``?`` (``"string?"``) makes it optional.
    """
    kinds = {"string": str, "number": (int, float), "bool": bool, "object": dict, "array": list}
    problems: List[str] = []
    for field, spec in fields.items():
        # Read the compact convention the type.json files use: "<type>[?] — description" (the
        # description follows an em-dash or " - "). Array notation ("string[]") is presence-only
        # here; element types are for JSON Schema in production.
        decl = str(spec)
        for sep in ("—", " - "):        # em-dash, then hyphen
            if sep in decl:
                decl = decl.split(sep, 1)[0]
                break
        decl = decl.strip()
        optional = decl.endswith("?")
        base = decl.rstrip("?").strip()
        if field not in context:
            if not optional:
                problems.append(f"missing required field '{field}' ({base})")
            continue
        py = kinds.get(base.rstrip("[]"))     # tolerate array notation for the presence check
        is_array = base.endswith("[]")
        val = context[field]
        if is_array and not isinstance(val, list):
            problems.append(f"field '{field}' should be an array ({base})")
        elif not is_array and py is not None and not isinstance(val, py):
            problems.append(f"field '{field}' should be {base}, got {type(val).__name__}")
    return problems


def describer_of(type_def: dict) -> Optional[dict]:
    """The content -> context adapter a type declares, or None. A type with no describer cannot
    turn its content into indexable context — its artifacts stay dark until one exists. That is a
    real state to report, not an error: not every type is describable yet."""
    ctx = type_def.get("context") or {}
    return ctx.get("describer")


__all__ = [
    "SCHEMA_CONTENT_TYPE", "SCHEMA_EDGE",
    "schema_id", "type_definition", "schema_artifact", "describer_of",
    "bind", "schema_ref", "conforms", "effective_fields",
]
