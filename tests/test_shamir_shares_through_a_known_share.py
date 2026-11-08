"""`shares_through` completes a k=2 split from the secret and one share already handed out
(review 27): the same line, so the shares it gives are the ones that split had."""
import pytest

from prism.trust import shamir


def test_the_shares_through_a_known_share_are_that_split_s():
    secret = bytes(range(32))
    for _ in range(20):
        split = dict(shamir.split(secret, k=2, n=3))
        got = dict(shamir.shares_through(secret, (2, split[2]), [1, 3]))
        assert got == {1: split[1], 3: split[3]}
        assert shamir.combine([(1, got[1]), (3, got[3])]) == secret


@pytest.mark.parametrize("known, xs", [((0, b"\x00" * 32), [1]), ((2, b"\x00" * 31), [1]),
                                       ((2, b"\x00" * 32), [0])])
def test_it_refuses_a_bad_share(known, xs):
    with pytest.raises(ValueError):
        shamir.shares_through(bytes(32), known, xs)
