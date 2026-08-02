"""The pattern RUNNER — a HOST executes operator code through THE ONE DISTRIBUTION PATH.

2026-07-23, John's directive: "No dual path. Single path only." The operator implementations'
authoritative home is chorus; no host holds code copies. Chorus publishes each register group as a
SOURCE BUNDLE — the impl module plus its impl-internal deps, with a manifest
{group, entry_module, register_fns, host_seams, modules, sha256} — and this module loads a bundle,
VERIFIES it, and execs it into an isolated namespace. Everything a host used to import from mirror
modules (arithmetic, operators, describe, dev_ops, docs_ops, corpus, fetch, evolution, category,
code_index, doc_index) is reached through here:

    from prism.runner import arithmetic            # the loaded bundle's entry module
    from prism.runner import evolution             # a shared dep, from its canonical bundle

⚠ MOVED HERE FROM `ember/runtime/runner.py` — 2026-08-02, the chorus→ember DAG work. Behaviour
unchanged apart from host seams becoming injected (see `_HOST_SEAMS`). It reads as ember's because it
was ember's, and that was the defect: **chorus was importing the RUNNER to load bundles whose
authoritative source is chorus itself.** A round trip out of the repo that authors the code and back,
purely to reach a loader.

Why prism, specifically:
  * The loader's dependencies were already prism's — `prism.canonical` for the canonical form,
    `prism.crystal_model.bundle_canonical` for the bundle's own canonicalization, `prism.mass` for the
    provenance ladder, and `prism.trust.opsign` for signatures. Nothing but the one hardcoded host seam
    tied it to ember.
  * prism is a PURE LEAF, so both the runner (ember) and the personas (chorus) reach it downward. There
    is no other home below both: mantle is beam's sibling and beam is the signal.
  * A BUNDLE is *"a named Prism + Crystals + Ember — the installable"* (see `_data_dir()`), and prism's
    CLI already verifies bundle shas on `install`. Verifying and grounding a bundle is prism's story;
    executing one is the same story's last step.

This module executes verified code, so it is NOT part of prism's zero-dependency base contract in
spirit — but it adds no hard dependency either: everything above is stdlib or prism-internal, and
`opsign` (the only `cryptography` reach) is imported lazily, inside the env-gated trust leg.

CONTENT ADDRESSING IS THE INTEGRITY GATE. A bundle's sha256 is computed over the canonical
JSON payload of everything except the sha itself (build_bundles.canonical, reproduced in
`_canonical` below — same keys, ordering, separators). Before ANY exec the hash is recomputed
and compared; a mismatch raises `BundleIntegrityError` loudly. There is no unverified path.

WHERE BUNDLES COME FROM (in order):
  1. The local store: artifact `bundle-<group>` with content_type
     `application/vnd.agience.bundle+json`, its `content` the bundle JSON. This is the mesh
     path — bundles travel as artifacts like everything else. sha-verified + provenance-checked.
  2. The SHIPPED DATA files `agience-bundle/bundles/<group>.json` — built there from chorus
     `definitions/bundles/`. A data mirror of content-addressed SIGNED CONTENT is distribution,
     not a code fork: the same bytes, the same sha, that the mesh will later carry. It exists so
     an offline node bootstraps with no chorus checkout and no store bundle present. sha-verified
     against its own manifest. ⛔ These files used to live at `ember/bundles/` and were MOVED OUT
     2026-07-30 — a BUNDLE is the installable (Prism + Crystals + Ember), so the payloads are the
     bundle repo's, and ember is the runner that loads and verifies them. See `_data_dir()`.

VERSION-PINNED PER PROCESS: the first successful load of a group pins that bundle for the
process lifetime (the same rule as genesis.invoke's `_pinned` — one logical runtime runs ONE
version of an operator throughout; a restart picks up newer bundles). `attach(store)` at boot,
BEFORE the first load, is what lets store bundles take precedence over shipped ones.

TRUST GATE (flagged seam — `verify_provenance`): sha-verification is the INTEGRITY leg and is
always enforced. The signature/rung leg — the Higgs rule: provenance is the field that splits
message from event, and an executable pattern must carry a verified signature + authority rung
before exec — is IMPLEMENTED but env-gated, staged for the cutover:

  * `EMBER_REQUIRE_SIGNED` unset (the default): behavior is exactly the pre-gate honest
    default — the sha check plus a `created_by`-resolvable check against the store (an
    executable artifact with no resolvable author is refused) — plus one breadcrumb log line
    at import saying the gate is OFF. Nothing else changes.
  * `EMBER_REQUIRE_SIGNED=1`: a STORE-sourced bundle must additionally carry a valid Ed25519
    signature (`opsign.sign_bundle` envelope: `signature`/`signed_by` over the same canonical
    payload the sha covers), the signing key must be ATTESTED by the store-resolved author
    artifact (an embedded key alone proves self-consistency, not authorship — opsign's own
    caveat), and the author's provenance rung (`prism.mass.provenance_of`) must meet the floor:
    `EMBER_MIN_BUNDLE_RUNG` (a rung name on `prism.mass.CLAIM_LADDER`) when set, else the
    DERIVED default — the rung must weigh above `prism.mass.GHOST_FLOOR`, the vocabulary's one
    existing trust floor ("at/below this, mass is not real"). No invented number: the default
    excludes exactly the ghost rungs; set `EMBER_MIN_BUNDLE_RUNG` to tighten. Failure raises
    `BundleTrustError` — refuse to ground, never warn-and-run.

Shipped data files ride package-install trust (they are part of the installed distribution) and skip
the store-provenance leg only — under either gate state.

HOST SEAMS: a bundle DECLARES the host modules it may reach for (`host_seams`, e.g. the
`operators` group's optional geometric matcher `match`). The mapping from seam name to the module
that fills it is REGISTERED BY THE HOST (`register_seam`); an unfilled seam leaves the bundle's own honest fallback
in charge (operators.select_for answers basis="generic"). Seams are store/host machinery —
never operator code.

MODULE SHARING BY CONTENT: bundle modules with no intra-bundle (relative) imports — answer,
evolution, category, code_index, doc_index, content — are cached by sha256(source) and SHARED
across bundles, so `evolution` is one module object and `Answer` one class process-wide
whenever the distributed bytes are identical. Identity follows content, exactly like the store.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Optional
from prism.canonical import canonical_string as _jcs_string

log = logging.getLogger(__name__)

BUNDLE_CONTENT_TYPE = "application/vnd.agience.bundle+json"
BUNDLE_ARTIFACT_PREFIX = "bundle-"

def _data_dir() -> Optional[Path]:
    """Where the SHIPPED bundle files live — in `agience-bundle`, never inside a host package.

    ⛔ THEY USED TO SIT AT `ember/src/ember/bundles/*.json` AND THEY DO NOT BELONG THERE
    (John, 2026-07-30: *"it's a BUNDLE feature so I moved it into agience-bundle"*). A BUNDLE is a
    named Prism + Crystals + Ember — the installable — so the bundle payloads are the bundle repo's
    concern. Ember is the RUNNER: it loads and verifies them, it does not ship them. Six tracked
    JSON files living under `src/ember/` made the runner look like their owner and made ember's
    package carry a copy of content that the mesh distributes.

    RESOLUTION ORDER, and every step is explicit rather than guessed:
      1. `$AGIENCE_BUNDLE_ROOT` — what a deployment sets. Points at the directory holding
         `<group>.json`, or at the `agience-bundle` checkout containing `bundles/`.
      2. The sibling `agience-bundle/bundles/` next to this checkout — the developer case.
      3. None. There is NO in-package fallback, deliberately: a silent fallback to a stale embedded
         copy is exactly how two versions of a content-addressed payload start to disagree, and the
         sha gate would then be verifying the wrong bytes faithfully.

    Returning None is not an error here — the STORE is the primary source (path 1 in the module
    docstring) and a node with its bundles in the lattice needs no files at all. `_load_shipped`
    reports the absence when it is actually reached.
    """
    raw = os.getenv("AGIENCE_BUNDLE_ROOT", "").strip()
    candidates = []
    if raw:
        p = Path(raw).expanduser()
        candidates += [p, p / "bundles"]
    # …/agience-genesis/agience-prism/py/src/prism/runner.py -> …/agience-genesis/agience-bundle
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "agience-bundle" / "bundles")
    for c in candidates:
        try:
            if c.is_dir():
                return c.resolve()
        except OSError:
            continue
    return None


_DATA_DIR = _data_dir()

GROUPS = ("arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch")

# shared impl-internal deps -> the canonical bundle that carries them (identical bytes in every
# bundle that includes them — the by-content module cache makes the choice immaterial).
_SHARED = {"evolution": "arithmetic", "answer": "arithmetic", "category": "arithmetic",
           "describe": "operators", "code_index": "operators", "doc_index": "operators"}

# seam name (as declared by a bundle's manifest) -> the dotted module path that FILLS it.
#
# ⚠ INJECTED, NOT HARDCODED — 2026-08-02. This read `{"match": "ember.ontology.match"}`, and that one
# line was what made the whole loader ember's. A host seam is by definition the HOST's to fill: the
# loader's job is to resolve the name a bundle's manifest declares, not to know which host is running.
# While the mapping was hardcoded, prism could not carry this module without importing the runner it
# sits below, and chorus could not reach the loader at all except through ember.
#
# Registration is idempotent, last-writer-wins per name. A host registers its seams at boot, BEFORE the
# first load — the same ordering rule `attach(store)` already follows. A bundle declaring a seam nobody
# registered simply does not resolve it: the manifest says what it needs, and the host either supplies
# it or does not.
_HOST_SEAMS: Dict[str, str] = {}


def register_seam(name: str, target: str) -> None:
    """Declare that host-seam `name` (as a bundle manifest spells it) is filled by dotted module
    `target`. Call at boot, before the first `load()`."""
    _HOST_SEAMS[str(name)] = str(target)


def registered_seams() -> Dict[str, str]:
    """The seams this host has registered — a copy, so a caller cannot mutate the live map."""
    return dict(_HOST_SEAMS)


class BundleIntegrityError(RuntimeError):
    """A bundle whose content does not hash to its ref, or whose provenance fails the gate.
    NEVER caught-and-continued into an exec: refusing to run unverified code is the point."""


class BundleTrustError(BundleIntegrityError):
    """The signature/rung leg refused a bundle (gate ON): unsigned, key not attested by the
    author artifact, forged, or the signer's rung is below the floor. A subclass so every
    existing refuse-path stays a refuse-path; a distinct name so 'tampered bytes' and
    'untrusted author' are never conflated in a traceback."""


_lock = threading.RLock()
_attached_store = None          # set by attach(); consulted at FIRST load of each group
_loaded: dict = {}              # group -> {"bundle","pkg","entry","origin","sha256"}
_by_content: dict = {}          # sha256(module source) -> module object (rel-import-free only)


def attach(store) -> None:
    """Bind the local store the runner consults for bundle artifacts. Call at boot, before the
    first load — a group already loaded stays pinned to what it loaded (process-lifetime pin)."""
    global _attached_store
    _attached_store = store


def _canonical(bundle: dict) -> bytes:
    """The bytes a bundle's sha is taken over — from the CONTRACT, not reproduced here.

    ⚠ THIS USED TO RESTATE THE FIELD LIST. Its own docstring said it was "build_bundles.canonical,
    reproduced exactly … or verification means nothing" — and `build_bundles.py` no longer exists,
    so it was a reproduction with no original to be checked against. The definition now lives in
    `prism.crystal_model.BUNDLE_SHA_FIELDS`, beside `crystal_sha`, where a publisher can find it."""
    from prism.crystal_model import bundle_canonical
    return bundle_canonical(bundle)


def _verify_sha(bundle: dict, *, where: str) -> str:
    try:
        actual = hashlib.sha256(_canonical(bundle)).hexdigest()
    except (KeyError, TypeError) as e:
        raise BundleIntegrityError("malformed bundle (%s): %s" % (where, e))
    claimed = bundle.get("sha256")
    if actual != claimed:
        raise BundleIntegrityError(
            "bundle %r (%s): content hashes to %s but manifest claims %s — REFUSING to exec"
            % (bundle.get("group"), where, actual, claimed))
    return actual


def _gate_enabled() -> bool:
    """Is the signature/rung leg ON? Read at call time so a test/process can flip it without a
    reimport. A SET-but-falsey value ('0', 'false', …) is off; any other set value is ON — an
    operator who set the variable never gets a silently-disabled gate out of a spelling."""
    v = (os.environ.get("EMBER_REQUIRE_SIGNED") or "").strip().lower()
    return v not in ("", "0", "false", "no", "off")


def _attested_signer_key(creator: dict) -> str:
    """The signing public key the AUTHOR ARTIFACT itself attests (hex), or '' when it attests
    none. Read from `signed_by`/`public_key` at top level or inside `context` (dict or JSON
    string — the same tolerance `prism.mass.provenance_of` extends to `context.provenance`).
    This is what turns opsign's 'verified against the embedded key proves only
    self-consistency' caveat into an authorship check: the key comes from the store-resolved
    author, not from the bundle that is asking to be trusted."""
    holders = [creator]
    ctx = creator.get("context")
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = None
    if isinstance(ctx, dict):
        holders.append(ctx)
    for holder in holders:
        for field in ("signed_by", "public_key"):
            v = holder.get(field)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return ""


def _check_signer_rung(rung, *, bundle_id, creator_id) -> None:
    """The rung leg: the author's provenance rung must meet the floor.

    `EMBER_MIN_BUNDLE_RUNG` set: a rung NAME on `prism.mass.CLAIM_LADDER`; the signer's rung
    must sit at/above it on the ladder. An unrecognized name REFUSES — mass.py's read path
    maps a typo to UNKNOWN because failing closed there means under-crediting; here the same
    fallback would mean silently WEAKENING an execution gate, so the fail-closed direction
    inverts.

    Unset: the DERIVED default — the rung must weigh strictly above `prism.mass.GHOST_FLOOR`
    ("at/below this, mass is not real"), the rung vocabulary's one existing trust floor. No
    invented number: today this excludes exactly ASSERTION, computed from the ladder, not
    hardcoded. Off-ladder rungs (ontology_proposal) answer a different question than "why
    believe this author" and are refused under either branch."""
    from prism.mass import CLAIM_LADDER, GHOST_FLOOR, Provenance, weigh

    min_name = (os.environ.get("EMBER_MIN_BUNDLE_RUNG") or "").strip().lower()
    if min_name:
        try:
            want = Provenance(min_name)
        except ValueError:
            want = None
        if want is None or want not in CLAIM_LADDER:
            raise BundleTrustError(
                "EMBER_MIN_BUNDLE_RUNG=%r is not a rung on prism.mass.CLAIM_LADDER (%s) — "
                "refusing to ground %r: a mis-set floor may not weaken the gate"
                % (min_name, ", ".join(r.value for r in CLAIM_LADDER), bundle_id))
        if rung not in CLAIM_LADDER or CLAIM_LADDER.index(rung) > CLAIM_LADDER.index(want):
            raise BundleTrustError(
                "store bundle %r: signer %r is on rung %r, below the required %r "
                "(EMBER_MIN_BUNDLE_RUNG) — refusing to ground"
                % (bundle_id, creator_id, rung.value, want.value))
        return
    if rung not in CLAIM_LADDER or weigh(rung).mass <= GHOST_FLOOR:
        raise BundleTrustError(
            "store bundle %r: signer %r rung %r weighs at/below prism.mass.GHOST_FLOOR — a "
            "ghost may not author executable patterns (derived default floor; set "
            "EMBER_MIN_BUNDLE_RUNG to a prism.mass.CLAIM_LADDER rung name to tighten)"
            % (bundle_id, creator_id, getattr(rung, "value", rung)))


