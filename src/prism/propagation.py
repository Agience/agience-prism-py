"""The screened-propagator accumulation — the field-spreading algorithm, kernel-side.

The propagation kernel is `prism.law.attenuate` (the one screened propagator, `exp(-d/xi)`); this module
is its accumulation over a field: `Σ energy · attenuate(d, xi) · specificity`, gated by the mass gap.

Pure math over a caller-supplied `distance` callback. The ontology — which nodes, what geodesic distance,
what specificity — lives above prism in the DAG (ember and the personas), so it arrives as callbacks and
prism imports none of it. The algorithm and the kernel are here; the ontology stays where it belongs.
[[beam-law-single-sourced-decay]]
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Tuple

from . import law as _law


def screened_accumulate(
    sources: Iterable[Tuple[str, float]],       # (key, energy)
    targets: Iterable[Tuple[str, float]],       # (key, specificity_weight)
    *,
    distance: Callable[[str, str], float],      # (source_key, target_key) -> geodesic distance in nats, or inf
    xi: float,
    gap: float,
) -> Tuple[float, float]:
    """Accumulate the screened field of `sources` onto `targets`; return `(total_energy, nearest_distance)`.

    Each (source, target) pair contributes `energy * attenuate(distance, xi) * specificity`, counted when
    that weight clears the mass `gap`. A source whose |energy| is below the gap clears it at no distance,
    since the kernel is 1.0 at distance 0 and decays from there, so it is dropped up front. Sources are
    then accumulated strongest-first for a stable order, with the whole list kept. Distances that are
    non-finite or negative are skipped. No coefficient is chosen here: the kernel is `prism.law` and the
    gap is the caller's.
    """
    srcs = [(k, e) for k, e in sources if abs(e) >= gap]
    srcs.sort(key=lambda kv: -abs(kv[1]))
    tgts = list(targets)
    total, nearest = 0.0, math.inf
    for skey, energy in srcs:
        if not energy:
            continue
        for tkey, spec in tgts:
            d = float(distance(skey, tkey))
            if not math.isfinite(d) or d < 0.0:
                continue
            w = float(_law.attenuate(d, length=xi))
            if w < gap:                          # the gap — below it, nothing propagates
                continue
            if d < nearest:
                nearest = d
            total += float(energy) * w * float(spec)
    return total, nearest


def spread_graph(
    seeds: Iterable[Tuple[object, float]],       # (node, energy)
    neighbours: Callable[[object], Iterable[Tuple[object, float]]],   # node -> [(neighbour, edge_distance>=0)]
    *,
    kernel: Callable[[float], float],            # distance -> weight, e.g. prism.law.similarity
    reach: float = math.inf,                     # accumulated-distance horizon (past it, prune)
    max_steps: "int | None" = None,              # hop-count cap (None = unbounded depth)
) -> dict:
    """BFS-propagate a seeded field over a graph, applying `kernel` to the accumulated edge distance.

    The graph is the caller's ontology: `neighbours(node)` yields `(neighbour, edge_distance)` with
    `edge_distance >= 0`, so this module holds the field-spread algorithm while the graph stays above it in
    the DAG. Each seed contributes its raw energy at distance 0; every node reached accumulates
    `energy * kernel(accumulated_distance)`. A per-seed min-distance `seen` guard keeps each node at its
    nearest reach across branches, so a node already reached at least this near stays queued only once.
    Nodes past `reach` (accumulated distance) or `max_steps` hops are pruned. Returns
    `{node: accumulated_energy}`. Mirrors ember `activation.spread_seeds`' IS-A field exactly; the caller
    supplies `neighbours`, `kernel` and `reach`, and adds any signed lateral couplings itself.
    """
    fired: dict = {}
    for seed, energy in seeds:
        fired[seed] = fired.get(seed, 0.0) + energy
        seen = {seed: 0.0}
        queue = [(seed, 0.0, 0)]
        while queue:
            node, dist, steps = queue.pop(0)
            if max_steps is not None and steps >= max_steps:
                continue
            for nb, edge in neighbours(node):
                edge = float(edge)
                if not math.isfinite(edge) or edge < 0.0:
                    continue
                d = dist + edge
                if d > reach:
                    continue                     # past the horizon: cannot clear the mass gap
                if nb in seen and seen[nb] <= d:
                    continue
                seen[nb] = d
                fired[nb] = fired.get(nb, 0.0) + float(energy) * float(kernel(d))
                queue.append((nb, d, steps + 1))
    return fired
