"""Which bundle groups exist is discovered from payloads, and the sha gate is unaffected by that.

Which module fills a seam is the host's answer rather than the loader's, and the same holds for
which groups exist: `known_groups()` reads the bundle directory, so a host or a third party can
introduce a group without editing this package.

The two halves pull in opposite directions, and both are pinned here:

  * a group whose payload exists loads end to end, is called into, and leaves a side effect, with
    prism knowing nothing about it (`test_a_NEW_group_loads_end_to_end`);
  * a group whose payload is absent does not run, and neither does a payload whose bytes were
    tampered with, one that names a different group, or a name that is not spellable. Discovery
    widens who may supply a payload, and leaves what a payload must satisfy where it was.

The exec log is the control. Each synthetic bundle's module writes a file when it is exec'd. The
positive test asserts that file appears, proving the mechanism fires at all; the tamper test asserts
it is absent, proving the sha was checked before exec, which is the only point at which the check is
worth anything. Without the positive half, "the file is absent" would also be satisfied by a test
that never loaded anything.

Each test below states what would make it fail, so that a check which cannot fail is visible as one.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from prism import runner
from prism.crystal_model import bundle_canonical


# ── Synthetic bundles: built through the same canonicalization the runner verifies with ──────────
#
# Built here rather than copied from `agience-observe/bundles/`: a group prism has never seen is the
# thing under test, and a shipped payload would exercise the ones already known to load.

def _demo_source(group: str) -> str:
    return (
        "import os, pathlib\n"
        "pathlib.Path(os.environ['PRISM_DEMO_EXEC_LOG']).write_text('EXECUTED', encoding='utf-8')\n"
        "\n"
        "MARKER = %r\n"
        "\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def register_demo_operators(store=None):\n"
        "    return 1\n"
    ) % group


def _demo_bundle(group: str, *, entry: str = None) -> dict:
    entry = entry or group
    bundle = {
        "group": group,
        "entry_module": entry,
        "register_fns": ["register_demo_operators"],
        "host_seams": [],
        "modules": {entry: _demo_source(group)},
    }
    bundle["sha256"] = hashlib.sha256(bundle_canonical(bundle)).hexdigest()
    return bundle


def _write(bundle: dict, path: Path) -> Path:
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return path


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Copies of the runner's process-lifetime state, restored afterwards: the pin table, the host
    group map, the attached store, plus an exec-log path in the environment. Tests may register and
    load while leaving the rest of the session's pins and host bindings as they were."""
    monkeypatch.setattr(runner, "_loaded", dict(runner._loaded))
    monkeypatch.setattr(runner, "_HOST_GROUPS", dict(runner._HOST_GROUPS))
    monkeypatch.setattr(runner, "_attached_store", None)
    monkeypatch.setenv("PRISM_DEMO_EXEC_LOG", str(tmp_path / "exec.log"))
    return tmp_path


def _log(tmp_path: Path) -> Path:
    return tmp_path / "exec.log"


# ── discovery ────────────────────────────────────────────────────────────────────────────────────

def test_the_group_list_is_DISCOVERED_from_payloads_not_declared(isolated, monkeypatch):
    """`known_groups()` reads the bundle directory, and `GROUPS` is that reading.

    Fails if `GROUPS` becomes a tuple literal: the second half drops a payload into a fresh
    directory and expects it to appear.
    """
    real = runner.known_groups()
    assert set(real) >= {"arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"}, real
    assert runner.GROUPS == real, "GROUPS drifted from the measurement it is supposed to BE"

    monkeypatch.setattr(runner, "_DATA_DIR", isolated)
    assert runner.known_groups() == (), "a payload-free directory reported groups"
    _write(_demo_bundle("demo_seen"), isolated / "demo_seen.json")
    assert runner.known_groups() == ("demo_seen",)
    assert runner.GROUPS == ("demo_seen",)


