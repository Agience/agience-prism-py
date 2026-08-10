"""Deterministic MinHash + LSH — scalable near-duplicate detection with no model.

Near-dup consolidation needs candidate pairs without O(n²) comparison. MinHash estimates Jaccard
similarity from fixed-size signatures; LSH banding surfaces only the pairs likely above threshold.
Everything is hashing + min + bucketing — deterministic (fixed seeds), recomputable, model-free.
This is the "computed, not learned" alternative to an ANN index over learned embeddings.

  sig = signature(text)                      # N min-hashes (a fingerprint)
  groups = near_dup_groups(items)            # [(canonical_idx, [member_idx...])] via LSH+verify

It imports `hashlib`, `math` and `re` and nothing else — no store, no ontology, no vocabulary — so
it sits on prism's dependency-free base beside `prism.resolution`, which names `minhash` in its
opening list of resolution questions. "Are these two documents the same thing" is a resolution
question over a sampled proportion, and the estimator here derives the same quantity the optics
read does.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

_MERSENNE = (1 << 61) - 1                     # a large prime for universal hashing
_NUM_HASHES = 128
_BANDS = 32                                   # rows = NUM/BANDS = 4 -> high recall; verify filters
_K = 5                                        # shingle size (words)

# Fixed (a, b) coefficients — derived deterministically from a constant seed, so signatures are
# identical across processes and runs (required: two workers must agree).
def _coeffs(n: int) -> List[Tuple[int, int]]:
    out = []
    for i in range(n):
        h = hashlib.blake2b(f"minhash-coeff-{i}".encode(), digest_size=16).digest()
        a = (int.from_bytes(h[:8], "big") % (_MERSENNE - 1)) + 1
        b = int.from_bytes(h[8:], "big") % _MERSENNE
        out.append((a, b))
    return out


_COEFFS = _coeffs(_NUM_HASHES)


def _band_bytes(chunk) -> bytes:
    """One LSH band's values → bytes, as 8-byte big-endian integers concatenated.

    The key is built from the values rather than from the container, so a band bucketed from a list,
    a tuple or a numpy array lands in the same bucket. `group_signatures` is typed
    `Sequence[Sequence[int]]` and accepts all three, and near-duplicates are found the same way for
    each.

    Eight bytes because signature values are `mod 2**61-1`; big-endian to match `_shingles` and
    `_coeffs`, which read their digests that way. Fixed width makes the concatenation unambiguous
    with no separator, and any language reproduces it.
    """
    return b"".join(int(v).to_bytes(8, "big") for v in chunk)


def _shingles(text: str, k: int = _K) -> List[int]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    if len(words) < k:
        s = {" ".join(words)} if words else set()
    else:
        s = {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}
    return [int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big") for sh in s]


def signature(text: str, *, num_hashes: int = _NUM_HASHES) -> Tuple[int, ...]:
    """The MinHash signature — for hash function i, the min of (a_i*x + b_i) mod prime over all
    shingle hashes x. Estimated Jaccard(A,B) = fraction of signature positions that match."""
    sh = _shingles(text)
    if not sh:
        return tuple([0] * num_hashes)
    sig = []
    for a, b in _COEFFS[:num_hashes]:
        sig.append(min(((a * x + b) % _MERSENNE) for x in sh))
    return tuple(sig)


def is_degenerate(sig: Sequence[int]) -> bool:
    """An all-zero signature means `_shingles` produced NOTHING — it is the absence of a
    measurement, not a measurement of emptiness. `signature()` returns `[0]*num_hashes` for empty
    text, whitespace, punctuation-only content, and any document with no `[a-z0-9]` characters
    (which includes entire non-Latin scripts)."""
    return not sig or not any(sig)


def estimated_jaccard(s1: Sequence[int], s2: Sequence[int]) -> float:
    """Estimated Jaccard over two signatures.

    A degenerate signature scores 0.0 against anything, including another degenerate one. A
    128-tuple of zeros carries no information about its document, so there is no basis on which to
    call two of them similar. The cost of holding them apart is a missed duplicate; merging on no
    evidence archives unrelated content, and that direction is unrecoverable. Degenerate signatures
    also collide in every LSH band, so without this they arrive as one bucket and union-find would
    collapse the whole unparseable tail of a corpus into a single group.

    Signatures of different lengths also score 0.0. `zip` truncates to the shorter one while the
    denominator is `len(s1)`, so a similarity computed across lengths depends on argument order and
    can land either side of a threshold. Comparing signatures of different lengths is a caller
    error, and 0.0 is what it yields."""
    if is_degenerate(s1) or is_degenerate(s2):
        return 0.0
    if len(s1) != len(s2):
        return 0.0
    m = sum(1 for x, y in zip(s1, s2) if x == y)
    return m / len(s1)


# ── The merge boundary is the estimator's own resolution ─────────────────────────────────────────
# Merging decides the most consequential thing this system does: when two things are one thing. A
# wrong merge leaves no trace, because the evidence that would reveal it is what got merged away.
# So the boundary is derived rather than picked:
#
#   * the LSH candidate score distribution has no valley: on real corpora it decays smoothly across
#     the candidate range with nothing near a natural cut, so "near-duplicate" and "merely similar"
#     form one continuum and any cut through it is ill-posed;
#   * the estimator's own standard error at J is `sqrt(J(1-J)/k)` — at J=0.85 with k=128 hashes
#     that is **±0.0316**, coarser than the gaps between candidate constants;
#   * so the defensible boundary is: merge when the read cannot resolve the pair apart from
#     identical. That is `J_hat + se(J_hat) >= 1.0`, i.e. `J_hat >= 1 - se`, which for k=128 yields
#     **0.9684**.
#
# The boundary is a function of `k` alone, and `k` is a property of the instrument we declare (how
# many hashes we compute) rather than a claim about the world. Widen the signature and the boundary
# tightens, exactly as a better instrument should.


def resolution(j: float, *, num_hashes: int = _NUM_HASHES) -> float:
    """The standard error of a MinHash Jaccard estimate at `j` — the estimator's resolution.

    `se = sqrt(j(1-j)/k)`: each of the k hashes is an independent Bernoulli trial with success
    probability J, so the estimate is a binomial proportion and this is its exact standard error.
    A difference smaller than this is not a difference the instrument can see."""
    j = min(1.0, max(0.0, float(j)))
    k = max(1, int(num_hashes))
    return math.sqrt(j * (1.0 - j) / k)


def merge_boundary(*, num_hashes: int = _NUM_HASHES) -> float:
    """The Jaccard at which this estimator can no longer tell a pair from identical.

    Solves `j + sqrt(j(1-j)/k) = 1` — the largest j whose one-sigma band still touches 1.0.
    Closed form: with `d = 1 - j`, `d^2 = (1-d)d/k` -> `d = 1/(k+1)`, so the boundary is
    `1 - 1/(k+1)`. For k=128 that is 0.99225; the looser reading used in the measurement above
    (se evaluated at the candidate rather than at the boundary) gives ~0.968. Both select exact
    identity, which `content_ref` already provides for free — which is the finding: at this
    instrument's resolution, a safe near-duplicate merge is exactly an identity match."""
    k = max(1, int(_NUM_HASHES if num_hashes is None else num_hashes))
    return 1.0 - 1.0 / (k + 1.0)


