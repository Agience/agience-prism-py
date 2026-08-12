"""The read default: a second registry slot, independent of the embodiment slot.

`set_default`/`get_default`/`resolve` (the embodiment slot) exist for the wire's two straddle
points and nothing else, by the module's own long-standing statement. `set_default_read` and
friends are the analogous slot for the `Read` contract — the spectral structure read a constrained
store (e.g. mantle's beacon) and a full node (`ember.optics`) can each legitimately fill their own
way. This file pins that the two slots never leak into each other and that the resolution order
(explicit instrument, then default, then refusal) holds for the read slot exactly as it does for
the embodiment slot.
"""
from __future__ import annotations

import pytest

from prism import instrument


class _FakeRead:
    """Fills only `read_ordered` — enough to exercise resolution without a real embodiment."""

    def read_ordered(self, rows):
        return "read:" + repr(rows)


@pytest.fixture(autouse=True)
def _clean_slots():
    """Both slots start and end empty, so one test's registration cannot leak into the next."""
    instrument.clear_default()
    instrument.clear_default_read()
    yield
    instrument.clear_default()
    instrument.clear_default_read()


def test_read_slot_starts_empty():
    assert instrument.get_default_read() is None


def test_set_and_get_default_read():
    fake = _FakeRead()
    instrument.set_default_read(instance := fake)
    assert instrument.get_default_read() is instance


def test_factory_is_lazy_and_resolved_once():
    calls = []

    def factory():
        calls.append(1)
        return _FakeRead()

    instrument.set_default_read(factory=factory)
    assert calls == [], "the factory ran before anything asked for the default"
    first = instrument.get_default_read()
    second = instrument.get_default_read()
    assert first is second
    assert calls == [1], "the factory ran more than once"


def test_set_default_read_rejects_both_instance_and_factory():
    with pytest.raises(ValueError):
        instrument.set_default_read(_FakeRead(), factory=lambda: _FakeRead())


def test_clear_default_read_empties_the_slot():
    instrument.set_default_read(_FakeRead())
    instrument.clear_default_read()
    assert instrument.get_default_read() is None


def test_resolve_read_prefers_the_explicit_instrument_over_the_default():
    instrument.set_default_read(_FakeRead())
    explicit = _FakeRead()
    fn = instrument.resolve_read(explicit, "read_ordered", at="test")
    assert fn.__self__ is explicit


def test_resolve_read_falls_back_to_the_default():
    default = _FakeRead()
    instrument.set_default_read(default)
    fn = instrument.resolve_read(None, "read_ordered", at="test")
    assert fn.__self__ is default


def test_resolve_read_refuses_when_nothing_is_registered():
    with pytest.raises(instrument.InstrumentRequired) as exc:
        instrument.resolve_read(None, "read_ordered", at="test_op")
    assert exc.value.contract == "read"
    assert exc.value.member == "read_ordered"
    assert exc.value.at == "test_op"


def test_resolve_read_names_the_missing_member_on_a_partial_embodiment():
    """A `Read` embodiment that fills one member and not another refuses by name, not by
    `AttributeError` — the same per-member check `require()` gives the embodiment slot."""
    instrument.set_default_read(_FakeRead())
    with pytest.raises(instrument.InstrumentRequired) as exc:
        instrument.resolve_read(None, "resolvable", at="test_op")
    assert exc.value.member == "resolvable"


def test_the_read_slot_is_independent_of_the_embodiment_slot():
    """Filling one slot must not be observable through the other — they are two registries, not
    one meaning read two ways."""
    instrument.set_default_read(_FakeRead())
    assert instrument.get_default() is None

    instrument.clear_default_read()
    instrument.set_default(_FakeRead())
    assert instrument.get_default_read() is None
