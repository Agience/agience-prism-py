"""``prism`` — the Prism SDK's command line: init / list / install / publish.

The install story (OPERATOR-ARCHITECTURE §12.3), client-side: a prism initializes an
identity + capability manifest, discovers bundles/crystals it can actually ground (the
self-filtering catalog), installs a bundle by VERIFYING it (the same semantics as the
op.install organon, run client-side through ``prism.crystal_model`` — Apache verifying
Apache, no AGPL import), and publishes locally-authored crystal/bundle artifacts.

What each command honestly does (and the seams, flagged):

  init      prism-py has NO key-generation machinery of its own — platform services get
            keys from the init container and ``prism.trust`` only LOADS them. So init
            GENERATES here, following the trust floor's file conventions: an RSA-2048
            keypair (``host.private.pem`` / ``host.public.pem`` in KEYS_DIR, the
            ``{name}.private.pem`` pattern) and a capability manifest
            (``prism.manifest.json``). Default capabilities: ``compute.local`` — the one
            capability running local Python physically demonstrates; everything else must
            be declared with ``--capabilities`` (a manifest is an ADVERTISEMENT the host
            must be able to honor, so nothing is auto-claimed).
  list      GET Mantle's discovery surface (``/artifacts/visible?content_type=…``) for
            bundle + crystal artifacts and filter by ``activates_on`` against THIS host's
            manifest capabilities — the self-filtering catalog. ``--all`` shows
            non-activating entries too, with the capability gap named per row.
  install   fetch the bundle artifact, verify the bundle sha, then member-by-member:
            fetch each crystal, ``prism.crystal_model.verify`` (refuse tampering), check
            the bundle's sha PIN, gate on ``activates_on`` (gap named). install.kind
            "artifact" grounds LOCALLY: the verified descriptor + crystal artifacts are
            recorded under ``KEYS_DIR/installed/<bundle>.json`` (the prism's own install
            registry — platform-side grounding stays with the op.install organon).
            pip/npm/cmake/compose are TYPED REFUSALS — "install kind X requires host
            policy" — executing package managers from a CLI verification path without a
            policy gate would be an unflagged security hole; the refusal IS the honest
            state, flagged for the host-policy brick.
  publish   build an artifact from a local JSON definition — a crystal definition
            (validated + sha-stamped via ``prism.crystal_model.crystal_artifact``) or a
            bundle ({"manifest": …, "content": …}, sha stamped over the canonical
            payload) — and POST it to Mantle, authed by the SDK's token conventions
            (``AGIENCE_TOKEN``, else ``AGIENCE_API_KEY``).

Config comes from ``prism.config`` (canonical names: MANTLE_URI, KEYS_DIR). The HTTP
boundary is the two module functions ``_http_get`` / ``_http_post`` — one seam, so tests
mock it without a network.

Exit codes: 0 ok · 1 usage/config/verification error · 3 policy-gated install kind ·
4 capability gap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

BUNDLE_CONTENT_TYPE = "application/vnd.agience.bundle+json"
CRYSTAL_CONTENT_TYPE = "application/vnd.agience.crystal+json"

MANIFEST_NAME = "prism.manifest.json"
POLICY_GATED_KINDS = ("pip", "npm", "cmake", "compose")

EXIT_OK, EXIT_ERROR, EXIT_POLICY, EXIT_GAP = 0, 1, 3, 4


# ── the HTTP boundary (one seam — tests replace these two functions) ─────────

def _token() -> Optional[str]:
    """The SDK's token conventions: AGIENCE_TOKEN (delegation/connection token,
    prism.host), else AGIENCE_API_KEY (prism.server)."""
    return os.getenv("AGIENCE_TOKEN") or os.getenv("AGIENCE_API_KEY") or None


def _headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return h


def _http_get(url: str, token: Optional[str] = None) -> Any:
    import httpx
    r = httpx.get(url, headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json() if r.content else None


def _http_post(url: str, body: Dict[str, Any], token: Optional[str] = None) -> Any:
    import httpx
    r = httpx.post(url, headers=_headers(token), json=body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else None


# ── shared helpers ───────────────────────────────────────────────────────────

def _keys_dir(arg: Optional[str]) -> Path:
    """--keys-dir, else the canonical KEYS_DIR (prism.config). No invented default:
    an identity location must be the caller's decision."""
    kd = arg or config.keys_dir()
    if not kd:
        raise SystemExit("prism: no keys directory — pass --keys-dir or set KEYS_DIR "
                         "(the SDK's canonical config name)")
    return Path(kd)