def verify_provenance(doc: dict, bundle: dict, store) -> None:
    """TRUST GATE (see module header). Runs for STORE-sourced bundles, after the sha check.

    Always: the bundle artifact must name a `created_by` that RESOLVES in the store — an
    executable pattern with no resolvable author is refused (provenance needs authority).

    When `EMBER_REQUIRE_SIGNED` is on, the signature/rung leg (the Higgs rule) additionally
    requires: a valid `opsign.sign_bundle` envelope, the signing key attested by the resolved
    author artifact, and the author's rung at/above the floor (`_check_signer_rung`).

    Raise to refuse; never soften to a warning."""
    creator = (doc.get("created_by") or "").strip()
    if not creator:
        raise BundleIntegrityError(
            "store bundle %r carries no created_by — an executable pattern with no author "
            "is refused (provenance needs authority)" % doc.get("id"))
    arts = getattr(store, "artifacts", store)
    try:
        resolved = arts.get_artifact(creator)
    except Exception as e:
        raise BundleIntegrityError(
            "store bundle %r: created_by %r could not be checked (%s: %s)"
            % (doc.get("id"), creator, type(e).__name__, e))
    if resolved is None:
        raise BundleIntegrityError(
            "store bundle %r: created_by %r does not resolve in this store — refused"
            % (doc.get("id"), creator))

    if not _gate_enabled():
        return                          # gate OFF: byte-identical to the pre-gate default

    from prism.trust import opsign
    from prism.mass import provenance_of

    if not bundle.get("signature"):
        raise BundleTrustError(
            "store bundle %r is UNSIGNED and EMBER_REQUIRE_SIGNED is on — unsigned code "
            "cannot ground (the Higgs rule: an executable pattern carries a verified "
            "signature + authority rung before exec)" % doc.get("id"))
    attested = _attested_signer_key(resolved)
    if not attested:
        raise BundleTrustError(
            "store bundle %r: author artifact %r attests no signing key (signed_by/"
            "public_key) — the embedded key alone proves self-consistency, not authorship; "
            "refusing to ground" % (doc.get("id"), creator))
    carried = str(bundle.get("signed_by") or "").strip().lower()
    if carried and carried != attested:
        raise BundleTrustError(
            "store bundle %r: bundle signed_by %s… is not the key author %r attests (%s…) — "
            "refusing to ground" % (doc.get("id"), carried[:16], creator, attested[:16]))
    pub = opsign.load_public(attested)
    if pub is None:
        raise BundleTrustError(
            "store bundle %r: author %r attests a malformed signing key — refusing to ground"
            % (doc.get("id"), creator))
    ok, why = opsign.verify_bundle(bundle, pub=pub)
    if not ok:
        raise BundleTrustError(
            "store bundle %r: %s — refusing to ground" % (doc.get("id"), why))

    _check_signer_rung(provenance_of(resolved), bundle_id=doc.get("id"), creator_id=creator)


