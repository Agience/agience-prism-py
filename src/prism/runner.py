"""The pattern runner — a host executes operator code through the one distribution path.

There is a single distribution path. The operator implementations' authoritative home is chorus, and
no host holds code copies. Chorus publishes each register group as a source bundle —
the impl module plus its impl-internal deps, with a manifest {group, entry_module, register_fns,
host_seams, modules, sha256} — and this module loads a bundle, verifies it, and execs it into an
isolated namespace.

    from prism.runner import arithmetic            # the loaded bundle's entry module
    from prism.runner import evolution             # a shared dep, from its canonical bundle

It adds no hard dependency: everything is stdlib or prism-internal, and `opsign` (the only
`cryptography` reach) is imported lazily inside the env-gated trust leg.

Content addressing is the integrity gate. A bundle's sha256 is computed over the canonical JSON
payload of everything except the sha itself (see `_canonical`). Before any exec the hash is
recomputed and compared; a mismatch raises `BundleIntegrityError`. There is no unverified path.

Where bundles come from, in order:
  1. The local store: artifact `bundle-<group>`, content_type
     `application/vnd.agience.bundle+json`, its `content` the bundle JSON — the mesh path, where
     bundles travel as artifacts. sha-verified and provenance-checked.
  2. A file the host bound to the group with `register_group(name, path)` — for a payload that
     lives outside the shipped directory (a third-party tekton's bundle beside its own package).
     sha-verified against its own manifest, exactly like (3).
  3. The data files `<group>.json` under `$AGIENCE_BUNDLE_ROOT`, published by the same build that
     produces the mesh artifacts. Same bytes, same sha the mesh carries; it exists so an offline
     node bootstraps with no store bundle. sha-verified against its own manifest. Unset, this route
     is simply absent — prism resolves no path of its own.

Version-pinned per process: the first successful load of a group pins that bundle for the process
lifetime — one logical runtime runs one version of an operator throughout; a restart picks up newer
bundles. `attach(store)` at boot, before the first load, is what lets store bundles take precedence
over shipped ones.

Trust gate (flagged seam — `verify_provenance`): sha-verification is the integrity leg and is always
enforced. The signature/rung leg is implemented but env-gated:

  * `EMBER_REQUIRE_SIGNED` unset (default): sha check plus a `created_by`-resolvable check against
    the store (an executable artifact with no resolvable author carries no authority), and one
    breadcrumb log line at import saying the gate is off.
  * `EMBER_REQUIRE_SIGNED=1`: a store-sourced bundle must additionally carry a valid Ed25519
    signature (`opsign.sign_bundle` envelope over the same canonical payload the sha covers), the
    signing key must be attested by the store-resolved author artifact (an embedded key alone proves
    self-consistency, not authorship), and the author's channel (`prism.mass.provenance_of`) must
    ground something: `EMBER_BUNDLE_CHANNELS` when set, else `prism.mass.has_referent`.

Shipped data files ride package-install trust and skip the store-provenance leg only, under either
gate state.

Host seams: a bundle declares the host modules it may reach for (`host_seams`). The seam→module
mapping is registered by the host (`register_seam`); an unfilled seam leaves the bundle's own
fallback in charge (operators.select_for answers basis="generic"). Seams are store/host machinery,
never operator code.

Which groups exist is discovered, not declared. A group exists when its payload does, so there is no
list to add to and a host or third party introduces one without editing prism. `known_groups()`
reports what is discoverable locally — every `<group>.json` in the shipped directory, plus whatever
a host bound with `register_group(name, path)`. `load()` is not gated on that report: it asks the
store, then the file, and raises `UnknownBundleGroupError` when no payload exists anywhere for the
group.

Discovery adds places to look, never a way to skip a check. Every route ends in `_verify_sha` and,
for store bundles, `verify_provenance`. `_verify_group` additionally binds the group name to the
payload, which is what keeps a host-supplied path honest about what it carries.

Module sharing by content: bundle modules with no intra-bundle (relative) imports — answer,
evolution, category, code_index, doc_index, content — are cached by sha256(source) and shared across
bundles, so `evolution` is one module object and `Answer` one class process-wide whenever the
distributed bytes are identical. Identity follows content, exactly like the store.
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

log = logging.getLogger(__name__)

BUNDLE_CONTENT_TYPE = "application/vnd.agience.bundle+json"
BUNDLE_ARTIFACT_PREFIX = "bundle-"

def _data_dir() -> Optional[Path]:
    """Where the shipped bundle files live — named by the deployment, never inside this package.

    Resolution order, and both steps are explicit rather than guessed:
      1. `$AGIENCE_BUNDLE_ROOT` — what a deployment sets. Points at the directory holding
         `<group>.json`, or at a checkout containing `bundles/`.
      2. None. There is no in-package fallback and no walk to a sibling checkout: a silent fallback
         to a stale embedded copy is how two versions of a content-addressed payload start to
         disagree, and the sha gate would then verify the wrong bytes faithfully. A path derived
         from where this file happens to sit is the same fallback wearing a directory name.

    Returning None is not an error here — the store is the primary source (path 1 in the module
    docstring), a host binds its own payloads with `register_group`, and a node with its bundles in
    the lattice needs no files at all. `_bundle_from_data` raises when the absence is actually
    reached.
    """
    raw = os.getenv("AGIENCE_BUNDLE_ROOT", "").strip()
    candidates = []
    if raw:
        p = Path(raw).expanduser()
        candidates += [p, p / "bundles"]
    for c in candidates:
        try:
            if c.is_dir():
                return c.resolve()
        except OSError:
            continue
    return None


_DATA_DIR = _data_dir()

# `GROUPS` answers through `__getattr__` at the foot of this module (`from prism.runner import
# GROUPS`, and ember re-exports it), and what it answers with is `known_groups()`: a measurement of
# the payloads that exist, taken at the moment it is asked.

# A group name goes into a filename (`<group>.json`) and into a module name
# (`_agience_bundle_<group>_<sha12>`), so it must be a Python identifier. The constraint is derived
# from those two uses: `..` or `a-b` would either escape the bundle directory or produce a package
# name no import statement can spell. `_check_name` raises for anything else.
_GROUP_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# shared impl-internal deps -> the canonical bundle that carries them (identical bytes in every
# bundle that includes them — the by-content module cache makes the choice immaterial).
_SHARED = {"evolution": "arithmetic", "answer": "arithmetic", "category": "arithmetic",
           "describe": "operators", "code_index": "operators", "doc_index": "operators"}

# seam name (as declared by a bundle's manifest) -> the dotted module path that FILLS it.
#
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
    No caller catches this and continues into an exec: unverified code does not run."""


