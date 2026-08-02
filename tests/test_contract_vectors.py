"""prism-py against the SHARED cross-SDK contract vectors.

`agience-beam/vectors/contract_vectors.json` is the one artifact every prism SDK is checked against.
Its companion is `agience-prism/js/test/contractVectors.test.ts`, which asserts the SAME expectations
from TypeScript — so byte-parity between the SDKs is ENFORCED rather than asserted in a README.

🔴 MOVED 2026-07-29 (Contract Builder, John's call) from `agience-prism/vectors/`, which was **in no git
repository at all**: `agience-prism/` is not a repo — only `c`, `js` and `py` are, each with its own
remote — and `vectors/` sat beside them, tracked by none. The single source of truth for every content
address in this workspace had no history (a re-baseline was undiffable), was on no remote (`push-all`
could not carry it; it died with the box), and, because both SDKs read the SAME file, an edit moved
Python and JS together — so the two-sided assertion that exists to catch drift could not catch drift
introduced through the vectors themselves.
It lives in **beam** because beam already holds one of the two sanctioned byte-identical copies of
`canonical.py` and is gated against these very vectors, so it was already a participant; and because
beam imports nothing from the workspace, no repo has to invert a dependency to read a data file from
it. Not mantle: mantle is FORBIDDEN from any prism coupling by its own `test_embeddable_surface.py`
and does not consume the vectors, so the contract would have been parked in the one repo required to
stay ignorant of it. This suite already read a path outside its own repo, so nothing about prism/py's
standalone status changed.

This is what §P.2 said was missing: the vocabulary drift gate compares NAMES, and would not have caught
the 2026-07-29 bug where Python escaped non-ASCII and prism-c did not. These vectors would have.
"""
import hashlib
import json
import pathlib

import pytest

from prism.crystal_model import canonical_json, crystal_sha

#: `parents[3]` is the genesis root: this file is at
#: `<root>/agience-prism/py/tests/test_contract_vectors.py`. The depth is ASSERTED below rather than
#: trusted — a wrong `parents[N]` resolves to a directory that simply does not contain the file, and
#: this workspace has already been bitten by that exact idiom passing VACUOUSLY (`test_one_aperture.py`
#: used `parents[3]` where it needed `parents[2]`, landing above the workspace, and read green).
_ROOT = pathlib.Path(__file__).resolve().parents[3]
VECTORS = _ROOT / "agience-beam" / "tests" / "vectors" / "contract_vectors.json"


def _load():
    assert (_ROOT / "agience-prism" / "py").is_dir(), (
        "path depth is wrong: parents[3] should be the genesis root but %s does not contain "
        "agience-prism/py — fix the depth, do not adjust the vectors path" % _ROOT)
    assert VECTORS.is_file(), (
        "shared contract vectors missing at %s — without them this suite passes vacuously and the "
        "SDKs can drift apart unnoticed" % VECTORS)
    return json.loads(VECTORS.read_text(encoding="utf-8"))


DATA = _load()


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
    """The invariant the vectors exist to protect — stated once, plainly."""
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
    """Guards the vector's PURPOSE, not just its value: if someone 'simplifies' this case to a small
    integer, the file would stay green while no longer proving anything."""
    from prism.canonical import canonical_json
    case = next(c for c in DATA["structural"] if c["name"] == "s_bigint")
    big = _realize(case["value"])["a"]
    assert big > 2 ** 53
    # JCS rounds it, and therefore cannot tell it from its neighbour — a silent address collision.
    assert canonical_json({"a": big}) == canonical_json({"a": big - 1})


# ── THE JUNCTION (added 2026-07-29, Contract Builder — NEXT.md §5.3) ──────────────────────────────
#
# §5.3: "The drift gate covers NAMES only — it would not have caught a single item in §5.1." It did not.
# Cross-checking these four functions against prism-js found TWO live divergences in the code that decides
# whether a host grounds a crystal at all — each SDK held half the validation. Details in the vector
# file's `_junction_comment`. These pin the agreement so it cannot drift back.

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
    """Problem MESSAGES are pinned verbatim, not just counted.

    Counting was how the first cross-check reported this — and a count would have let the two SDKs
    disagree about WHICH problem they found while agreeing on how many. The messages are byte-identical
    across prism-py and prism-js by design.
    """
    from prism.crystal_model import validate
    assert validate(case["crystal"]) == case["problems"]


def test_the_capability_spelling_check_exists_here_at_all():
    """prism-py — the SIGNER — had no spelling check while prism-js did.

    Pinned separately from the vectors because this is the property, not an example: an unknown kind must
    be REFUSED before it can be signed into an artifact, and open-family members must still be accepted
    or every real sensor is refused with it.
    """
    from prism.crystal_model import validate
    base = {"name": "c", "created_by": "j", "facets": [{"name": "f", "direction": "out"}],
            "tektons": [{"name": "t"}]}
    bogus = dict(base, organons=[{"name": "op.a", "requires": ["totally.bogus"]}])
    assert any("unknown capability kind" in p for p in validate(bogus)), validate(bogus)
    ok = dict(base, organons=[{"name": "op.a", "requires": ["sensor.temperature", "net.get"]}])
    assert validate(ok) == [], "an open-family member must NOT be refused as a typo: %r" % validate(ok)
