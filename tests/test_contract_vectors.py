"""prism-py against the shared cross-SDK contract vectors.

`prism/vectors/contract_vectors.json` — shipped inside this package — is the one artifact every prism
SDK is checked against.
Its companion is `agience-prism/js/test/contractVectors.test.ts`, which asserts the same expectations
from TypeScript, so byte-parity between the SDKs is enforced by a test rather than by a README.

The vocabulary drift gate compares names, so it says nothing about bytes: one SDK escaping non-ASCII
while another emits it raw passes that gate. These vectors compare the bytes themselves.
"""
import hashlib

import pytest

from prism.crystal_model import canonical_json, crystal_sha
from prism.vectors import load_vectors

# The vectors ship as package data inside prism itself, so this resolves through
# `importlib.resources` — the same mechanism a `pip install`ed consumer uses, with no source tree,
# no sibling repo and no directory depth to get wrong.
#
# A parent-directory walk into a sibling checkout has neither property. A wrong `parents[N]` lands
# in a directory that simply does not contain the file, and a consumer that skips on absence then
# reads green while checking nothing.
#
# `load_vectors` raises on absence, so every path through this module that reports success has the
# data behind it.
DATA = load_vectors("contract_vectors")


def test_the_vector_file_is_actually_populated():
    """Guards the vacuous pass: an empty vector list would make every parametrised test below
    disappear silently and the gate would report success while checking nothing."""
    assert len(DATA["canonical_json"]) >= 8
    assert len(DATA["crystal_sha"]) >= 2
    names = [c["name"] for c in DATA["canonical_json"]]
    # the cases that actually diverged must be present
    for required in ("non_ascii_latin", "astral_emoji", "control_and_quote"):
        assert required in names, "vector %r removed — that is the case that broke" % required


@pytest.mark.parametrize("case", DATA["canonical_json"], ids=lambda c: c["name"])
def test_canonical_json_matches_the_shared_vector(case):
    got = canonical_json(case["value"])
    assert got.decode("utf-8") == case["canonical"]
    assert hashlib.sha256(got).hexdigest() == case["sha256"]


@pytest.mark.parametrize("case", DATA["crystal_sha"], ids=lambda c: c["name"])
def test_crystal_sha_matches_the_shared_vector(case):
    assert crystal_sha(case["crystal"]) == case["sha256"]


def test_non_ascii_vectors_are_raw_utf8_not_escaped():
    """The invariant the vectors exist to protect: canonical JSON carries non-ASCII as raw UTF-8."""
    for case in DATA["canonical_json"]:
        if case["name"].startswith("non_ascii") or case["name"] == "astral_emoji":
            assert "\\u" not in case["canonical"], (
                "vector %r is pinned in the ESCAPED form — that is the bug, not the fix"
                % case["name"])


# ── structural (deterministic CBOR) — the permanent content address ───────────────────────────────

def _realize(v):
    """`{"$bigint": "..."}` -> a native int. JSON cannot carry an integer beyond 2^53, so the vector
    file encodes it as a string and each SDK reconstitutes it natively — which is itself part of the
    point: the JSON text path cannot even express the value structural encoding addresses exactly."""
    if isinstance(v, dict) and set(v) == {"$bigint"}:
        return int(v["$bigint"])
    if isinstance(v, dict):
        return {k: _realize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_realize(x) for x in v]
    return v


def test_structural_vectors_are_populated():
    assert len(DATA["structural"]) >= 8
    names = [c["name"] for c in DATA["structural"]]
    for required in ("s_bigint", "s_astral_key", "s_numbers"):
        assert required in names, "structural vector %r removed" % required
    assert DATA["structural_algo"] == "cbor-det-sha256"


@pytest.mark.parametrize("case", DATA["structural"], ids=lambda c: c["name"])
def test_structural_encoding_matches_the_shared_vector(case):
    from prism.structural import structural_encode, structural_sha
    value = _realize(case["value"])
    assert structural_encode(value).hex() == case["cbor_hex"]
    assert structural_sha(value) == case["sha256"]


def test_the_bigint_vector_is_the_one_jcs_cannot_represent():
    """Guards the vector's purpose, not just its value: if this case were 'simplified' to a small
    integer, the file would stay green while checking nothing."""
    from prism.canonical import canonical_json
    case = next(c for c in DATA["structural"] if c["name"] == "s_bigint")
    big = _realize(case["value"])["a"]
    assert big > 2 ** 53
    # JCS rounds it, and therefore cannot tell it from its neighbour — a silent address collision.
    assert canonical_json({"a": big}) == canonical_json({"a": big - 1})


# ── the junction (Contract Builder — NEXT.md §5.3) ────────────────────────────────────────────────
#
# These four functions are the code that decides whether a host grounds a crystal at all. A drift gate
# over names says nothing about them, and validation split across two SDKs diverges quietly, each one
# holding half the check. Details in the vector file's `_junction_comment`. These vectors pin the
# agreement between the SDKs.

def test_the_junction_sections_are_populated():
    """Vacuous-pass guard: an absent section would silently skip every case below."""
    for key, least in (("capability_reach", 8), ("activates_on", 8),
                       ("required_capabilities", 3), ("validate", 4)):
        assert len(DATA.get(key, [])) >= least, "junction vectors missing/short: %s" % key


@pytest.mark.parametrize("case", DATA.get("capability_reach", []),
                         ids=[c["name"] for c in DATA.get("capability_reach", [])])
def test_capability_reach_matches_the_shared_vector(case):
    from prism.crystal_model import capability_reach
    assert capability_reach(case["required"], case["advertised"]) == case["matches"]


@pytest.mark.parametrize("case", DATA.get("activates_on", []),
                         ids=[c["name"] for c in DATA.get("activates_on", [])])
def test_activates_on_matches_the_shared_vector(case):
    from prism.crystal_model import activates_on
    assert activates_on(case["crystal"], case["advertised"]) is case["activates"]


@pytest.mark.parametrize("case", DATA.get("required_capabilities", []),
                         ids=[c["name"] for c in DATA.get("required_capabilities", [])])
def test_required_capabilities_matches_the_shared_vector(case):
    from prism.crystal_model import required_capabilities
    assert required_capabilities(case["crystal"]) == case["required"]


@pytest.mark.parametrize("case", DATA.get("validate", []),
                         ids=[c["name"] for c in DATA.get("validate", [])])
def test_validate_matches_the_shared_vector(case):
    """Problem messages are pinned verbatim, not just counted.

    A count alone would let the two SDKs disagree about which problem they found while agreeing on
    how many. The messages are byte-identical across prism-py and prism-js by design.
    """
    from prism.crystal_model import validate
    assert validate(case["crystal"]) == case["problems"]


def test_the_capability_spelling_check_exists_here_at_all():
    """Pinned separately from the vectors because this is a property, not an example: an unknown
    capability kind is rejected before it can be signed into an artifact, and an open-family member
    is still accepted — the check that catches a typo must not reject every real sensor with it.
    """
    from prism.crystal_model import validate
    base = {"name": "c", "created_by": "j", "facets": [{"name": "f", "direction": "out"}],
            "tektons": [{"name": "t"}]}
    bogus = dict(base, organons=[{"name": "op.a", "requires": ["totally.bogus"]}])
    assert any("unknown capability kind" in p for p in validate(bogus)), validate(bogus)
    ok = dict(base, organons=[{"name": "op.a", "requires": ["sensor.temperature", "net.get"]}])
    assert validate(ok) == [], "an open-family member must NOT be refused as a typo: %r" % validate(ok)
