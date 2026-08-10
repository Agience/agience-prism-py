"""Signal frames on the wire — carry an ordered `(T, F)` frame as a reach payload, and absorb it at a tekton.

The signal-native reach's payload is a signal — an ordered `(T, F)` frame, the measured thing — rather than a
stringified answer (`SIGNAL-PROTOCOL.md §2`). This is the thin wire layer between that principle and the
reach transport, which seals a JSON payload:

  · `encode_frame` / `decode_frame` — a `(T, F)` float frame ↔ a compact JSON-safe string, so a reach need or
    evidence carries the frame itself inside its sealed payload, exactly and deterministically, without
    becoming a bulky nested list.
  · `absorb_at_tekton` — the provider side of the 0a mechanism: split the incident frame at this tekton's
    membrane (the embodiment's `absorb_transmit`) into the band it absorbs — its work, condensed to a typed
    artifact and signed there — and the residual to propagate to the next tekton.

The frame is the payload; provenance is signed at the tekton boundary, on the condensed artifact, rather than
on a mid-stream frame. That is the waveform-provenance boundary.

The aperture is injected, not imported. `absorb_at_tekton` is the one call site in this module that takes a
measurement, and it reaches it through an injected instrument (`prism.instrument`): the wire holds no import
of the aperture, and the aperture is no dependency of a package whose base install is empty.
`encode_frame`, `decode_frame` and `FRAME_KEY` need numpy and nothing else, which is what lets a node carry
frames it cannot measure.
"""
from __future__ import annotations

import base64
import io
from typing import Any, Optional, Tuple

import numpy as np

from . import instrument as _instrument

FRAME_KEY = "frame"      # the reach-payload field that carries an encoded (T, F) frame


# ── The frame wire format ────────────────────────────────────────────────────────────────────────
# `BFR1` + rows:u32 + cols:u32 + rows*cols float64, all big-endian, C order, then base64.
# Twelve bytes of header, fully specified in one line, implementable from this comment alone.
#
# The header is bytes rather than a NumPy `.npy` buffer so that any language can read it. `.npy`
# spells its shape as a Python dict literal in ASCII — `{'descr': '<f8', 'fortran_order': False,
# 'shape': (2, 2), }` — which asks a JavaScript or C carrier to parse Python syntax, and costs a 2x2
# frame 128 bytes of header for 32 bytes of data. Big-endian because it is what `DataView` reads by
# default and what `ntohl` gives C for free; float64 because the frame is float64 everywhere it is
# measured.
#
# `prism.vectors/frame_wire_vectors.json` pins the bytes, so a second-language implementation has
# something to be correct against rather than a description to interpret.
FRAME_MAGIC = b"BFR1"


def encode_frame(arr) -> str:
    """A `(T, F)` float frame → a compact JSON-safe string. Deterministic and exact (`decode_frame`
    round-trips to the same array), so a frame rides inside a sealed reach payload rather than as a
    bulky nested list."""
    a = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
    if a.ndim != 2:
        raise ValueError("a frame is (T, F); got shape %r. The two axes carry different meanings — "
                         "axis 0 is ORDERED and axis 1 is FEATURE — so a flat array is ambiguous "
                         "rather than merely under-specified." % (a.shape,))
    head = FRAME_MAGIC + a.shape[0].to_bytes(4, "big") + a.shape[1].to_bytes(4, "big")
    return base64.b64encode(head + a.astype(">f8").tobytes()).decode("ascii")


def decode_frame(s: Optional[str]):
    """Inverse of `encode_frame` — the exact `(T, F)` float array, or None on an absent or malformed
    string. `None` is an honest 'no frame' rather than a fabricated one.

    The `.npy` encoding is read as well. Frames written that way are still in flight and in stored
    payloads, and a reader that turned them away would turn old evidence into no evidence."""
    if not s:
        return None
    try:
        raw = base64.b64decode(s)
    except Exception:
        return None

    if raw[:4] == FRAME_MAGIC:
        rows = int.from_bytes(raw[4:8], "big")
        cols = int.from_bytes(raw[8:12], "big")
        body = raw[12:]
        if len(body) != rows * cols * 8:
            return None          # a truncated frame is absent, never a short one silently reshaped
        return np.frombuffer(body, dtype=">f8").astype(np.float64).reshape(rows, cols)

    try:
        return np.load(io.BytesIO(raw), allow_pickle=False)
    except Exception:
        return None


def absorb_at_tekton(frame, basis=None, *, embodiment=None, **kw) -> Optional[Tuple[Any, Any, int]]:
    """The tekton (provider) side of 0a: split the incident frame at this tekton's membrane (the
    embodiment's `absorb_transmit`). Returns `(absorbed, transmitted, k)` — the coupled band this tekton
    absorbs (its work: condense to a typed artifact and sign it there) and the residual to propagate onward.
    `None` when the frame carried no read, meaning there is nothing to absorb and the frame propagates on
    unchanged. `basis` is this tekton's `(F, k)` coupling (its offer or tuning); omit it for a
    self-resolution membrane.

    This is the one function in the module that takes a measurement, so it is the one that binds to an
    instrument. `embodiment=` is the caller's answer and wins; otherwise the process default the host
    registered (`prism.instrument.set_default`). An empty slot raises `InstrumentRequired` rather than
    returning `None`, because `None` already means "the frame carried no read" and an unmeasured frame
    reads differently from a measured one that found nothing."""
    fn = _instrument.resolve(embodiment, "absorb_transmit", at="absorb_at_tekton")
    return fn(frame, basis=basis, **kw)


