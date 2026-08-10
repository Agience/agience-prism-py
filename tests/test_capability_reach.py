"""The prism junction measures reach instead of testing membership.

The load-bearing test here is `test_a_family_near_miss_does_not_satisfy_the_gate`: measuring reach
does not widen what may activate. Until discharge is authorized by a grant on the energy (NEXT.md
§Q), a near miss is information, not permission.
"""
from prism.crystal_model import activates_on, capability_reach, required_capabilities


def _crystal(*requires):
    return {"name": "c", "organons": [{"name": "o", "requires": list(requires)}]}


# ── measurement ───────────────────────────────────────────────────────────────

def test_exact_match_is_zero_hops():
    [m] = capability_reach(["net.get"], ["net.get", "fs.read"])
    assert m == {"required": "net.get", "matched": "net.get", "basis": "exact", "hops": 0}


def test_a_family_neighbour_is_reported_at_one_hop():
    """The crystal wants a thermometer; the prism affords a camera. Both are `sensor.*`, so a
    non-match can name what is nearby instead of only a missing string."""
    [m] = capability_reach(["sensor.temperature"], ["sensor.capture", "fs.read"])
    assert m["basis"] == "family"
    assert m["matched"] == "sensor.capture"
    assert m["hops"] == 1


def test_out_of_family_is_out_of_reach():
    [m] = capability_reach(["sensor.temperature"], ["fs.read", "net.get"])
    assert m["basis"] is None and m["matched"] is None and m["hops"] is None


def test_base_kinds_have_no_family_so_a_near_miss_is_unreachable():
    """`net.get` and `net.request` are NOT an open family — only sensor.*/actuator.* are."""
    [m] = capability_reach(["net.request"], ["net.get"])
    assert m["basis"] is None


def test_a_bare_family_prefix_is_not_a_member():
    assert capability_reach(["sensor."], ["sensor.capture"])[0]["basis"] is None
    assert capability_reach(["sensor.capture"], ["sensor."])[0]["basis"] is None


def test_one_entry_per_requirement_in_order():
    got = capability_reach(["fs.read", "sensor.temperature", "nope.x"], ["fs.read", "sensor.capture"])
    assert [m["basis"] for m in got] == ["exact", "family", None]


# ── the gate is unchanged ──────────────────────────────────────────────────────

def test_a_family_near_miss_does_not_satisfy_the_gate():
    """Reach is measured and reported, but permission is unchanged: a prism affording
    `sensor.capture` does not activate a crystal requiring `sensor.temperature`. Loosening the
    match before discharge is grant-authorized would widen the permission surface."""
    c = _crystal("sensor.temperature")
    assert capability_reach(required_capabilities(c), ["sensor.capture"])[0]["basis"] == "family"
    assert not activates_on(c, ["sensor.capture"])          # measured as near — still does not activate


def test_gate_still_requires_every_capability_exactly():
    c = _crystal("compute.local", "store.read")
    assert activates_on(c, ["compute.local", "store.read"])
    assert activates_on(c, ["compute.local", "store.read", "extra"])   # superset is fine
    assert not activates_on(c, ["store.read"])                          # missing one
    assert activates_on(_crystal(), [])                                 # requires nothing
