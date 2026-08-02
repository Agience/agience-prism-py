"""The structural content address, and the properties that justify it over JSON-text canonicalization.

These are not "it runs" tests. Each one names a divergence class that JSON-text canonicalization has
and structural encoding does not — measured side by side against the JCS implementation we actually
shipped, so the comparison is real rather than rhetorical.
"""
import hashlib

import pytest

from prism.canonical import canonical_json
from prism.structural import (
    STRUCTURAL_ALGO,
    Unaddressable,
    structural_encode,
    structural_sha,
)


# ── the loss JCS forces, and structural does not ──────────────────────────────

def test_a_big_integer_survives_structurally_but_is_ROUNDED_by_jcs():
    """THE headline property. JCS numbers are IEEE-754 doubles, so Python had to round
    9007199254740993 to …992 to agree with JavaScript. A CBOR integer is not a float."""
    big = 9007199254740993                               # 2^53 + 1
    assert b"9007199254740992" in canonical_json({"a": big})     # JCS: silently rounded
    assert b"9007199254740993" not in canonical_json({"a": big})

    # structural: the integer is encoded exactly, so the two differ
    assert structural_sha({"a": big}) != structural_sha({"a": big - 1})


def test_jcs_cannot_tell_those_two_integers_apart_at_all():
    """The same fact from the other side: under JCS these collide. Two DIFFERENT artifacts share one
    content address — a silent collision, which is the worst failure a content address can have."""
    assert canonical_json({"a": 9007199254740993}) == canonical_json({"a": 9007199254740992})


# ── the three questions that simply do not exist ──────────────────────────────

def test_no_escaping_question_strings_are_length_prefixed_utf8():
    """A text string is a byte run with a length. There is no 'should é be escaped' decision to get
    wrong, so the 2026-07-29 bug class cannot recur here."""
    enc = structural_encode({"k": "café"})
    assert "café".encode("utf-8") in enc                 # raw bytes, verbatim
    assert b"\\u00e9" not in enc                          # no escape form exists


def test_no_collation_question_keys_sort_by_encoded_bytes():
    """Code point vs UTF-16 code unit was a real divergence in the text path. Byte order is one total
    order and is identical in every language."""
    a = structural_encode({"\U0001F600": 1, "�": 2, "z": 3})
    b = structural_encode({"z": 3, "�": 2, "\U0001F600": 1})
    assert a == b                                        # insertion order is irrelevant


def test_no_number_rendering_question_integers_and_floats_are_distinct_types():
    """1.5 is a float64; 2 is an integer. Neither is rendered to text, so there is no
    fixed-vs-exponential or trailing-.0 decision."""
    assert structural_encode({"a": 1.5}) != structural_encode({"a": 2})
    assert structural_encode({"a": 1.5})[-8:] == __import__("struct").pack(">d", 1.5)


# ── the ONE normalization that remains ────────────────────────────────────────

def test_integral_float_and_integer_address_identically():
    """The single unavoidable rule: JavaScript cannot distinguish 1 from 1.0, so an integral value is
    an integer on both sides. One rule, stated once — not a per-character behaviour."""
    assert structural_sha({"a": 1}) == structural_sha({"a": 1.0})
    assert structural_sha({"a": -0.0}) == structural_sha({"a": 0})


def test_non_finite_numbers_are_refused_not_encoded():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="no content address"):
            structural_encode({"a": bad})


# ── determinism + the algorithm tag ───────────────────────────────────────────

def test_encoding_is_stable_and_the_sha_is_over_those_bytes():
    doc = {"name": "crystal.fetcher", "n": 7, "l": [1, "x", None, True]}
    assert structural_encode(doc) == structural_encode(dict(reversed(list(doc.items()))))
    assert structural_sha(doc) == hashlib.sha256(structural_encode(doc)).hexdigest()


def test_the_algorithm_is_named_so_addresses_can_coexist():
    """A bare digest cannot say which algorithm produced it. During migration a structural address and
    a JCS address for the same artifact MUST be distinguishable, or they silently collide."""
    assert STRUCTURAL_ALGO == "cbor-det-sha256"
    assert structural_sha({"a": 1}) != hashlib.sha256(canonical_json({"a": 1})).hexdigest()


def test_shortest_form_heads_are_used():
    """RFC 8949 §4.2.1 requires shortest-form encoding — otherwise two encoders both 'valid' produce
    different bytes, which is the whole problem again."""
    assert structural_encode(23) == b"\x17"              # inline
    assert structural_encode(24) == b"\x18\x18"          # 1-byte follow
    assert structural_encode(256) == b"\x19\x01\x00"     # 2-byte follow


# ── what this encoder REFUSES (added 2026-07-29, Contract Builder) ─────────────
#
# Every test below pins a case that previously produced BYTES. The reason structural encoding exists is
# that JCS silently gives two different artifacts one content address; an encoder that mis-addresses its
# own edge cases reproduces that defect one layer down. So these are the load-bearing tests in the file.