def test_the_six_historical_groups_load_exactly_as_before():
    """The six shipped bundles verify, load, and resolve their manifest-declared register fns.

    Fails on any regression in `_load_group`, `_verify_sha` or `_verify_group` — for instance a
    payload whose `group` field disagrees with its filename.

    Runs against the process's real pins rather than the `isolated` fixture, so what it asserts is
    what a node actually runs.
    """
    for group in ("arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"):
        shipped = json.loads((runner._DATA_DIR / (group + ".json")).read_text(encoding="utf-8"))
        entry = runner.load(group)
        assert entry.__name__.endswith("." + shipped["entry_module"])
        assert runner.loaded()[group]["sha256"] == shipped["sha256"]
        assert runner.loaded()[group]["origin"] == "shipped"
        assert all(callable(f) for f in runner.register_fns(group))


# ── a new group, end to end ──────────────────────────────────────────────────────────────────────

def test_a_NEW_group_loads_end_to_end(isolated):
    """A group prism has never heard of is built, loaded and called into, with no edit to prism.

    Fails if the loader rejects an unrecognised group name, if the payload is found but not exec'd
    (the log file), or if `register_fns` stops reading the bundle's own manifest.
    """
    path = _write(_demo_bundle("demo_new"), isolated / "demo_new.json")
    runner.register_group("demo_new", path)
    assert runner.registered_groups()["demo_new"] == str(path.resolve())

    mod = runner.load("demo_new")
    assert mod.MARKER == "demo_new"
    assert mod.add(2, 3) == 5, "the loaded bundle's code does not actually run"
    assert [f.__name__ for f in runner.register_fns("demo_new")] == ["register_demo_operators"]
    assert runner.register_fns("demo_new")[0]() == 1

    info = runner.loaded()["demo_new"]
    assert info["sha256"] == json.loads(path.read_text(encoding="utf-8"))["sha256"]
    assert info["origin"] == "host", "a host-registered payload reported as 'shipped'"
    assert _log(isolated).read_text(encoding="utf-8") == "EXECUTED", (
        "the exec log did not fire — the tamper test below would then prove nothing")


def test_a_host_registered_payload_OUTRANKS_the_shipped_one(isolated):
    """`register_group` is the host's answer, and it beats the ambient sibling checkout — the same
    precedence `register_seam` has over anything on `sys.path`.

    Fails if the shipped directory is consulted first: `fetch` would then resolve to chorus's real
    organon and both assertions below would miss.
    """
    path = _write(_demo_bundle("fetch"), isolated / "fetch.json")
    runner.register_group("fetch", path)
    runner._loaded.pop("fetch", None)
    mod = runner.load("fetch")
    assert mod.MARKER == "fetch" and mod.add(1, 1) == 2
    assert runner.loaded()["fetch"]["origin"] == "host"


# ── The four payloads that do not run ────────────────────────────────────────────────────────────

def test_a_TAMPERED_bundle_in_a_NEW_group_is_REFUSED_before_exec(isolated):
    """A payload reached through the host route is sha-checked before it is exec'd.

    The tamper is a semantic no-op — two spaces inside the source text — so the only thing wrong
    with this payload is that it is not the payload that was hashed. A tamper that also broke the
    code would fail for the wrong reason and leave the sha gate untested.

    Fails if `_verify_sha` is skipped for host-registered files or softened to a warning: the load
    succeeds and the exec log appears.
    """
    good = _demo_bundle("demo_tampered")
    bad = json.loads(json.dumps(good))
    bad["modules"]["demo_tampered"] = bad["modules"]["demo_tampered"].replace(
        "def add(a, b)", "def add(a,  b)", 1)
    assert bad["modules"] != good["modules"], "the tamper did not change anything"
    assert bad["sha256"] == good["sha256"], "the tamper must leave the CLAIMED sha in place"

    path = _write(bad, isolated / "demo_tampered.json")
    runner.register_group("demo_tampered", path)
    with pytest.raises(runner.BundleIntegrityError, match="REFUSING to exec"):
        runner.load("demo_tampered")
    assert not _log(isolated).exists(), "the payload was EXEC'D before the hash was checked"
    assert "demo_tampered" not in runner.loaded(), "a refused bundle was pinned anyway"


# A group name that stands for "nothing carries this". `op_pay_session` is an organon that
# `ophan/server.py` names and does not implement — two Stripe tools point at it — so the name is
# meaningful rather than arbitrary. The day it is built, this test fails, which is the right signal:
# the name needs replacing, and the test below needs leaving alone.
_NEVER_BUILT = "op_pay_session"