def _bundle_from_store(group: str):
    """The store's bundle artifact for `group`, verified — or None when absent. A PRESENT but
    unverifiable bundle raises (loud), it never silently falls back to the shipped copy."""
    store = _attached_store
    if store is None:
        return None
    arts = getattr(store, "artifacts", store)
    try:
        doc = arts.get_artifact(BUNDLE_ARTIFACT_PREFIX + group)
    except Exception:
        return None                     # store unreachable => absent, use the shipped copy
    if not doc or doc.get("content_type") != BUNDLE_CONTENT_TYPE:
        return None
    raw = doc.get("content")
    if not raw:
        return None
    bundle = json.loads(raw) if isinstance(raw, str) else dict(raw)
    _verify_sha(bundle, where="store artifact %s" % doc.get("id"))
    verify_provenance(doc, bundle, store)
    return bundle


def _bundle_from_data(group: str) -> dict:
    if _DATA_DIR is None:
        # Say WHICH of the two sources failed and how to supply the second. "no bundle" alone sent
        # a previous reader looking for a corrupt file that was simply not there.
        raise BundleIntegrityError(
            "no bundle for group %r: it is not in the store, and no shipped bundle directory was "
            "found. Bundle payloads live in `agience-bundle/bundles/` — set AGIENCE_BUNDLE_ROOT to "
            "that directory (or to the agience-bundle checkout). There is deliberately no copy "
            "inside ember: a second copy of a content-addressed payload can drift from the one the "
            "mesh carries, and the sha gate would then verify the wrong bytes faithfully." % group)
    path = _DATA_DIR / (group + ".json")
    if not path.exists():
        raise BundleIntegrityError(
            "no bundle for group %r: not in the store and %s is missing (bundle payloads are "
            "`agience-bundle`'s — built there from chorus definitions)" % (group, path))
    bundle = json.loads(path.read_text(encoding="utf-8"))
    _verify_sha(bundle, where=str(path))
    return bundle