def _load_manifest(keys_dir: Path) -> Optional[Dict[str, Any]]:
    path = keys_dir / MANIFEST_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _capabilities(keys_dir: Path) -> Optional[List[str]]:
    m = _load_manifest(keys_dir)
    return list(m.get("capabilities") or []) if m else None


def _canonical_payload(content: Any) -> bytes:
    """bundle_manifest's canonical-payload semantics (str = UTF-8 bytes; dict/list =
    sorted-keys no-whitespace JSON) — the sha over these bytes IS the bundle ref."""
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    return json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_of(content: Any) -> str:
    return hashlib.sha256(_canonical_payload(content)).hexdigest()


def _context_of(artifact: Dict[str, Any]) -> Dict[str, Any]:
    ctx = artifact.get("context") or "{}"
    out = json.loads(ctx) if isinstance(ctx, str) else dict(ctx)
    return out if isinstance(out, dict) else {}


def _verify_bundle_sha(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """The bundle integrity gate — refuse-before-grounding, like op.install."""
    manifest = _context_of(artifact)
    claimed = manifest.get("sha256")
    content = artifact.get("content", "")
    actual = _sha256_of(content)
    if claimed != actual and isinstance(content, str):
        try:
            actual = _sha256_of(json.loads(content))    # sha taken over the canonical object
        except Exception:
            pass
    if claimed != actual:
        raise SystemExit("prism install: bundle integrity failure — manifest sha256=%s but the "
                         "payload hashes to %s; refusing unverified bytes" % (claimed, actual))
    return manifest


# ── init ─────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    keys_dir = _keys_dir(args.keys_dir)
    keys_dir.mkdir(parents=True, exist_ok=True)
    priv_path = keys_dir / "host.private.pem"
    pub_path = keys_dir / "host.public.pem"
    manifest_path = keys_dir / MANIFEST_NAME

    if priv_path.exists() and not args.force:
        # never clobber an identity — a regenerated key is a DIFFERENT prism.
        print("prism init: identity already exists at %s (use --force to regenerate — "
              "a new key is a NEW prism identity)" % priv_path)
        return EXIT_ERROR

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()))
    pub_path.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))

    caps = sorted({c.strip() for c in (args.capabilities or "compute.local").split(",")
                   if c.strip()})
    manifest = {"name": args.name, "environment": "py", "capabilities": caps,
                "public_key": "host.public.pem"}
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print("prism init: identity + manifest written to %s" % keys_dir)
    print("  keypair      host.private.pem / host.public.pem (RSA-2048)")
    print("  capabilities %s" % ", ".join(caps))
    return EXIT_OK


# ── list ─────────────────────────────────────────────────────────────────────

def _requires_of(artifact: Dict[str, Any]) -> List[str]:
    """The capability requirements an artifact advertises. Crystal context carries
    `requires` (crystal_artifact writes it); a bundle manifest carries
    `requires.capabilities` (bundle_manifest shape)."""
    ctx = _context_of(artifact)
    if artifact.get("content_type") == CRYSTAL_CONTENT_TYPE:
        return list(ctx.get("requires") or [])
    req = ctx.get("requires")
    if isinstance(req, dict):
        return list(req.get("capabilities") or [])
    return []


