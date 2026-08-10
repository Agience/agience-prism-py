"""The frame wire format — `prism.vectors/frame_wire_vectors.json` asserted against the wire.

A frame is the payload of a reach, so every language that carries one implements this encoding. The
vectors are the contract: a second implementation is checked against bytes rather than against a
description it has to interpret. Same idiom as `contract_vectors.json` (prism py/js/c parity) and
`screen_read_vectors.json` (full aperture/beacon read parity).

The format, in full: `BFR1` + `rows:u32` + `cols:u32` + `rows*cols` float64, all big-endian, C order,
then base64.
"""

import base64

import numpy as np
import pytest

from prism.frames import FRAME_MAGIC, decode_frame, encode_frame
# Read from the installed prism package rather than a local `vectors/` directory. `load_vectors`
# raises when the set is absent.
from prism.vectors import load_vectors, vector_path

VECTORS = "frame_wire_vectors"


def _cases():
    return load_vectors(VECTORS)["vectors"]


def test_the_vector_file_is_present_and_populated():
    """The gate's precondition — a parametrised test over zero cases passes."""
    assert vector_path(VECTORS).is_file(), "%s is missing" % VECTORS
    assert len(_cases()) >= 6


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_encoding_reproduces_the_pinned_bytes(case):
    """`prism.frames` emits exactly the pinned string. This is the assertion a second implementation copies."""
    got = encode_frame(np.array(case["values"], dtype=np.float64))
    assert got == case["encoded"], (
        "%s: the wire bytes moved. Any implementation pinned to the old string now disagrees, so "
        "this file and every implementation move together or not at all." % case["name"]
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_decoding_the_pinned_bytes_recovers_the_values(case):
    """The other direction. Encode-only agreement would leave a reader free to be wrong."""
    got = decode_frame(case["encoded"])
    assert got is not None, "%s decoded to None" % case["name"]
    assert list(got.shape) == case["shape"], (
        "%s: shape %r, pinned %r" % (case["name"], list(got.shape), case["shape"]))
    assert np.array_equal(got, np.array(case["values"], dtype=np.float64)), (
        "%s: values differ after a round trip through the pinned bytes" % case["name"])


def test_the_header_is_readable_without_a_numpy_parser():
    """The whole point of the format, asserted directly rather than implied.

    This test reads a frame using only base64, integer arithmetic and `struct` — the operations a
    JavaScript `DataView` or thirty lines of C have. It passing means the format is implementable
    from the spec comment alone. The `.npy` encoding it replaced could not pass this: its shape was
    a Python dict literal in ASCII.
    """
    import struct

    frame = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    raw = base64.b64decode(encode_frame(frame))

    assert raw[:4] == b"BFR1", "the magic identifies the format and its version"
    rows = struct.unpack(">I", raw[4:8])[0]
    cols = struct.unpack(">I", raw[8:12])[0]
    assert (rows, cols) == (2, 3)
    assert len(raw) == 12 + rows * cols * 8, "header is exactly 12 bytes; the rest is payload"

    values = [struct.unpack(">d", raw[12 + i * 8:20 + i * 8])[0] for i in range(rows * cols)]
    assert values == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "C order: row 0 complete, then row 1"


def test_shape_survives_when_the_values_cannot_distinguish_it():
    """`(1,5)` and `(5,1)` hold the same numbers in the same order and mean different things — axis 0
    is ordered, axis 1 is feature. The payload bytes are identical, so only the header separates
    them, and a reader that ignored it would silently transpose meaning."""
    wide, tall = np.arange(5.0).reshape(1, 5), np.arange(5.0).reshape(5, 1)
    assert encode_frame(wide) != encode_frame(tall)
    assert base64.b64decode(encode_frame(wide))[12:] == base64.b64decode(encode_frame(tall))[12:], (
        "the payloads should be byte-identical — if they are not, this test is proving something "
        "weaker than it claims")
    assert decode_frame(encode_frame(wide)).shape == (1, 5)
    assert decode_frame(encode_frame(tall)).shape == (5, 1)


def test_a_flat_array_is_refused():
    """A frame is (T, F). A 1-D array is ambiguous between one step of N features and N steps of
    one, and guessing would make the wire format lossy at its first byte."""
    with pytest.raises(ValueError, match="frame is"):
        encode_frame([1.0, 2.0, 3.0])


def test_legacy_npy_frames_still_decode():
    """Frames written with the legacy `.npy` encoding are in stored payloads and in flight. A reader
    that rejected them would turn old evidence into no evidence, so `decode_frame` reads both
    encodings."""
    import io

    a = np.array([[1.0, 2.0], [3.0, 4.0]])
    buf = io.BytesIO()
    np.save(buf, a, allow_pickle=False)
    legacy = base64.b64encode(buf.getvalue()).decode("ascii")

    assert legacy != encode_frame(a), "the two encodings must be distinguishable to be worth testing"
    assert np.array_equal(decode_frame(legacy), a), "a legacy frame stopped being readable"


def test_absent_and_malformed_are_None_not_a_fabricated_frame():
    """An unreadable frame is an honest absence. Returning a zero array here would manufacture a
    measurement nobody took, which downstream cannot tell from a real one."""
    for bad in (None, "", "not-base64!!", base64.b64encode(b"BFR1garbage").decode()):
        assert decode_frame(bad) is None, "%r produced a frame" % (bad,)

    truncated = base64.b64encode(
        FRAME_MAGIC + (2).to_bytes(4, "big") + (2).to_bytes(4, "big") + b"\x00" * 8
    ).decode()
    assert decode_frame(truncated) is None, (
        "a frame claiming 2x2 but carrying 8 bytes was accepted — a short payload must be absent, "
        "never silently reshaped into a smaller frame")


def test_round_trip_is_exact_over_awkward_values():
    """Float64 in, the same bits out. Values chosen so a decimal-rendering round trip would fail."""
    a = np.array([[0.1, 1e-300, -0.0], [1e300, np.pi, 2.0 ** -1074]])
    out = decode_frame(encode_frame(a))
    assert np.array_equal(out, a), "exact float64 round trip failed"
    assert np.signbit(out[0, 2]) == np.signbit(a[0, 2]), "negative zero lost its sign"