# ── exec: one isolated namespace per bundle sha ───────────────────────────────────────────────

_RELATIVE_IMPORT = re.compile(r"(?m)^\s*from\s+\.")


class _SourceLoader(importlib.abc.Loader):
    """Execs one bundle module from its distributed source. Modules whose source has no
    relative imports are shared BY CONTENT across bundles (module header: identity follows
    content); modules with relative imports bind to their bundle package and never share."""

    def __init__(self, source: str, share_key: Optional[str]):
        self.source, self.share_key, self._shared = source, share_key, None

    def create_module(self, spec):
        if self.share_key is not None:
            self._shared = _by_content.get(self.share_key)
            if self._shared is not None:
                return self._shared
        return None                                     # default module creation

    def exec_module(self, module):
        if self._shared is not None:
            return                                      # already exec'd under another bundle
        code = compile(self.source, module.__spec__.name, "exec")
        exec(code, module.__dict__)
        if self.share_key is not None:
            _by_content[self.share_key] = module

    def get_source(self, fullname):                     # tracebacks/inspect over bundle code
        return self.source


class _SeamLoader(importlib.abc.Loader):
    """Fills a DECLARED host seam with the ember module that implements it (store machinery,
    not operator code). Resolved lazily — only when the bundle actually imports the seam.

    The import machinery stamps the alias name onto whatever module create_module returns
    (init_module_attrs rewrites __spec__/__name__/__package__/__loader__), which would corrupt
    the REAL ember module's identity — its own relative imports then warn and resolve by luck.
    exec_module restores the host module's original attributes; the bundle still sees it under
    the alias via sys.modules."""

    def __init__(self, target: str):
        self.target = target
        self._orig = None

    def create_module(self, spec):
        mod = importlib.import_module(self.target)
        self._orig = (mod.__spec__, mod.__package__, mod.__name__,
                      getattr(mod, "__loader__", None))
        return mod

    def exec_module(self, module):
        spec, pkg, name, loader = self._orig
        module.__spec__, module.__package__, module.__name__ = spec, pkg, name
        if loader is not None:
            module.__loader__ = loader