def absorb_need(need, basis=None, *, embodiment=None, **kw) -> Optional[dict]:
    """The provider-side frame check, shared across persona reach handlers (§A.2). If `need` carries a signal
    frame, absorb this tekton's coupled band (against `basis` — its offer coupling, or self-resolution) and
    return a frame-response dict::

        {"absorbed_k": k, "incident_energy": …, "absorbed_energy": …, "residual_energy": …,
         FRAME_KEY: <encoded residual>}

    The residual is what remains, to propagate to the next tekton. Returns `None` when the need carries no
    readable frame, so the provider falls through to its normal query path. A provider merges its own
    condensed result into this dict (e.g. `"hits"` or `"answer"`); that condensed artifact is what is signed
    at the tekton boundary, and the mid-stream frame is not.

    All three energies are reported so the hop is self-certifying: `incident == absorbed + residual` is
    checkable on the spot, and `absorbed / incident` is the 0 → 1 coordinate this hop contributes. An
    absorbed joule count on its own has no denominator, so it cannot say whether this tekton took 1% of the
    signal or 99% of it; the quantity that certifies is a fraction, and a fraction carries its denominator
    alongside it. `residual_energy` duplicates what the encoded frame holds by design — it is the number the
    next hop checks its own `incident_energy` against, which is what makes a chain of these auditable rather
    than a chain of unrelated readings. See `prism.conservation` for the whole-path account these feed."""
    enc = (need or {}).get(FRAME_KEY)
    if not enc:
        return None
    W = decode_frame(enc)
    if W is None:
        return None
    res = absorb_at_tekton(W, basis=basis, embodiment=embodiment, **kw)
    if res is None:
        return None
    absorbed, residual, k = res
    from .conservation import energy as _energy
    return {"absorbed_k": int(k),
            "incident_energy": _energy(W),
            "absorbed_energy": _energy(absorbed),
            "residual_energy": _energy(residual),
            FRAME_KEY: encode_frame(residual)}


def offer_basis(coords, *, rtol: Optional[float] = None):
    """A tekton's coupling basis from its offer — the orthonormal basis of the subspace the offer spans.

    A tekton offers a set of ontology nodes; `coords` is that offer as an `(n, F)` array, one row per offered
    node holding its F-dim coordinate. A measured frame carries noisy rows that the aperture resolves against
    a floor, whereas the offered coordinates are themselves the coupling directions — exact, and taken as
    given — so the coupling subspace is the span of those coordinates. This returns its orthonormal basis
    (the left singular vectors of `coords.T` with non-negligible singular value), an `(F, r)` array; then
    `absorb_at_tekton(frame, basis=offer_basis(coords))` makes the tekton absorb the band lying in what it
    offers, rather than the frame's self-structure. Singular values below `rtol · σ_max` are dropped as
    numerical null. Returns `None` when the offer spans nothing (empty or all-zero). Pure linear algebra on
    the given coordinates: it takes no reading from the aperture, since a span is a different quantity from a
    resolved-mode count.

    Geometry-agnostic: the caller supplies the coordinates (e.g. sage or ember stacking `geometry.dense_vec`
    for the synsets in `match._offers`), which keeps the optics package free of the ontology."""
    if coords is None:
        return None
    M = np.asarray(coords, dtype=np.float64)
    if M.ndim != 2 or M.shape[0] < 1 or M.shape[1] < 1 or not np.any(M):
        return None
    U, s, _ = np.linalg.svd(M.T, full_matrices=False)     # M.T is (F, n); U columns span the offer in F-space
    if s.size == 0 or s[0] <= 0:
        return None
    # The numerical null, derived from the matrix's own shape and dtype unless the caller states one.
    #
    # This is a rank tolerance: the largest singular value an exactly rank-deficient matrix can still
    # show once the SVD has rounded, which LAPACK and `numpy.linalg.matrix_rank` both put at
    # `max(m, n) · ε · σ_max`. It bounds the representation of a zero, and is a different quantity
    # from the accumulation bound in `prism.rounding`, which bounds how far a running total can have
    # drifted — there is no running total here. The two questions share the letter ε and nothing
    # else: this one asks whether a direction is there at all. `σ_max` (`s[0]`) enters as the scale
    # below, so the test is relative to the offer's own magnitude and a uniformly rescaled offer
    # reads identically.
    tol = (max(M.T.shape) * float(np.finfo(M.dtype).eps)) if rtol is None else float(rtol)
    r = int((s > tol * s[0]).sum())
    return U[:, :r] if r > 0 else None


__all__ = ["FRAME_KEY", "encode_frame", "decode_frame", "absorb_at_tekton", "offer_basis", "absorb_need"]
