"""The screened-propagator accumulation primitive — invariants, kernel-side (no ontology)."""
import math

from prism import propagation as prop
from prism import law


def _naive(sources, targets, dist, xi, gap):
    """Independent reference: the same accumulation written straight, to check the primitive."""
    total, nearest = 0.0, math.inf
    for sk, e in sources:
        if abs(e) < gap:
            continue
        for tk, spec in targets:
            d = dist(sk, tk)
            if not math.isfinite(d) or d < 0:
                continue
            w = law.attenuate(d, length=xi)
            if w < gap:
                continue
            nearest = min(nearest, d)
            total += e * w * spec
    return total, nearest


def test_matches_an_independent_reference_over_seeds():
    for seed in range(60):
        r = (seed * 2654435761) & 0xFFFFFFFF
        srcs = [(f"s{i}", ((r >> (i * 3)) % 20) / 10.0 - 0.5) for i in range(5)]
        tgts = [(f"t{j}", 1.0 + ((r >> (j * 5)) % 10) / 10.0) for j in range(4)]
        dmap = {(sk, tk): ((r >> (i + j)) % 30) / 10.0 for i, (sk, _) in enumerate(srcs)
                for j, (tk, _) in enumerate(tgts)}
        def dist(sk, tk):
            return dmap[(sk, tk)]
        got = prop.screened_accumulate(srcs, tgts, distance=dist, xi=0.42, gap=0.05)
        exp = _naive(srcs, tgts, dist, 0.42, 0.05)
        assert math.isclose(got[0], exp[0], rel_tol=1e-12, abs_tol=1e-12), (seed, got, exp)
        assert got[1] == exp[1], (seed, got, exp)


def test_gap_drops_weak_sources_and_far_targets():
    # a source below the gap in |energy| contributes nothing at any distance
    got, near = prop.screened_accumulate([("weak", 0.01)], [("t", 1.0)],
                                         distance=lambda a, b: 0.0, xi=1.0, gap=0.05)
    assert got == 0.0 and near == math.inf
    # a target whose kernel weight is below the gap does not propagate
    got, near = prop.screened_accumulate([("s", 1.0)], [("far", 1.0)],
                                         distance=lambda a, b: 100.0, xi=1.0, gap=0.05)
    assert got == 0.0 and near == math.inf


def test_identical_point_gives_full_kernel_times_energy_times_spec():
    got, near = prop.screened_accumulate([("s", 2.0)], [("t", 3.0)],
                                         distance=lambda a, b: 0.0, xi=1.0, gap=0.05)
    assert math.isclose(got, 2.0 * 1.0 * 3.0)   # attenuate(0)=1
    assert near == 0.0


def test_nonfinite_or_negative_distance_is_skipped():
    got, near = prop.screened_accumulate([("s", 1.0)], [("a", 1.0), ("b", 1.0)],
                                         distance=lambda a, b: math.inf if b == "a" else -1.0,
                                         xi=1.0, gap=0.05)
    assert got == 0.0 and near == math.inf


# ── spread_graph ─────────────────────────────────────────────────────────────

# a small DAG: child -> [(parent, edge_distance)]
_G = {"dog": [("canine", 0.5), ("pet", 1.2)], "canine": [("carnivore", 0.4)],
      "carnivore": [("animal", 0.6)], "pet": [("animal", 0.9)], "animal": []}


def _neigh(n):
    return _G.get(n, [])


def _naive_spread(seeds, neigh, kernel, reach, max_steps):
    fired = {}
    for seed, energy in seeds:
        fired[seed] = fired.get(seed, 0.0) + energy
        seen = {seed: 0.0}
        q = [(seed, 0.0, 0)]
        while q:
            node, dist, steps = q.pop(0)
            if max_steps is not None and steps >= max_steps:
                continue
            for nb, edge in neigh(node):
                if edge < 0:
                    continue
                d = dist + edge
                if d > reach:
                    continue
                if nb in seen and seen[nb] <= d:
                    continue
                seen[nb] = d
                fired[nb] = fired.get(nb, 0.0) + energy * kernel(d)
                q.append((nb, d, steps + 1))
    return fired


def test_spread_graph_matches_reference():
    for reach, ms in [(math.inf, None), (1.5, None), (math.inf, 1), (2.0, 2)]:
        seeds = [("dog", 1.0), ("pet", 0.3)]
        got = prop.spread_graph(seeds, _neigh, kernel=law.similarity, reach=reach, max_steps=ms)
        exp = _naive_spread(seeds, _neigh, law.similarity, reach, ms)
        assert set(got) == set(exp), (reach, ms, got, exp)
        for k in exp:
            assert math.isclose(got[k], exp[k], rel_tol=1e-12, abs_tol=1e-12), (k, reach, ms)


def test_spread_graph_seed_is_raw_energy_and_accumulates_each_nondominated_visit():
    got = prop.spread_graph([("dog", 1.0)], _neigh, kernel=law.similarity)
    assert got["dog"] == 1.0                                  # seed raw, distance 0
    # animal is reachable via pet (1.2+0.9=2.1, two hops) and via canine->carnivore (0.5+0.4+0.6=1.5,
    # three hops). FIFO-BFS processes the 2-hop path first (fires at d=2.1), then the nearer 3-hop path
    # (d=1.5 < 2.1, so the seen-guard does not skip it) fires again, so animal accumulates both.
    # This matches ember's `activation.spread_seeds`: every non-dominated visit fires and accumulates
    # rather than only the nearest one, and this test pins that parity.
    assert math.isclose(got["animal"], law.similarity(2.1) + law.similarity(1.5))


def test_spread_graph_reach_horizon_prunes():
    near = prop.spread_graph([("dog", 1.0)], _neigh, kernel=law.similarity, reach=0.6)
    assert "canine" in near and "animal" not in near         # animal (d=1.5) is past the horizon
