"""Types & schemas: bind by a content-addressed edge; the type carries its describer.

The load-bearing claim: strong typing does not need a new mechanism. A type definition is an
artifact (so it has mass/provenance), its id is content-addressed (so versioning is immutable),
and an artifact binds to the exact version by a typed edge (so no silent contract drift).
"""
from __future__ import annotations

from prism.mass import Provenance, provenance_of
from prism.schema import (
    SCHEMA_CONTENT_TYPE, SCHEMA_EDGE, bind, conforms, describer_of, schema_id, schema_ref,
    type_definition,
)

PDF = "application/vnd.agience.pdf+json"
FIELDS = {"title": "string", "pages": "number", "summary": "string?"}
DESC = {"kind": "mcp_tool", "target": "astra.extract_pdf"}


def test_a_type_is_a_content_addressed_artifact() -> None:
    td = type_definition(PDF, FIELDS, describer=DESC, inherits=("application/json",))
    assert td["content_type"] == SCHEMA_CONTENT_TYPE     # a type is an artifact
    assert td["id"] == schema_id(PDF, FIELDS, ("application/json",))
    # It has provenance, so stronger typing inherits the trust model: a fresh type is a claim.
    assert provenance_of(td) is Provenance.HYPOTHESIS


def test_versioning_falls_out_of_content_addressing() -> None:
    """The property. A changed schema is a different artifact; the old version keeps its id and
    its bound artifacts. A mutable `version: 1` integer cannot promise this."""
    v1 = type_definition(PDF, FIELDS, describer=DESC)
    v2 = type_definition(PDF, {**FIELDS, "author": "string"}, describer=DESC)   # one field added
    assert v1["id"] != v2["id"]
    # ...but identical inputs are idempotent (same id everywhere — no accidental fork).
    assert type_definition(PDF, FIELDS, describer=DESC)["id"] == v1["id"]


def test_the_describer_versions_WITH_the_schema() -> None:
    """The describer produces the context; the schema constrains it. They are one contract, so a
    type carries both — you cannot index fields the describer no longer emits."""
    td = type_definition(PDF, FIELDS, describer=DESC)
    assert describer_of(td) == DESC
    assert td["context"]["fields"] == FIELDS            # context_schema — what the ontology indexes
    # a type with no describer is honest about it: its artifacts stay dark until one exists
    assert describer_of(type_definition(PDF, FIELDS)) is None


def test_an_artifact_binds_to_an_exact_version_by_edge() -> None:
    td = type_definition(PDF, FIELDS, describer=DESC)
    art = bind({"id": "doc-1", "content_type": PDF}, td["id"])
    assert schema_ref(art) == td["id"]
    # the binding is a typed edge, not a context field — a relationship between two artifacts
    assert any(e["rel"] == SCHEMA_EDGE for e in art["edges"])


def test_rebinding_replaces_the_one_conformance_edge() -> None:
    """An artifact conforms to exactly one schema version. Re-binding (a migration) swaps the
    edge, it does not accumulate — and upstream that swap is a revision, governed by may_revise."""
    v1 = type_definition(PDF, FIELDS, describer=DESC)
    v2 = type_definition(PDF, {**FIELDS, "author": "string"}, describer=DESC)
    art = bind(bind({"id": "doc-1", "content_type": PDF}, v1["id"]), v2["id"])
    edges = [e for e in art["edges"] if e["rel"] == SCHEMA_EDGE]
    assert len(edges) == 1 and edges[0]["target"] == v2["id"]


def test_absence_of_a_binding_is_honest_not_false_precision() -> None:
    """No conforms_to edge => None. The artifact is loosely typed, not falsely precise — the
    typing analogue of provenance defaulting to UNKNOWN. Absence is not conformance."""
    assert schema_ref({"id": "x", "content_type": PDF}) is None


def test_bind_copies_it_does_not_mutate() -> None:
    """Artifacts are content-addressed — editing one in place changes what it is."""
    original = {"id": "doc-1", "content_type": PDF}
    bind(original, "schema-abc")
    assert "edges" not in original