class BundleTrustError(BundleIntegrityError):
    """The signature/rung leg raises this (gate on) for a bundle that is unsigned, whose key is
    not attested by the author artifact, that is forged, or whose signer's rung is below the
    floor. A subclass of BundleIntegrityError, so a caller that catches the base class catches
    this too; a distinct name so 'tampered bytes' and 'untrusted author' are never conflated in
    a traceback."""


class UnknownBundleGroupError(BundleIntegrityError):
    """Nothing carries this group: not the store, not a host-registered file, not the shipped
    directory. A subclass of BundleIntegrityError, because a caller that stops on a bad bundle
    stops here too, and because the two are one fact under content addressing: an unverifiable
    payload and an absent payload both mean there is nothing here to run.

    "Unknown group" means no payload was found, and the message names all three places that were
    looked and how to supply one. A name with no bytes behind it fails before anything is
    imported."""


# group name -> the bundle payload FILE a host bound to it (`register_group`). The shipped
# directory needs no such map: a payload sitting in it IS the declaration, which is the whole point
# of discovery. This exists for the payload that lives somewhere else — a third-party tekton's
# bundle beside its own package, a build output, a test fixture — where only the host knows the path.
#
# Registration is idempotent, last-writer-wins per name, exactly like `register_seam`, and it is
# subject to the same ordering rule: register at boot, BEFORE the first load, because the first
# successful load of a group pins it for the process.
_HOST_GROUPS: Dict[str, Path] = {}


def _check_name(group: str) -> str:
    """A group name must be spellable as both a file stem and a module name (see `_GROUP_NAME`)."""
    name = str(group)
    if not _GROUP_NAME.match(name):
        raise UnknownBundleGroupError(
            "bundle group %r is not a usable name: it becomes both a filename (<group>.json) and a "
            "module name (_agience_bundle_<group>_<sha>), so it must be a Python identifier "
            "([A-Za-z_][A-Za-z0-9_]*)" % name)
    return name


def register_group(name: str, path) -> None:
    """Declare that bundle group `name` is carried by the payload file at `path`.

    The host's answer to which groups exist, and the counterpart of `register_seam`: the loader
    holds no opinion about either. A registered path takes precedence over a same-named file in the
    shipped directory, since the host is more specific than an ambient sibling checkout, and a store
    bundle outranks both because that is the path with provenance behind it.

    This opens no unverified path. The file is read by `_bundle_from_data`, which sha-verifies it
    against its own manifest and checks that the payload names this group, before a single line of
    it is compiled. A host says where to look, not what to trust.

    Raises at registration when the path is not a file, so a boot-time mistake is heard at boot."""
    group = _check_name(name)
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(
            "register_group(%r, %s): no such bundle payload file. Register the path of a built "
            "`<group>.json`" % (group, p))
    _HOST_GROUPS[group] = p.resolve()


