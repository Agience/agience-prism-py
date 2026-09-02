"""Carriers — the substrate adapters the communication plane rides on.

A carrier is an append-only, content-addressed leaf feed with one small face — `put(leaf)`, `poll()`,
`ids()`, `get(id)`. Isolation, delivery and order belong to the plane; transport belongs to the carrier,
so the plane is independent of which carrier delivered a leaf and "works across all substrates" means
"add a carrier".

Shipped here:
  - `InMemoryCarrier`  — loopback and tests.
  - `LocalDirCarrier`  — a durable filesystem folder (one JSON file per leaf, keyed by id) — the same
                         shape a shared NAS folder or an S3 prefix has; the production carriers plug in
                         at this seam (NasFacet is the NAS instance; an S3 carrier is the rendezvous).
  - `S3Carrier`        — an S3 prefix, the durable global rendezvous.
  - `StoreCarrier`     — the local carrier over the mantle lattice: a leaf is persisted as an artifact in
                         the shared lattice store, so the ground plane is the lattice itself. This makes a
                         reach a real store-and-forward round trip on one node — the reacher writes a need
                         artifact, a provider's serve loop polls new need artifacts for its cap out of the
                         same store, and discharges an evidence artifact back onto it; the reacher reads
                         the evidence back by provenance correlation, with no live receiver and no
                         `reply_to`.

`reconcile(a, b)` is anti-entropy: an id-set diff that leaves both carriers holding the union — the
correctness core of Merkle anti-entropy (a real Merkle tree only makes the diff sublinear, not more
correct). Idempotent: a leaf already present is never duplicated (content-addressed by id).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from .canonical import canonical_string as _jcs_string   # the one canonicaliser for the package


def _leaf_order(leaf: Dict[str, Any]):
    """The total order over carried leaves: `(hlc, id)` compared as UTF-8 encoded bytes.

    Every carrier returns leaves in this order, and a JavaScript or C carrier returns the same one —
    polling is how two nodes agree on what arrived and in what sequence.

    Encoding first is what makes the order language-independent. Python compares `str` by code point;
    JavaScript compares by UTF-16 code unit, and an astral character (above U+FFFF) is a surrogate
    pair beginning `0xD800`, which sorts below `0xFFFD`. Measured: given ids `z`, `U+FFFD` and
    `U+10000`, Python orders them `z, FFFD, 10000` while JavaScript's default sort gives
    `z, 10000, FFFD`. UTF-8 byte order is code point order, so encoding first gives one total order in
    every language — the same rule `structural.ts` applies to CBOR map keys.

    In Python this changes no output; it states the contract the other implementations are held to.
    """
    return (str(leaf.get("hlc", "")).encode("utf-8"), str(leaf.get("id", "")).encode("utf-8"))


class InMemoryCarrier:
    """A loopback carrier — an append-only, id-deduped leaf log."""

    def __init__(self) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []

    def put(self, leaf: Dict[str, Any]) -> Dict[str, Any]:
        i = leaf["id"]
        if i not in self._by_id:                       # content-addressed → idempotent
            self._by_id[i] = dict(leaf)
            self._order.append(i)
        return leaf

    def poll(self) -> List[Dict[str, Any]]:
        return [dict(self._by_id[i]) for i in self._order]

    def ids(self) -> Set[str]:
        return set(self._by_id)

    def get(self, leaf_id: str) -> Optional[Dict[str, Any]]:
        leaf = self._by_id.get(leaf_id)
        return dict(leaf) if leaf else None

    def __len__(self) -> int:
        return len(self._by_id)


class LocalDirCarrier:
    """A durable filesystem carrier — one JSON file per leaf, named by id. This is the NAS/shared-folder
    /S3-prefix shape: store-and-forward for free (a leaf sits until polled), NAT-proof, and the substrate
    a partitioned or offline node reconciles against on reconnect."""

    def __init__(self, root: Any) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, leaf_id: str) -> Path:
        return self.root / ("%s.json" % leaf_id)

    def put(self, leaf: Dict[str, Any]) -> Dict[str, Any]:
        p = self._path(leaf["id"])
        if not p.exists():                             # idempotent: never rewrite an existing leaf
            p.write_text(_jcs_string(leaf),
                         encoding="utf-8")
        return leaf

    def poll(self) -> List[Dict[str, Any]]:
        leaves = []
        for f in self.root.glob("*.json"):
            try:
                leaves.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:                          # a malformed leaf is skipped, never fatal
                continue
        return sorted(leaves, key=_leaf_order)

    def ids(self) -> Set[str]:
        return {f.stem for f in self.root.glob("*.json")}

    def get(self, leaf_id: str) -> Optional[Dict[str, Any]]:
        p = self._path(leaf_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None


# NasCarrier is a LocalDirCarrier pointed at a shared NAS mount (the `_comms/` folder the fleet uses).
# Same code — a shared folder is a shared folder — named for the deployment that uses it.
NasCarrier = LocalDirCarrier


class S3Carrier:
    """A carrier over an S3 prefix — the durable, NAT-proof global rendezvous (store-and-forward: a leaf
    waits in the bucket until a node polls it). One object per leaf, key `<prefix>/<leaf id>.json`.

    Duck-typed on an S3 client (`put_object` / `get_object` / `list_objects_v2`) so a fake dict-backed
    client exercises the full logic without a live bucket, and so the real `boto3` or mantle S3 client
    drops in unchanged. Writing to the fleet bucket is a deploy step, gated by the standing local-only
    rule; what lives here is the carrier code and its behaviour, tested against a fake."""

    def __init__(self, s3, bucket: str, prefix: str = "mesh/comms") -> None:
        self._s3, self._bucket, self._prefix = s3, bucket, prefix.rstrip("/")

    def _key(self, leaf_id: str) -> str:
        return "%s/%s.json" % (self._prefix, leaf_id)

    def put(self, leaf: Dict[str, Any]) -> Dict[str, Any]:
        # content-addressed → writing the same leaf twice is idempotent (identical bytes to the same key)
        self._s3.put_object(Bucket=self._bucket, Key=self._key(leaf["id"]),
                            Body=_jcs_string(leaf).encode("utf-8"))
        return leaf

    def ids(self) -> Set[str]:
        out: Set[str] = set()
        token = None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": self._prefix + "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = self._s3.list_objects_v2(**kw)
            for o in resp.get("Contents", []) or []:
                stem = o["Key"].rsplit("/", 1)[-1]
                if stem.endswith(".json"):
                    out.add(stem[:-5])
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return out

    def get(self, leaf_id: str) -> Optional[Dict[str, Any]]:
        try:
            body = self._s3.get_object(Bucket=self._bucket, Key=self._key(leaf_id))["Body"].read()
            return json.loads(body)
        except Exception:                              # missing/unreadable object → not present here
            return None

    def poll(self) -> List[Dict[str, Any]]:
        leaves = [self.get(i) for i in self.ids()]
        return sorted((leaf for leaf in leaves if leaf is not None), key=_leaf_order)


# The lattice content_type a carried leaf (a NEED / EVIDENCE envelope) is persisted under. Namespaced so
# comm leaves never collide with corpus artifacts sharing the store — `poll()` reads back only these.
CARRIER_LEAF_CT = "application/vnd.agience.carrier-leaf+json"


class StoreCarrier:
    """A carrier backed by a mantle lattice store — store-and-forward over the ground itself.

    Each leaf (a sealed need or evidence envelope from `prism.reach`) is wrapped as a lattice artifact
    (`{id: <leaf id>, content_type: CARRIER_LEAF_CT, leaf: <the leaf>}`) and upserted through the
    artifact store. The leaf id is content-addressed by the reach core, so persistence is idempotent
    (a re-delivered leaf is the same artifact id, and is skipped). `poll()` reads the wrapped leaves
    back and re-sorts them `(hlc, id)` — arrival-independent, exactly like `LocalDirCarrier`. The leaf's
    routing fields (`to/origin/hlc/root/in_reply_to/…`) live in cleartext on the wrapper while the
    payload stays sealed inside `leaf.sealed`, so the lattice is a faithful ground plane: it holds the
    provenance in the clear and sees neither the question nor the answer.

    `store` may be an ember `LocalStore` bundle (`.artifacts`) or a raw `LatticeArtifactStore` — either
    exposes `put_artifact` / `get_artifact` / `list_artifacts`. Nothing here writes edges or content: a
    carrier leaf is a self-contained envelope vertex.
    """

    def __init__(self, store: Any, *, content_type: str = CARRIER_LEAF_CT) -> None:
        self._arts = getattr(store, "artifacts", store)
        self._ct = content_type
        # ── The watermark ────────────────────────────────────────────────────────────────────────
        # In-memory on purpose, which is what upholds the one invariant a cursor must hold: it may
        # never skip. A watermark that survived the process could advance past a leaf that never
        # reached the index, and that leaf would sit behind the cursor with nothing reporting it.
        # This one starts at 0 on every boot, so a restart re-reads the whole plane and a crash
        # loses nothing — the cost is one full scan per process lifetime rather than one per poll.
        #
        # The cursor bounds the read, not the answer. `poll()` returns the whole index every time,
        # because it is a repeatable read of the plane rather than a stream (see `poll`). The
        # watermark exists so the store is asked only for what it has gained.
        self._seq = 0
        self._index: Dict[str, Dict[str, Any]] = {}     # leaf id -> leaf, folded in as `_seq` grows
        self._bounded = callable(getattr(self._arts, "page_by_ct", None))

    def put(self, leaf: Dict[str, Any]) -> Dict[str, Any]:
        i = leaf["id"]
        if self._arts.get_artifact(i) is None:            # content-addressed → idempotent, never rewrite
            self._arts.put_artifact({"id": i, "content_type": self._ct, "hlc": leaf.get("hlc", ""),
                                     "leaf": dict(leaf)})
        return leaf

    def poll(self) -> List[Dict[str, Any]]:
        """Every leaf on the plane, `(hlc, id)`-ordered — the whole set, on every call.

        Returning the whole set is load-bearing. `poll()` is a repeatable read of the plane with more
        than one consumer, rather than a stream consumed once. The reach's requester and its provider
        both poll the same plane, and a requester asking `evidence(handle)` after the cadence has
        already polled still sees that evidence. A leaf a caller has not asked for yet is not a leaf
        it has consumed.

        The store is asked only for what it has gained since the last look (`_seq > cursor`, an
        indexed range walk on an injective sequence); those rows are folded into an index the carrier
        holds, and the index is returned whole. The cost of a poll is set by the new leaves since the
        last look rather than by the size of the whole plane, so a steady-state poll stays cheap as
        the plane grows. The index holds no more than one full read materialises, so the speed costs
        no memory.

        A store that cannot page takes the full-read path. `page_by_ct` is a mantle capability; a
        dict store or a foreign lattice has no `_seq` to cursor on, and for those a full read is the
        correct answer. The branch is chosen once at construction, so the two stay consistent across
        calls."""
        if not self._bounded:
            leaves = [d["leaf"] for d in self._arts.list_artifacts(content_type=self._ct)
                      if d.get("leaf") is not None]
            return sorted(leaves, key=_leaf_order)

        while True:
            page = self._arts.page_by_ct(content_type=self._ct, after_seq=self._seq)
            if not page:
                break
            start = self._seq
            for row in page:
                leaf = (row.get("doc") or {}).get("leaf")
                if leaf is not None:
                    self._index[leaf.get("id")] = leaf
                # The cursor advances over every row this pass decided about, including one that
                # carried no leaf. A row of this content type with no `leaf` key is structurally not
                # a leaf and will not become one, so holding the cursor behind it to retry would
                # stall the plane on a single malformed row. The never-skip rule covers transient
                # failure, which this is not.
                self._seq = max(self._seq, int(row.get("_seq") or self._seq))
            if self._seq <= start:
                # Rows came back and the cursor stood still, which happens only when a store hands
                # back rows carrying no `_seq`. Stopping is the safe act: continuing re-issues the
                # identical query indefinitely, and a poll that never returns is a worse outage than
                # one that returns what it has.
                break
        return sorted(self._index.values(), key=_leaf_order)

    def ids(self) -> Set[str]:
        out: Set[str] = set()
        for doc in self._arts.list_artifacts(content_type=self._ct):
            leaf = doc.get("leaf")
            if leaf is not None:
                out.add(leaf.get("id", doc.get("id")))
        return out

    def get(self, leaf_id: str) -> Optional[Dict[str, Any]]:
        doc = self._arts.get_artifact(leaf_id)
        if not doc or doc.get("content_type") != self._ct:
            return None
        return doc.get("leaf")


def reconcile(a, b) -> int:
    """Anti-entropy between two carriers — an id-set diff; both end holding the union. Returns the number
    of leaves transferred. Idempotent (a second call transfers 0). The correctness core of Merkle
    anti-entropy; a real Merkle tree makes the `ids()` diff sublinear but no more correct."""
    ai, bi = a.ids(), b.ids()
    n = 0
    for i in ai - bi:
        leaf = a.get(i)
        if leaf is not None:
            b.put(leaf)
            n += 1
    for i in bi - ai:
        leaf = b.get(i)
        if leaf is not None:
            a.put(leaf)
            n += 1
    return n


__all__ = ["InMemoryCarrier", "LocalDirCarrier", "NasCarrier", "S3Carrier", "StoreCarrier",
           "CARRIER_LEAF_CT", "reconcile"]