class _BundleFinder(importlib.abc.MetaPathFinder):
    """Serves `pkg` and `pkg.<module>` for one verified bundle from its in-memory sources."""

    def __init__(self, pkg: str, bundle: dict):
        self.pkg = pkg
        self.modules = bundle["modules"]
        self.seams = {s: _HOST_SEAMS[s] for s in bundle.get("host_seams", ())
                      if s in _HOST_SEAMS}

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.pkg:
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        if not fullname.startswith(self.pkg + "."):
            return None
        name = fullname[len(self.pkg) + 1:]
        if name in self.modules:
            src = self.modules[name]
            share = (None if _RELATIVE_IMPORT.search(src)
                     else hashlib.sha256(src.encode("utf-8")).hexdigest())
            return importlib.util.spec_from_loader(fullname, _SourceLoader(src, share))
        if name in self.seams:
            return importlib.util.spec_from_loader(fullname, _SeamLoader(self.seams[name]))
        return None


def _load_group(group: str) -> dict:
    if group not in GROUPS:
        raise KeyError("unknown bundle group %r (groups: %s)" % (group, ", ".join(GROUPS)))
    with _lock:
        info = _loaded.get(group)
        if info is not None:
            return info
        bundle, origin = _bundle_from_store(group), "store"
        if bundle is None:
            bundle, origin = _bundle_from_data(group), "shipped"
        sha = bundle["sha256"]
        pkg = "_agience_bundle_%s_%s" % (group, sha[:12])
        if pkg not in sys.modules:
            sys.meta_path.append(_BundleFinder(pkg, bundle))
            importlib.import_module(pkg)
        entry = importlib.import_module("%s.%s" % (pkg, bundle["entry_module"]))
        info = {"bundle": bundle, "pkg": pkg, "entry": entry,
                "origin": origin, "sha256": sha}
        _loaded[group] = info
        return info


