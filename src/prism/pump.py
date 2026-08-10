"""The pump loop — the serve-loop cadence that makes store-and-forward reaches self-driving.

A `Reactor` over a carrier, with no live fabric, completes a round-trip when `pump(carrier)` is called: a
provider handles needs and discharges evidence back onto the ground, and a requester absorbs the evidence
off it. `PumpLoop` is the cadence that supplies those calls — it drives every registered reactor's `pump`
over one shared carrier, on an interval, in a background daemon thread. A persona server then answers
reaches and a requester collects them with nobody hand-driving the loop, which is what a true two-process
run needs.

Pure and local: it drives whatever reactors and carrier a host wires, e.g. ember's requester reactor
(`ember.reach.reactor`) plus lumen and sage server reactors (`*/reach_provider.py`) sharing one
`prism.carriers.StoreCarrier`. Pointing that carrier at a shared DB file, or an `S3Carrier` at the mesh
bucket, and running the loop against node 71's live store is the gated deploy step. The mechanism here is
the local, tested substrate under it, and drives nothing until a host constructs it.

Determinism: `tick()` is one synchronous cadence pass, driving every reactor once, so behaviour is
testable with no threads and no sleeps; `start()`/`stop()` wrap `tick()` in the background runner. A
reactor whose `pump` raises is skipped, so one bad endpoint leaves the shared loop running.
"""
from __future__ import annotations

import threading
from typing import Any, Iterable, List, Optional


class PumpLoop:
    """Drive a set of `Reactor`s' `pump(carrier)` on a shared carrier, on an interval.

    Construct with the shared carrier and the reactors to drive (add more later with `add`). `tick()` runs
    one cadence pass and returns how many reactors were pumped; `start()` runs `tick()` every `interval`
    seconds on a daemon thread until `stop()`. Usable as a context manager (`with PumpLoop(...): …`)."""

    def __init__(self, carrier: Any, reactors: Optional[Iterable[Any]] = None, *,
                 interval: float = 0.05) -> None:
        self._carrier = carrier
        self._reactors: List[Any] = list(reactors or [])
        self._interval = float(interval)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # One cadence at a time. Reentrant, so a handler that reaches again from inside its own pump
        # proceeds on its own thread — the exclusion this enforces is between threads.
        self._pumping = threading.RLock()

    def add(self, reactor: Any) -> "PumpLoop":
        """Register another reactor to drive (thread-safe — a server can be added after the loop starts)."""
        with self._lock:
            self._reactors.append(reactor)
        return self

    def tick(self) -> int:
        """One cadence pass: drive every registered reactor's `pump` over the shared carrier. Returns the
        number pumped. A reactor that raises is skipped, so one bad endpoint leaves the loop running.

        The whole pass is held under `_pumping`, so exactly one cadence runs at a time across threads.
        A loop is a cadence — one beat at a time — and `pump` is not reentrant across providers:
        `Provider.pump` saves and restores `self._outbound` around its call, so two concurrent pumps
        on one provider would clobber each other's outbound carrier.

        The serialisation also closes a door onto a BLAS defect. `ReachHost` drives one loop from two
        threads — `start()` runs `_run` on a daemon thread, and `respond()` → `prism.pump.resolve`
        calls `tick()` on the caller's thread — and with the pass unserialised both could enter
        `Reactor.pump` on the same reactors, both reach the conversation tekton, and both call
        `numpy.linalg.eigh` (`entroptics/reads.py:262`) concurrently. `eigh` is not concurrency-safe
        on this box's OpenBLAS: concurrent calls from independent threads can crash the process
        (access violation) or hang, and a clean run of the underlying probe is not evidence of
        absence — the fault is intermittent by nature.

        The BLAS defect itself remains, out of reach through this door. Any two threads calling into
        entroptics can fault, so a process that may do so pins the BLAS pool
        (`OPENBLAS_NUM_THREADS=1`) — including any ASGI host serving sync endpoints off a threadpool.
        The pin travels with the package: `prism/__init__.py` sets it via `os.environ.setdefault`
        above its imports, and the same line is in `mantle`, `ember`, `prism` and `entroptics`, every
        package that calls into LAPACK. It sits at package scope because OpenBLAS sizes its pool when
        the library loads, so setting the variable after `import numpy` is inert (see
        `test_blas_thread_pin.py` in `ember`, `mantle` and `entroptics`). Two further limits apply:
        `setdefault` yields to an operator's exported value, and a process that imported numpy before
        the package is beyond the pin's reach."""
        with self._lock:
            reactors = list(self._reactors)
        pumped = 0
        with self._pumping:                              # one cadence at a time, across threads
            for r in reactors:
                try:
                    r.pump(self._carrier)
                    pumped += 1
                except Exception:
                    pass                                 # a bad endpoint is skipped; the loop runs on
        return pumped

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> "PumpLoop":
        """Begin driving the cadence on a background daemon thread. Idempotent while already running."""
        if self.running:
            return self
        self._stop.clear()
        t = threading.Thread(target=self._run, name="beam-pump-loop", daemon=True)
        self._thread = t
        t.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)              # sleeps between ticks, wakes immediately on stop

    def stop(self, *, timeout: float = 2.0) -> None:
        """Signal the loop to stop and join the thread (best-effort within `timeout`)."""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
        self._thread = None

    def __enter__(self) -> "PumpLoop":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def resolve(requester: Any, need: Any, *, to: str, loop: "PumpLoop", max_ticks: int = 200) -> Any:
    """Synchronous request over a store-and-forward carrier: place a need on `requester` for capability
    `to`, then drive `loop` (the servers plus this requester) until the evidence returns, up to
    `max_ticks` cadence passes. Returns the evidence, or `None` if it never resolved — silence stays
    silence.

    This is what a request/response caller (a chat bff, a CLI) uses over a carrier. The one-shot
    `Reactor.reach()` places and collects without a `pump`, so over store-and-forward it returns `None`.
    `resolve` bounds the drive — no threads and no sleeps, since each `tick()` is one synchronous pass —
    so a caller gets a deterministic answer-or-`None` without standing up the background `start()` loop.
    Use the background loop for a long-lived server, and `resolve` for a single request that returns
    inline."""
    handle = requester.reach(need, to=to)
    for _ in range(max(1, int(max_ticks))):
        loop.tick()
        ev = requester.evidence(handle)
        if ev is not None:
            return ev
    return None


__all__ = ["PumpLoop", "resolve"]
