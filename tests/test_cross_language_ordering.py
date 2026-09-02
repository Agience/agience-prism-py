"""Cross-language ordering and encoding — `prism.vectors/ordering_vectors.json` asserted against the wire.

Two functions state an explicit encoding rather than leaning on Python's defaults, because a second
implementation in another language needs something to be correct against:

  * `prism.minhash._band_bytes` — the LSH band key, built from the values as fixed-width big-endian
    bytes rather than from the container, so a band bucketed from a list, a tuple, or a numpy array
    lands in the same bucket.
  * `prism.carriers._leaf_order` — the order every carrier's `poll()` returns, `(hlc, id)` compared
    as UTF-8 encoded bytes rather than by Python `str`, so the order agrees with a JavaScript or C
    carrier too.
"""

import hashlib

import pytest

from prism.carriers import _leaf_order
from prism.minhash import _band_bytes
# Read from the installed prism package rather than a local `vectors/` directory. `load_vectors`
# raises when the set is absent, so this module fails to import rather than collecting zero cases
# and reporting success.
from prism.vectors import load_vectors

VECTORS = "ordering_vectors"
DOC = load_vectors(VECTORS)


# ── the band key ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("case", DOC["band_bytes"]["vectors"], ids=lambda c: c["name"])
def test_band_bytes_reproduces_the_pinned_encoding(case):
    """The bytes and the digest, so an implementation that gets the encoding right but hashes it
    differently is caught too."""
    raw = _band_bytes(case["values"])
    assert raw.hex() == case["bytes_hex"], "%s: encoding moved" % case["name"]
    assert hashlib.blake2b(raw, digest_size=8).digest().hex() == case["blake2b8_hex"], (
        "%s: the band key digest moved — every bucket assignment changes with it" % case["name"])


def test_the_band_key_is_the_same_for_every_container_that_holds_the_values():
    """The band key is the same regardless of which container carries the values.

    `group_signatures` is typed `Sequence[Sequence[int]]`, so a band arrives as a list from one
    caller, a tuple from another, and a numpy array from a third. Keying on `repr(chunk)` would
    render those as `[1, 2, 3, 4]`, `(1, 2, 3, 4)` and `array([1, 2, 3, 4], dtype=uint64)` — three
    strings, three buckets, and near-duplicates that would never meet as candidates because of how
    they were passed. `_band_bytes` keys on the values themselves instead, so all three land in the
    same bucket.
    """
    import numpy as np

    values = [1, 2, 3, 4]
    keys = {
        "list": _band_bytes(values),
        "tuple": _band_bytes(tuple(values)),
        "numpy_uint64": _band_bytes(np.array(values, dtype=np.uint64)),
        "numpy_int64": _band_bytes(np.array(values, dtype=np.int64)),
        "generator": _band_bytes(iter(values)),
    }
    assert len(set(keys.values())) == 1, (
        "the same values gave different band keys by container: %s"
        % {k: v.hex() for k, v in keys.items()})


def test_band_bytes_is_fixed_width_so_it_needs_no_separator():
    """Why the encoding is unambiguous without a delimiter. If widths varied, `[1, 23]` and
    `[12, 3]` could collide; at 8 bytes each they cannot."""
    assert len(_band_bytes([1, 2, 3])) == 24
    assert _band_bytes([1, 23]) != _band_bytes([12, 3])
    assert _band_bytes([]) == b"", "an empty band is empty bytes"
    assert _band_bytes([0]) != _band_bytes([]), (
        "a zero value and an absent value must not share an encoding")


def test_a_value_too_large_for_the_field_is_refused():
    """Signature values are `mod 2**61-1`, so 8 bytes always suffice. A value that does not fit
    raises rather than truncating — a silently wrapped band key is a wrong bucket that looks right.
    """
    with pytest.raises(OverflowError):
        _band_bytes([1 << 64])


# ── the leaf order ──────────────────────────────────────────────────────────────
def test_leaf_order_reproduces_the_pinned_sequence():
    section = DOC["leaf_order"]
    got = [leaf["id"] for leaf in sorted(section["leaves"], key=_leaf_order)]
    assert got == section["expected_id_order"], (
        "carrier poll order moved. Two nodes agree on what arrived and in what sequence by this "
        "order, so every implementation moves with it or not at all.")


def test_the_order_is_by_utf8_bytes_and_astral_characters_are_where_it_shows():
    """The case that separates the three candidate orderings.

    `U+FFFD` and `U+10000`: Python's `str` comparison is by code point and puts `FFFD` first;
    JavaScript's default sort is by UTF-16 code unit, and `U+10000` is the surrogate pair
    `D800 DC00`, so `D800 < FFFD` puts `10000` first. UTF-8 byte order agrees with code point order,
    which is why encoding first makes the two languages agree.
    """
    hlc = "2026-01-01T00:00:00Z"
    leaves = [{"hlc": hlc, "id": i} for i in ("\U00010000", "�", "z")]
    assert [leaf["id"] for leaf in sorted(leaves, key=_leaf_order)] == ["z", "�", "\U00010000"]

    utf16_order = sorted(("\U00010000", "�", "z"), key=lambda s: s.encode("utf-16-be"))
    assert utf16_order != ["z", "�", "\U00010000"], (
        "UTF-16 and UTF-8 orderings agree on this input, so it does not demonstrate the divergence "
        "and this test proves less than it claims")


def test_hlc_outranks_id():
    """`(hlc, id)` — time first, id only to break ties. An id-first order would interleave leaves
    from different moments."""
    leaves = [{"hlc": "2026-01-02T00:00:00Z", "id": "a"},
              {"hlc": "2026-01-01T00:00:00Z", "id": "z"}]
    assert [leaf["id"] for leaf in sorted(leaves, key=_leaf_order)] == ["z", "a"]


def test_a_leaf_missing_hlc_or_id_still_orders():
    """`poll()` skips nothing for being incomplete, so the key handles absence rather than raising —
    a malformed leaf that sorts is visible, and one that raises takes the whole poll down."""
    leaves = [{"id": "b"}, {"hlc": "2026-01-01T00:00:00Z", "id": "a"}, {}]
    ordered = sorted(leaves, key=_leaf_order)
    assert ordered[0] == {} and ordered[1] == {"id": "b"}, (
        "an empty hlc sorts first, and among those the id decides")