def cmd_list(args: argparse.Namespace) -> int:
    mantle = config.mantle_uri()
    token = _token()
    keys_dir = _keys_dir(args.keys_dir) if (args.keys_dir or config.keys_dir()) else None
    caps = _capabilities(keys_dir) if keys_dir else None
    if caps is None:
        print("prism list: no local manifest (%s) — showing ALL entries, unfiltered "
              "(run `prism init` to get the self-filtering catalog)" % MANIFEST_NAME)

    rows = []
    for ct, kind in ((BUNDLE_CONTENT_TYPE, "bundle"), (CRYSTAL_CONTENT_TYPE, "crystal")):
        arts = _http_get("%s/artifacts/visible?content_type=%s" % (mantle, ct), token) or []
        if isinstance(arts, dict):                       # tolerate {items: [...]} pagination
            arts = arts.get("items") or arts.get("artifacts") or []
        for a in arts:
            requires = _requires_of(a)
            missing = sorted(set(requires) - set(caps)) if caps is not None else []
            activates = caps is not None and not missing
            rows.append((kind, a.get("name") or a.get("id") or "?", requires,
                         activates, missing))

    shown = 0
    for kind, name, requires, activates, missing in rows:
        if caps is not None and not activates and not args.all:
            continue
        shown += 1
        if caps is None:
            status = "?"
        elif activates:
            status = "activates"
        else:
            status = "GAP: missing %s" % ",".join(missing)
        print("%-8s %-40s requires=%-40s %s" % (kind, name, ",".join(requires) or "-", status))
    if not shown:
        print("prism list: nothing %s" % ("matches this prism's capabilities "
              "(re-run with --all to see the gaps)" if caps is not None else "found"))
    return EXIT_OK


# ── install ──────────────────────────────────────────────────────────────────