def registered_groups() -> Dict[str, str]:
    """The groups this host has bound to a file — a copy, so a caller cannot mutate the live map."""
    return {k: str(v) for k, v in _HOST_GROUPS.items()}


def known_groups() -> tuple:
    """Every group discoverable in this process, sorted — a measurement rather than a declaration.

    This is what a node can load with no store attached, which is what a health or status line, a
    test, and `runner.GROUPS` each want. It is not the set of loadable groups: a store carrying
    `bundle-<group>` serves a group that appears in no local file, and `load()` serves it, because
    nothing is gated on this function. Store contents are not enumerated here because an artifact
    store is not required to offer a listing surface."""
    names = set(_HOST_GROUPS)
    if _DATA_DIR is not None:
        try:
            names |= {p.stem for p in _DATA_DIR.glob("*.json") if _GROUP_NAME.match(p.stem)}
        except OSError:
            pass
    return tuple(sorted(names))


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
    """The bytes a bundle's sha is taken over — from the contract, not reproduced here.
    A copy is a reproduction with no original to be checked against."""
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


def _verify_group(bundle: dict, group: str, *, where: str) -> None:
    """The payload must SAY it is the group it was asked for.

    This is the check `_verify_sha` cannot make. The sha proves a payload is internally consistent —
    that these bytes are the bytes that were hashed — and says nothing about whether they are the
    bytes for this name, because the name comes from outside the payload: a filename, a store
    artifact id, or a host's `register_group` argument. Without this binding, an `install.json`
    holding the `fetch` bundle would load a valid payload under the wrong name and every other check
    would pass.

    `group` sits inside the canonical payload the sha covers, so the check costs nothing and cannot
    be forged separately: changing it requires re-hashing, which makes it a different bundle."""
    claimed = bundle.get("group")
    if claimed != group:
        raise BundleIntegrityError(
            "bundle at %s was asked for as group %r but its own sha-covered manifest says %r — "
            "refusing to load a payload under a name it was not hashed under" % (where, group, claimed))


def _gate_enabled() -> bool:
    """Is the signature/rung leg on? Read at call time so a test or process can flip it without a
    reimport. A set-but-falsey value ('0', 'false', …) is off and any other set value is on, so an
    operator who set the variable never gets a silently-disabled gate from a spelling."""
    v = (os.environ.get("EMBER_REQUIRE_SIGNED") or "").strip().lower()
    return v not in ("", "0", "false", "no", "off")


def _attested_signer_key(creator: dict) -> str:
    """The signing public key the author artifact itself attests (hex), or '' when it attests
    none. Read from `signed_by`/`public_key` at top level or inside `context` (dict or JSON
    string — the same tolerance `prism.mass.provenance_of` extends to `context.provenance`).
    Taking the key from the store-resolved author rather than from the bundle asking to be trusted
    is what makes this an authorship check: verifying against a bundle's embedded key would prove
    only that the bundle is self-consistent."""
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