def test_conforms_is_a_seed_that_catches_the_obvious() -> None:
    """Seed only (production: JSON Schema). Still: required-field and type violations must be
    caught, or 'strong typing' is decorative."""
    assert conforms({"title": "Q", "pages": 10}, FIELDS) == []              # valid
    assert conforms({"title": "Q", "pages": 10, "summary": "s"}, FIELDS) == []  # optional present
    problems = conforms({"pages": "ten"}, FIELDS)                            # missing + wrong type
    assert any("missing required field 'title'" in p for p in problems)
    assert any("'pages' should be number" in p for p in problems)


def test_inheritance_changes_identity() -> None:
    """`inherits` is composition, and it is part of the contract — a type that inherits a
    different parent is a different type, so it must have a different id."""
    a = type_definition(PDF, FIELDS, inherits=("application/json",))
    b = type_definition(PDF, FIELDS, inherits=("application/vnd.agience.document+json",))
    assert a["id"] != b["id"]
    # order within inherits must not matter (it is a set of parents, not a sequence)
    c = type_definition(PDF, FIELDS, inherits=("a", "b"))
    d = type_definition(PDF, FIELDS, inherits=("b", "a"))
    assert c["id"] == d["id"]


# --------------------------------------------------------------------------- inheritance
def _chain():
    return {
        "application/json": type_definition("application/json", {"id": "string"}),
        "doc": type_definition("doc", {"title": "string", "author": "string?"},
                               inherits=("application/json",)),
        "pdf": type_definition("pdf", {"pages": "number", "author": "string"}, inherits=("doc",)),
    }


def test_effective_fields_walks_the_inheritance_chain() -> None:
    """Inherited constraints must be visible, or a subtype is validated only against its own extra
    fields while its parents' requirements go unchecked."""
    from prism.schema import effective_fields
    eff = effective_fields("pdf", _chain().get)
    assert set(eff) == {"id", "title", "author", "pages"}   # own + all ancestors


def test_child_overrides_parent() -> None:
    """Specialization tightens: pdf redefines author as required (parent had it optional)."""
    from prism.schema import effective_fields, conforms
    eff = effective_fields("pdf", _chain().get)
    assert eff["author"] == "string"                        # not "string?"
    assert any("author" in p for p in conforms({"id": "x", "title": "t", "pages": 1}, eff))


def test_a_missing_parent_is_skipped_not_fatal() -> None:
    """An unresolved ancestor must not erase the fields that can be resolved — partial is better
    than nothing, and a registry mid-population should still validate what it knows."""
    from prism.schema import effective_fields
    defs = {"pdf": type_definition("pdf", {"pages": "number"}, inherits=("missing-parent",))}
    eff = effective_fields("pdf", defs.get)
    assert eff == {"pages": "number"}                       # own fields survive the missing parent


def test_inheritance_is_cycle_safe() -> None:
    """A malformed graph (A inherits B inherits A) must be a no-op, not an infinite loop."""
    from prism.schema import effective_fields
    defs = {
        "a": type_definition("a", {"x": "string"}, inherits=("b",)),
        "b": type_definition("b", {"y": "string"}, inherits=("a",)),
    }
    eff = effective_fields("a", defs.get)                   # must terminate
    assert set(eff) == {"x", "y"}


def test_diamond_inheritance_resolves_once() -> None:
    """A inherits B and C, both inherit base. Base's fields appear once; no double-walk hang."""
    from prism.schema import effective_fields
    defs = {
        "base": type_definition("base", {"id": "string"}),
        "b": type_definition("b", {"b": "string"}, inherits=("base",)),
        "c": type_definition("c", {"c": "string"}, inherits=("base",)),
        "a": type_definition("a", {"a": "string"}, inherits=("b", "c")),
    }
    eff = effective_fields("a", defs.get)
    assert set(eff) == {"id", "a", "b", "c"}


def test_unknown_type_resolves_to_empty_not_error() -> None:
    """Asking for a type the registry doesn't have yields {}, not an exception — loose, honest."""
    from prism.schema import effective_fields
    assert effective_fields("never-registered", lambda ct: None) == {}