def cmd_install(args: argparse.Namespace) -> int:
    from prism.crystal_model import activates_on, crystal_sha, required_capabilities, verify

    mantle = config.mantle_uri()
    token = _token()
    keys_dir = _keys_dir(args.keys_dir)
    caps = _capabilities(keys_dir)
    if caps is None:
        print("prism install: no local manifest — run `prism init` first (installing "
              "without an advertised capability set cannot be gated honestly)")
        return EXIT_ERROR

    artifact = _http_get("%s/artifacts/%s" % (mantle, args.bundle), token)
    if not artifact:
        print("prism install: bundle %r not found" % args.bundle)
        return EXIT_ERROR
    manifest = _verify_bundle_sha(artifact)              # 1. the bundle sha gate

    inst = manifest.get("install") or {}
    kind = inst.get("kind") if isinstance(inst, dict) else None
    if kind in POLICY_GATED_KINDS:
        # ⛔ the typed policy refusal — see the module docstring. Never a shell-out.
        print("prism install: REFUSED — install kind %s requires host policy "
              "(seam: host-policy-gate)" % kind)
        return EXIT_POLICY
    if kind != "artifact":
        print("prism install: install.kind %r is outside the vocabulary — refusing" % (kind,))
        return EXIT_ERROR

    members = manifest.get("crystals")
    if not isinstance(members, list) or not members:
        print("prism install: a crystal bundle must list its crystals [{name, sha256}, ...]")
        return EXIT_ERROR

    grounded = []
    for member in members:
        name, pin = member.get("name"), member.get("sha256")
        if not name or not pin:
            print("prism install: crystals[] member missing name/sha256 — an unpinned "
                  "crystal cannot refuse tampering")
            return EXIT_ERROR
        cart = _http_get("%s/artifacts/%s" % (mantle, name), token)
        if not cart:
            print("prism install: crystal %s not found" % name)
            return EXIT_ERROR
        try:
            crystal = verify(cart)                       # 2. refuses tampering, loudly
        except ValueError as e:
            print("prism install: %s" % e)
            return EXIT_ERROR
        if crystal_sha(crystal) != pin:
            print("prism install: crystal %s — bundle pins sha256=%s but the fetched crystal "
                  "is %s; refusing a substituted structure" % (name, pin, crystal_sha(crystal)))
            return EXIT_ERROR
        if not activates_on(crystal, caps):              # 3. the prism junction gate
            gap = sorted(set(required_capabilities(crystal)) - set(caps))
            print("prism install: REFUSED — capability gap: crystal %s requires %s this "
                  "prism does not advertise (advertised: %s)" % (name, gap, sorted(caps)))
            return EXIT_GAP
        grounded.append({"name": name, "sha256": pin,
                         "requires": required_capabilities(crystal), "artifact": cart})

    # 4. ground LOCALLY: the prism's own install registry (KEYS_DIR/installed/). The
    # platform-side registry mutation belongs to the op.install organon, not this client.
    rec_dir = keys_dir / "installed"
    rec_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(args.bundle))
    record = {"bundle": args.bundle, "sha256": manifest.get("sha256"), "kind": "artifact",
              "crystals": grounded, "prism_capabilities": sorted(caps)}
    (rec_dir / (safe + ".json")).write_text(
        json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("prism install: grounded %d crystal(s) from %s -> %s" %
          (len(grounded), args.bundle, rec_dir / (safe + ".json")))
    return EXIT_OK


# ── publish ──────────────────────────────────────────────────────────────────

def cmd_publish(args: argparse.Namespace) -> int:
    from prism.crystal_model import crystal_artifact

    token = _token()
    if not token:
        print("prism publish: no credential — set AGIENCE_TOKEN (or AGIENCE_API_KEY); "
              "publishing writes to Mantle and must be authed")
        return EXIT_ERROR

    path = Path(args.path)
    if not path.is_file():
        print("prism publish: %s not found" % path)
        return EXIT_ERROR
    definition = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(definition, dict) and "facets" in definition:
        # a CRYSTAL definition — validated + sha-stamped by the contract itself.
        try:
            artifact = crystal_artifact(definition)
        except ValueError as e:
            print("prism publish: %s" % e)
            return EXIT_ERROR
    elif isinstance(definition, dict) and "manifest" in definition:
        # a BUNDLE: {"name", "manifest": {...}, "content": ...} — sha stamped over the
        # canonical payload (bundle_manifest semantics), never trusted from the file.
        manifest = dict(definition["manifest"])
        content = definition.get("content", "")
        manifest["sha256"] = _sha256_of(content)
        name = definition.get("name") or manifest.get("name")
        if not name:
            print("prism publish: a bundle definition needs a name")
            return EXIT_ERROR
        artifact = {"id": name, "name": name, "content_type": BUNDLE_CONTENT_TYPE,
                    "context": json.dumps(manifest),
                    "content": content if isinstance(content, str) else json.dumps(content)}
    else:
        print("prism publish: %s is neither a crystal definition (facets/tektons/…) nor a "
              "bundle ({manifest, content}) — refusing to guess" % path)
        return EXIT_ERROR

    out = _http_post("%s/artifacts" % config.mantle_uri(), artifact, token)
    sha = json.loads(artifact["context"]).get("sha256")
    print("prism publish: %s published (sha256=%s)" % (artifact["name"], sha))
    if isinstance(out, dict) and out.get("id"):
        print("  store id: %s" % out["id"])
    return EXIT_OK


# ── entrypoint ───────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism",
        description="Agience Prism CLI — init an identity, discover what this host can "
                    "ground, install bundles (verified), publish artifacts.")
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="generate this prism's keypair + capability manifest")
    p_init.add_argument("--keys-dir", default=None, help="identity directory (default: $KEYS_DIR)")
    p_init.add_argument("--name", default="prism-host", help="this prism's name")
    p_init.add_argument("--capabilities", default=None,
                        help="comma-separated advertised capabilities (default: compute.local — "
                             "the one capability local execution demonstrates)")
    p_init.add_argument("--force", action="store_true",
                        help="regenerate even if an identity exists (a NEW prism identity)")
    p_init.set_defaults(fn=cmd_init)

    p_list = sub.add_parser("list", help="bundles/crystals from Mantle, filtered by what "
                                         "this prism can activate")
    p_list.add_argument("--keys-dir", default=None)
    p_list.add_argument("--all", action="store_true", help="include entries with capability gaps")
    p_list.set_defaults(fn=cmd_list)

    p_inst = sub.add_parser("install", help="verify + ground a bundle (artifact kind only; "
                                            "pip/npm/cmake/compose are policy-gated refusals)")
    p_inst.add_argument("bundle", help="bundle artifact id/name in Mantle")
    p_inst.add_argument("--keys-dir", default=None)
    p_inst.set_defaults(fn=cmd_install)

    p_pub = sub.add_parser("publish", help="build + validate + sha-stamp a local crystal/bundle "
                                           "definition and PUT it to Mantle")
    p_pub.add_argument("path", help="path to the JSON definition file")
    p_pub.set_defaults(fn=cmd_publish)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except SystemExit:
        raise
    except Exception as e:                               # honest surface, no traceback spam
        print("prism %s: %s: %s" % (args.command, type(e).__name__, e))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