def _check_signer_rung(rung, *, bundle_id, creator_id, author=None, resolve=None) -> None:
    """The provenance leg: the author must be grounded before they may author executable patterns.

    Default, when the author artifact and a resolver are in hand: `prism.mass.grounds(author,
    resolve)` — the author's `cited_from` must name an artifact that actually exists in this store.

    Grounding is resolved rather than asserted. A label such as `span_cited` passes forever, whereas
    a citation can dangle, so the gate follows the citation to a real artifact. This is the same
    discipline `verify_provenance` applies one step earlier — `created_by` must resolve, not merely
    be present — extended to the author's own grounding.

    `has_referent(rung)` is the fallback when no resolver was supplied, so a caller holding only a
    channel string still gets the label check. It is the weaker of the two paths; the resolver path
    is the strong one, and it treats UNKNOWN and HYPOTHESIS as ungrounded, same as any other author
    that fails to resolve.

    `EMBER_BUNDLE_CHANNELS` names an explicit comma-separated set of `prism.mass.Provenance` values
    to require instead. It is a set rather than a floor, matching the shape of what it overrides. An
    unrecognized name raises here, rather than mapping to UNKNOWN as `provenance_of` does:
    `provenance_of` maps a typo to UNKNOWN because failing closed there leaves an artifact
    ungrounded, whereas the same fallback here would weaken an execution gate, so the fail-closed
    direction inverts.

    `EMBER_MIN_BUNDLE_RUNG` raises rather than being reinterpreted. It named a floor on an ordering
    this gate does not use, and reading it as a set would change what a deployed configuration means
    without anyone touching it, so a stale environment fails loudly."""
    from prism.mass import Provenance, grounds, has_referent

    stale = (os.environ.get("EMBER_MIN_BUNDLE_RUNG") or "").strip()
    if stale:
        raise BundleTrustError(
            "EMBER_MIN_BUNDLE_RUNG=%r is set, but it named a floor on prism.mass.CLAIM_LADDER, "
            "which no longer exists — refusing to ground %r rather than reinterpret a trust "
            "setting. Use EMBER_BUNDLE_CHANNELS (comma-separated Provenance names) instead."
            % (stale, bundle_id))

    want_names = [n.strip().lower() for n in
                  (os.environ.get("EMBER_BUNDLE_CHANNELS") or "").split(",") if n.strip()]
    if want_names:
        want = set()
        for name in want_names:
            try:
                want.add(Provenance(name))
            except ValueError:
                raise BundleTrustError(
                    "EMBER_BUNDLE_CHANNELS names %r, which is not a prism.mass.Provenance (%s) — "
                    "refusing to ground %r: a mis-set gate may not weaken it"
                    % (name, ", ".join(p.value for p in Provenance), bundle_id))
        if rung not in want:
            raise BundleTrustError(
                "store bundle %r: signer %r is on channel %r, not in the required set %s "
                "(EMBER_BUNDLE_CHANNELS) — refusing to ground"
                % (bundle_id, creator_id, getattr(rung, "value", rung),
                   sorted(p.value for p in want)))
        return
    if resolve is not None:
        if grounds(author, resolve) is None:
            raise BundleTrustError(
                "store bundle %r: author %r is not grounded — its `cited_from` is absent, "
                "self-anchored, or names an artifact that does not resolve in this store. An "
                "executable pattern needs an author something actually stands behind (channel was "
                "%r; set EMBER_BUNDLE_CHANNELS to gate on channels instead)"
                % (bundle_id, creator_id, getattr(rung, "value", rung)))
        return
    if not has_referent(rung):
        raise BundleTrustError(
            "store bundle %r: signer %r is on channel %r, which has no checkable referent — "
            "nothing grounds this author, so they may not author executable patterns (set "
            "EMBER_BUNDLE_CHANNELS to an explicit set of prism.mass.Provenance names to override)"
            % (bundle_id, creator_id, getattr(rung, "value", rung)))


def verify_provenance(doc: dict, bundle: dict, store) -> None:
    """Trust gate (see module header). Runs for store-sourced bundles, after the sha check.

    Always: the bundle artifact must name a `created_by` that resolves in the store, because an
    executable pattern's authority comes from its provenance — one with no resolvable author has
    none.

    When `EMBER_REQUIRE_SIGNED` is on, the signature/rung leg (the Higgs rule) additionally
    requires: a valid `opsign.sign_bundle` envelope, the signing key attested by the resolved
    author artifact, and the author's rung at/above the floor (`_check_signer_rung`).
    This always raises; it never softens to a warning."""
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

    # The author artifact and the store's resolver both go in: grounding is checked against the
    # store, not read off a label. `arts.get_artifact` is the same resolver that established
    # `created_by` above, so both legs of "provenance needs authority" resolve through one door.
    _check_signer_rung(provenance_of(resolved), bundle_id=doc.get("id"), creator_id=creator,
                       author=resolved, resolve=arts.get_artifact)


def _bundle_from_store(group: str):
    """The store's bundle artifact for `group`, verified — or None when absent. A present but
    unverifiable bundle raises loudly — it never silently falls back to the shipped copy."""
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
    _verify_group(bundle, group, where="store artifact %s" % doc.get("id"))
    verify_provenance(doc, bundle, store)
    return bundle


def _bundle_file(group: str) -> Optional[Path]:
    """The file carrying this group: what the host registered, else the shipped `<group>.json`.

    A registered path is returned even if it has since vanished, so that a missing host payload
    fails by name in `_bundle_from_data` rather than being substituted by a same-named shipped
    file."""
    p = _HOST_GROUPS.get(group)
    if p is not None:
        return p
    if _DATA_DIR is not None:
        p = _DATA_DIR / (group + ".json")
        if p.is_file():
            return p
    return None