def test_the_unknown_group_example_is_STILL_unknown():
    """The precondition for the test below, kept separate so the two failures read differently.

    If `_NEVER_BUILT` is built, the test below starts failing for a reason unrelated to what it
    pins. This one line says so, so that the next reader replaces the name rather than the
    assertion.
    """
    assert _NEVER_BUILT not in runner.known_groups(), (
        "%r now has a payload, so it can no longer stand for 'a group nothing carries'. Pick another "
        "unbuilt name here; do NOT weaken the refusal test below." % _NEVER_BUILT)


def test_an_UNKNOWN_group_is_REFUSED_loudly(isolated):
    """A name nothing carries fails at `load`, names itself, and says where it looked.

    Resolution stops there rather than falling through to an empty namespace or to something on
    `sys.path`, so the failure arrives at the load and names the group.

    Fails if the group check is dropped: `load(...)` then resolves elsewhere and surfaces later, in
    other code.
    """
    with pytest.raises(runner.UnknownBundleGroupError) as e:
        runner.load(_NEVER_BUILT)
    msg = str(e.value)
    assert _NEVER_BUILT in msg and "bundle_spec.json" in msg and "register_group" in msg, msg
    assert isinstance(e.value, runner.BundleIntegrityError), (
        "an absent payload must stay inside the refuse-to-run family — every caller that already "
        "refuses on a bad bundle must refuse on a missing one")
    assert _NEVER_BUILT not in runner.loaded()
    with pytest.raises(AttributeError):
        getattr(runner, _NEVER_BUILT)                    # the attribute door answers the same way


def test_a_payload_that_NAMES_A_DIFFERENT_GROUP_is_refused(isolated):
    """The payload's own `group` field must agree with the name it was loaded under.

    A sha shows a payload is internally consistent. It says nothing about which name that payload
    belongs to, because the name arrives from outside — a filename, an artifact id, a host's
    argument — so `_verify_group` checks that binding on its own.

    Fails without `_verify_group`: the `demo_a` payload runs as group `demo_b`, sha-valid the whole
    way.
    """
    path = _write(_demo_bundle("demo_a"), isolated / "demo_b.json")   # says demo_a, filed as demo_b
    runner.register_group("demo_b", path)
    with pytest.raises(runner.BundleIntegrityError, match="was not hashed under"):
        runner.load("demo_b")
    assert not _log(isolated).exists(), "the substituted payload was exec'd"


def test_an_UNSPELLABLE_group_name_is_refused(isolated):
    """A group name becomes both a filename and a module name, so it has to be an identifier.

    The rule is derived from those two uses. It is checked before anything touches the filesystem,
    because `../evil` would otherwise reach `_DATA_DIR / (group + '.json')`.

    Fails without the check: a name that escapes the bundle directory is a path traversal, and one
    containing a `-` produces a package name no import statement can spell.
    """
    for bad in ("../evil", "a-b", "", "demo group", "9lives"):
        with pytest.raises(runner.UnknownBundleGroupError, match="not a usable name"):
            runner.load(bad)


def test_register_group_refuses_a_path_that_is_not_there_AT_REGISTRATION(isolated):
    """A boot-time mistake is heard at boot. `register_group` runs before the first load, and checks
    the path then, so a typo is reported against the host that registered it.

    Fails if the check is deferred: the traceback points at whichever code first touched the group,
    rather than at the mis-registration.
    """
    with pytest.raises(FileNotFoundError, match="no such bundle payload file"):
        runner.register_group("demo_missing", isolated / "not_written.json")
    assert "demo_missing" not in runner.registered_groups()
    assert "demo_missing" not in runner.known_groups()

    with pytest.raises(runner.UnknownBundleGroupError, match="not a usable name"):
        runner.register_group("../evil", _write(_demo_bundle("x"), isolated / "x.json"))


def test_the_registered_map_cannot_be_mutated_through_the_report(isolated):
    """`registered_groups()` hands out a copy, matching `registered_seams()`.

    Fails if the live dict is returned: a caller could then bind a group by mutating a status
    report.
    """
    path = _write(_demo_bundle("demo_copy"), isolated / "demo_copy.json")
    runner.register_group("demo_copy", path)
    report = runner.registered_groups()
    report["demo_injected"] = str(path)
    assert "demo_injected" not in runner.registered_groups()
