"""The ground-plane poll is bounded — a `_seq` watermark on the read, not on the return.

An unbounded `StoreCarrier.poll()` re-reads every leaf ever placed from the store on every call, and
a reach polls twice per answer. Measured on the live shard: 302.7 ms over 1,250 leaves, ~605 ms per
turn, growing with every answer the system had ever given. A carrier that degrades without bound
cannot carry a conversation. Bounded, the same poll costs 3.4 ms in steady state, 89x less.

What is bounded is the store read; the return is always the whole plane. `poll()` is a repeatable
read of the plane rather than a stream consumed once, and it has more than one consumer: the reach's
requester and its provider poll the same plane, so a requester asking `evidence(handle)` after the
cadence has already polled still sees that evidence.

What these tests watch for:
  - poll stops returning the whole plane, so a leaf handed out once goes missing on the next call
    and a second consumer never sees it;
  - a leaf placed after the first poll never appears;
  - a store that cannot page loses leaves instead of falling back to a full read;
  - the store read grows with the plane, so the cost does too;
  - a malformed row stalls the plane forever, or spins the pager in an infinite loop.
"""

from prism.carriers import CARRIER_LEAF_CT, StoreCarrier


class _Arts:
    """A minimal artifact store with the `_seq` discipline: monotone, injective, assigned on write."""

    def __init__(self):
        self.rows = {}          # id -> {"_seq": int, "doc": {...}}
        self._next = 0

    def get_artifact(self, i):
        r = self.rows.get(i)
        return dict(r["doc"]) if r else None

    def put_artifact(self, doc):
        self._next += 1
        self.rows[doc["id"]] = {"_seq": self._next, "doc": dict(doc)}

    def list_artifacts(self, *, content_type=None, **kw):
        for r in sorted(self.rows.values(), key=lambda r: r["doc"]["id"]):
            if content_type is None or r["doc"].get("content_type") == content_type:
                yield dict(r["doc"])

    def page_by_ct(self, *, content_type, after_seq=0, limit=512):
        rows = [r for r in self.rows.values()
                if r["doc"].get("content_type") == content_type and r["_seq"] > after_seq]
        rows.sort(key=lambda r: r["_seq"])
        return [{"_seq": r["_seq"], "doc": dict(r["doc"])} for r in rows[:limit]]


class _UnpageableArts(_Arts):
    """A store with no `_seq` to cursor on — an in-memory dict, or a foreign lattice."""
    page_by_ct = None                      # not callable -> the carrier must choose the full read


def _leaf(i, hlc="1"):
    return {"id": i, "hlc": hlc, "to": "x", "sealed": ""}


def test_poll_returns_the_WHOLE_plane_every_time():
    """The contract. `poll()` is a repeatable read, not a stream — two consumers share one plane and
    each still sees the whole of it."""
    c = StoreCarrier(_Arts())
    for i in "abc":
        c.put(_leaf(i))
    assert {leaf["id"] for leaf in c.poll()} == set("abc")
    assert {leaf["id"] for leaf in c.poll()} == set("abc"), "a second poll lost leaves it had returned"
    assert {leaf["id"] for leaf in c.poll()} == set("abc")


def test_a_leaf_placed_AFTER_a_poll_joins_the_plane():
    c = StoreCarrier(_Arts())
    c.put(_leaf("a"))
    assert {leaf["id"] for leaf in c.poll()} == {"a"}
    c.put(_leaf("b"))
    assert {leaf["id"] for leaf in c.poll()} == {"a", "b"}
    assert {leaf["id"] for leaf in c.poll()} == {"a", "b"}


def test_NOTHING_IS_EVER_LOST_across_interleaved_writes_and_polls():
    """The invariant. After any interleaving of writes and polls, a poll returns exactly what has
    been placed. A leaf dropped by the cursor is silent by construction, so it is asserted."""
    c = StoreCarrier(_Arts())
    placed = []
    for round_ in range(12):
        for k in range(round_ % 3):                     # 0, 1 or 2 writes between polls
            i = "leaf-%d-%d" % (round_, k)
            placed.append(i)
            c.put(_leaf(i))
        got = [leaf["id"] for leaf in c.poll()]
        assert sorted(got) == sorted(placed), "the plane lost a leaf at round %d" % round_
        assert len(got) == len(set(got)), "a leaf was returned twice"


def test_a_store_that_cannot_page_keeps_the_OLD_path_whole():
    """A dict store or a foreign lattice has no `_seq` to cursor on, and for those a full read is
    the only correct answer. The branch is chosen once at construction so the two cannot diverge."""
    c = StoreCarrier(_UnpageableArts())
    assert c._bounded is False
    for i in "abc":
        c.put(_leaf(i))
    assert {leaf["id"] for leaf in c.poll()} == set("abc")
    assert {leaf["id"] for leaf in c.poll()} == set("abc")


def test_a_row_with_no_leaf_does_not_stall_the_plane_forever():
    """A row of this content type with no `leaf` key is structurally not a leaf and never will be.
    Holding the cursor behind it to 'retry' would stall the plane permanently on one malformed row —
    worse than the skip the rule guards against, because that rule is about transient failure and
    this row is malformed for good."""
    arts = _Arts()
    c = StoreCarrier(arts)
    arts.put_artifact({"id": "junk", "content_type": CARRIER_LEAF_CT})     # no "leaf"
    c.put(_leaf("a"))
    assert {leaf["id"] for leaf in c.poll()} == {"a"}
    assert {leaf["id"] for leaf in c.poll()} == {"a"}         # and the junk never becomes a leaf


def test_a_store_that_returns_rows_without_seq_terminates():
    """Impossible while `_seq` is present and injective — so reaching it means a store handed back
    rows without one. Stopping is the only safe act: continuing re-issues the identical query
    forever, and a poll that never returns is a worse outage than one that returns what it has."""
    class _NoSeq(_Arts):
        def page_by_ct(self, *, content_type, after_seq=0, limit=512):
            return [{"doc": {"id": "a", "content_type": content_type, "leaf": _leaf("a")}}]

    c = StoreCarrier(_NoSeq())
    assert [leaf["id"] for leaf in c.poll()] == ["a"]         # returns what it collected, and terminates


def test_the_STORE_READ_stops_growing_with_the_plane():
    """The bound as a property rather than a timing: the rows a steady-state poll fetches stay
    constant as the plane grows, even though what it returns grows with it."""
    fetched = []

    class _Counting(_Arts):
        def page_by_ct(self, *, content_type, after_seq=0, limit=512):
            rows = _Arts.page_by_ct(self, content_type=content_type,
                                    after_seq=after_seq, limit=limit)
            fetched.append(len(rows))
            return rows

    c = StoreCarrier(_Counting())
    for i in range(200):
        c.put(_leaf("leaf-%03d" % i))
    c.poll()                                            # the one full load, per process lifetime
    fetched.clear()

    c.put(_leaf("one-more"))
    out = c.poll()
    assert sum(fetched) == 1, "the store was re-read for leaves already held: %r" % (fetched,)
    assert len(out) == 201, "the RETURN must still be the whole plane"

    fetched.clear()
    assert len(c.poll()) == 201
    assert sum(fetched) == 0, "an idle poll fetched rows it already had"