def _bundle_from_data(group: str) -> dict:
    path = _bundle_file(group)
    if path is None:
        # Name all three places that were looked and how to supply each, so the message separates
        # "nothing carries this" from "the payload here is corrupt".
        raise UnknownBundleGroupError(
            "no bundle for group %r. A group exists when its sha-verified payload does, so this is "
            "the whole answer: the store has no `bundle-%s` artifact, no host registered a file for "
            "it, and %s. Supply it by placing a built `%s.json` under $AGIENCE_BUNDLE_ROOT, by "
            "publishing a `bundle-%s` artifact, or by calling "
            "prism.runner.register_group(%r, path) at boot. Discoverable here: %s. "
            "There is no in-package copy to fall back to: a second copy of a content-addressed "
            "payload can drift from the one the mesh carries, and the sha gate would then verify "
            "the wrong bytes faithfully."
            % (group, group,
               ("no shipped bundle directory was found — set AGIENCE_BUNDLE_ROOT to one"
                if _DATA_DIR is None else "%s is missing" % (_DATA_DIR / (group + ".json"))),
               group, group, group, ", ".join(known_groups()) or "(nothing)"))
    bundle = json.loads(path.read_text(encoding="utf-8"))
    _verify_sha(bundle, where=str(path))
    _verify_group(bundle, group, where=str(path))
    return bundle


# ── exec: one isolated namespace per bundle sha ───────────────────────────────────────────────

_RELATIVE_IMPORT = re.compile(r"(?m)^\s*from\s+\.")


class _SourceLoader(importlib.abc.Loader):
    """Execs one bundle module from its distributed source. Modules whose source has no
    relative imports are shared by content across bundles (module header: identity follows
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
    """Fills a declared host seam with the ember module that implements it (store machinery,
    not operator code). Resolved lazily — only when the bundle actually imports the seam.

    The import machinery stamps the alias name onto whatever module create_module returns
    (init_module_attrs rewrites __spec__/__name__/__package__/__loader__), which would corrupt
    the real ember module's identity — its own relative imports then warn and resolve by luck.
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
    # No membership precheck: the sources are the answer, and a group with no payload in any of them
    # raises `UnknownBundleGroupError` from `_bundle_from_data` before anything is compiled. The
    # name is still checked for being spellable, because it reaches both a path and a module name.
    group = _check_name(group)
    with _lock:
        info = _loaded.get(group)
        if info is not None:
            return info
        bundle, origin = _bundle_from_store(group), "store"
        if bundle is None:
            # "host" and "shipped" are told apart because `loaded()` is a published stat: a node
            # reporting "shipped" while actually running a payload the host pointed elsewhere would
            # be reporting the wrong provenance of the bytes it is executing.
            bundle = _bundle_from_data(group)
            origin = "host" if group in _HOST_GROUPS else "shipped"
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
    health/status can say which bundle a node is actually running."""
    with _lock:
        return {g: {"sha256": i["sha256"], "origin": i["origin"]}
                for g, i in _loaded.items()}


def __getattr__(name: str):
    """PEP 562: `from .runner import arithmetic` / `from .runner import evolution` reads as a plain
    sibling import and resolves through the single distribution path.

    `GROUPS` is served here too, as the live measurement `known_groups()`, so the name every caller
    reads (ember re-exports it) tracks the payloads actually present. A dunder name raises first,
    before any lookup, because the import machinery and pytest probe for `__path__`, `__wrapped__`,
    `__bases__` and friends, and none of those should cost a directory listing or a bundle load."""
    if name.startswith("__"):
        raise AttributeError("module 'prism.runner' has no attribute %r" % name)
    if name == "GROUPS":
        return known_groups()
    if name in _SHARED or name in known_groups():
        return load(name)
    raise AttributeError("module 'prism.runner' has no attribute %r" % name)


def _log_gate_state() -> None:
    """The honest breadcrumb, once at runner init: the flagged seam's state is said, not
    discoverable only by reading env. The gate itself still reads env at call time."""
    raw = os.environ.get("EMBER_REQUIRE_SIGNED")
    if _gate_enabled():
        log.info("bundle signature gate ON (EMBER_REQUIRE_SIGNED=%s; channels: %s)",
                 raw, os.environ.get("EMBER_BUNDLE_CHANNELS")
                 or "derived — signer channel must satisfy prism.mass.has_referent")
    elif raw is None:
        log.info("bundle signature gate OFF (EMBER_REQUIRE_SIGNED unset) — flagged seam")
    else:
        log.info("bundle signature gate OFF (EMBER_REQUIRE_SIGNED=%r) — flagged seam", raw)


_log_gate_state()
