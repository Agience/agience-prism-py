"""`prism.trust.shamir` — the one Shamir k-of-n implementation in the workspace.

Origin's key oracle re-exports it (`origin.services.shamir`) and Mantle's threshold master-key store
splits and combines with it, so these cases pin the arithmetic both depend on.
"""
from __future__ import annotations

import ast
import itertools
import os
import pathlib
import sys

import pytest

from prism.trust import shamir


def test_the_module_needs_only_the_standard_library():
    tree = ast.parse(pathlib.Path(shamir.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add((node.module or "").split(".")[0])
    assert roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names)


@pytest.mark.parametrize("k,n", [(2, 2), (2, 3), (3, 5), (5, 5)])
def test_every_k_subset_reconstructs_the_secret(k, n):
    secret = os.urandom(32)
    shares = shamir.split(secret, k=k, n=n)
    assert [x for x, _ in shares] == list(range(1, n + 1))
    for subset in itertools.combinations(shares, k):
        assert shamir.combine(list(subset)) == secret


def test_a_share_is_not_the_secret_in_the_clear():
    secret = b"\x00" * 64
    for _x, y in shamir.split(secret, k=2, n=3):
        assert y != secret                   # 2^-512 to fail by chance


def test_fewer_than_two_shares_and_duplicates_are_refused():
    shares = shamir.split(b"key", k=2, n=3)
    with pytest.raises(ValueError):
        shamir.combine(shares[:1])
    with pytest.raises(ValueError):
        shamir.combine([shares[0], shares[0]])


def test_shares_of_different_lengths_are_refused():
    """Origin's copy truncated to the first share's length when it was the shorter one, returning
    wrong bytes with no error, and raised IndexError the other way round."""
    a = shamir.split(b"a-longer-secret", k=2, n=3)
    b = shamir.split(b"short", k=2, n=3)
    with pytest.raises(ValueError):
        shamir.combine([a[0], b[1]])
    with pytest.raises(ValueError):
        shamir.combine([b[1], a[0]])


@pytest.mark.parametrize("k,n", [(1, 3), (4, 3), (2, 256)])
def test_an_impossible_threshold_is_refused(k, n):
    with pytest.raises(ValueError):
        shamir.split(b"x", k=k, n=n)


@pytest.mark.parametrize("x", [0, 256, -1, "1", True])
def test_a_share_outside_one_to_255_is_refused(x):
    """x = 0 is the secret's own coordinate and outside the field's share range; combining with it
    returned bytes rather than an error."""
    shares = shamir.split(b"key", k=2, n=3)
    with pytest.raises(ValueError):
        shamir.combine([shares[0], (x, shares[1][1])])