def load(name: str, module: Optional[str] = None):
    """The one lookup: `load(group)` -> the group's entry module; `load(group, mod)` -> a named
    module inside that bundle; `load(shared_dep)` -> the dep from its canonical bundle."""
    if module is None and name in _SHARED:
        name, module = _SHARED[name], name
    info = _load_group(name)
    if module is None or module == info["bundle"]["entry_module"]:
        return info["entry"]
    if module not in info["bundle"]["modules"]:
        raise KeyError("bundle %r does not carry module %r" % (name, module))
    return importlib.import_module("%s.%s" % (info["pkg"], module))


def register_fns(group: str) -> list:
    """The group's register functions, resolved from the loaded bundle (manifest-declared)."""
    info = _load_group(group)
    return [getattr(info["entry"], fn) for fn in info["bundle"]["register_fns"]]


def loaded() -> dict:
    """What is pinned in this process: {group: {"sha256", "origin"}} — a published stat, so
    health/status can SAY which bundle a node is actually running."""
    with _lock:
        return {g: {"sha256": i["sha256"], "origin": i["origin"]}
                for g, i in _loaded.items()}


def __getattr__(name: str):
    """PEP 562: `from .runner import arithmetic` / `from .runner import evolution` reads as the
    old sibling import did, and resolves through the single distribution path."""
    if name in GROUPS or name in _SHARED:
        return load(name)
    raise AttributeError("module 'prism.runner' has no attribute %r" % name)


def _log_gate_state() -> None:
    """The honest breadcrumb, once at runner init: the flagged seam's state is SAID, not
    discoverable only by reading env. The gate itself still reads env at call time."""
    raw = os.environ.get("EMBER_REQUIRE_SIGNED")
    if _gate_enabled():
        log.info("bundle signature gate ON (EMBER_REQUIRE_SIGNED=%s; floor: %s)",
                 raw, os.environ.get("EMBER_MIN_BUNDLE_RUNG")
                 or "derived — signer rung must weigh above prism.mass.GHOST_FLOOR")
    elif raw is None:
        log.info("bundle signature gate OFF (EMBER_REQUIRE_SIGNED unset) — flagged seam")
    else:
        log.info("bundle signature gate OFF (EMBER_REQUIRE_SIGNED=%r) — flagged seam", raw)


_log_gate_state()