def near_dup_groups(items: Sequence[Tuple[str, str]], *, threshold: Optional[float] = None,
                    bands: int = _BANDS) -> List[List[int]]:
    """items = [(id, text)]. Returns groups (lists of item indices) of near-duplicates."""
    if len(items) < 2:
        return []
    return group_signatures([signature(t) for _id, t in items], threshold=threshold, bands=bands)


def group_signatures(sigs: Sequence[Sequence[int]], *, threshold: Optional[float] = None,
                     bands: int = _BANDS) -> List[List[int]]:
    """LSH + verify + union-find over PRE-COMPUTED signatures (the fast path: signatures are
    stored on artifacts at ingest, so consolidation never re-reads content). Returns index groups."""
    n = len(sigs)
    if n < 2:
        return []
    # None means "the instrument's own resolution" — the only non-arbitrary boundary (see above).
    if threshold is None:
        threshold = merge_boundary(num_hashes=len(sigs[0]) or _NUM_HASHES)
    rows = len(sigs[0]) // bands
    # LSH: bucket by each band; items sharing a band-bucket are candidates.
    # Degenerate signatures stay out of the buckets. An all-zero signature is identical to every
    # other all-zero signature in every band, so the unparseable tail of a corpus (empty,
    # whitespace, punctuation-only, non-Latin) would otherwise form one enormous candidate bucket —
    # quadratic in the size of that tail, and every pair in it scoring 0.0 at verification anyway.
    # Excluding them up front is both correct and cheap.
    buckets: Dict[Tuple[int, bytes], List[int]] = {}
    for idx, sig in enumerate(sigs):
        if is_degenerate(sig):
            continue
        for band in range(bands):
            chunk = sig[band * rows:(band + 1) * rows]
            key = (band, hashlib.blake2b(_band_bytes(chunk), digest_size=8).digest())
            buckets.setdefault(key, []).append(idx)
    # union-find over verified candidate pairs
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for members in buckets.values():
        if len(members) < 2:
            continue
        base = members[0]
        for other in members[1:]:
            if find(base) == find(other):
                continue
            if estimated_jaccard(sigs[base], sigs[other]) >= threshold:
                parent[find(base)] = find(other)
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]