def test_a_set_is_REFUSED_because_its_address_would_depend_on_PYTHONHASHSEED():
    """THE WORST OF THE OLD FALLBACKS. `_emit` ended in `str(obj)`, so a set addressed as `str(set)` —
    whose element order follows hash values, which vary per process. The same set therefore had a
    different content address in different runs: an address that is not a function of the content.
    Nothing raised, nothing logged, and the digest looked perfectly valid."""
    with pytest.raises(Unaddressable, match="set has no structural encoding"):
        structural_encode({1, 2, 3})
    with pytest.raises(Unaddressable):
        structural_encode({"a": frozenset([1])})          # also refused when nested


def test_arbitrary_objects_are_REFUSED_rather_than_addressed_by_their_repr():
    """`datetime`/`Decimal`/custom objects were addressed via `str()` — a representation decision the
    caller never made, and one that changes with a library upgrade."""
    import datetime as _dt
    import decimal as _dec

    for value in (_dt.datetime(2026, 7, 29), _dec.Decimal("1.5"), object()):
        with pytest.raises(Unaddressable, match="no structural encoding"):
            structural_encode(value)


def test_a_non_string_dict_key_is_REFUSED_because_coercion_COLLIDED_two_keys():
    """Measured before the fix: key `1.0` was coerced with `str(k)` to `"1.0"`, so a dict holding BOTH
    emitted a duplicate-key CBOR map — invalid for deterministic encoding (RFC 8949 §5.6) — and which
    value survived depended on insertion order, so two dicts equal as data had different addresses."""
    with pytest.raises(Unaddressable, match="dict keys must be str"):
        structural_encode({1.0: "x", "1.0": "y"})
    for bad_key in (1, 1.0, b"k", None, True, (1, 2)):
        with pytest.raises(Unaddressable, match="dict keys must be str"):
            structural_encode({bad_key: "v"})


def test_the_insertion_order_collision_is_gone():
    """The exact pair that used to produce two different addresses now refuses identically both ways —
    the negative control for the key fix, stated as the failure it prevents rather than as a rule."""
    for d in ({1.0: "x", "1.0": "y"}, {"1.0": "y", 1.0: "x"}):
        with pytest.raises(Unaddressable):
            structural_encode(d)


# ── big integers: exact and unbounded, which the docstring used to only CLAIM ──

def test_the_64_bit_bignum_handover_is_exact_on_both_sides_of_the_boundary():
    """Major type 0/1 while the value FITS in 64 bits, bignum only beyond. The split is mandatory: if a
    small value could also be a bignum, one integer would have two valid encodings and two addresses.

    Before this, |int| >= 2^64 raised an opaque `struct.error` in Python while the JS counterpart
    SILENTLY TRUNCATED to the low 64 bits — so 2**64 and 0 shared a head there. One integer, two SDKs,
    two addresses, nothing raised on either side."""
    assert structural_encode(2 ** 64 - 1) == bytes.fromhex("1bffffffffffffffff")   # major 0
    assert structural_encode(2 ** 64) == bytes.fromhex("c249010000000000000000")   # tag 2 bignum
    assert structural_encode(-(2 ** 64)) == bytes.fromhex("3bffffffffffffffff")    # major 1
    assert structural_encode(-(2 ** 64) - 1) == bytes.fromhex("c349010000000000000000")  # tag 3


def test_a_bignum_magnitude_carries_no_leading_zero_byte():
    """A leading zero would be a second encoding of the same number — determinism gone."""
    enc = structural_encode(2 ** 64)
    assert enc[:2] == b"\xc2\x49", enc.hex()          # tag 2, byte string of length 9
    assert enc[2] != 0, "leading zero byte in the magnitude: %s" % enc.hex()
    assert structural_encode(2 ** 128 + 7).hex() == "c2510100000000000000000000000000000007"


def test_huge_integers_no_longer_raise_and_stay_DISTINGUISHABLE():
    """The point of leaving JCS: `9007199254740993` must not collide with `…992`. That has to keep
    holding arbitrarily far out, not just past 2^53."""
    assert structural_sha(2 ** 64) != structural_sha(2 ** 64 + 1)
    assert structural_sha(2 ** 200) != structural_sha(2 ** 200 + 1)
    assert structural_sha(9007199254740993) != structural_sha(9007199254740992)


def test_refusing_did_not_break_the_supported_domain():
    """The vacuous-pass guard for this whole section: if the refusals were over-broad, every test above
    would still pass while the encoder had become useless. Ordinary JSON-shaped documents must be
    unaffected, and the previously pinned bytes must be unchanged."""
    assert structural_encode({"b": 1, "a": 2}).hex() == "a2616102616201"
    assert structural_sha(1) == structural_sha(1.0)
    doc = {"id": "x~1", "n": 3, "f": 1.5, "s": "héllo", "l": [1, "a", None, True], "d": {"k": {}},
           "raw": b"\x00\x01"}
    assert len(structural_encode(doc)) > 0
