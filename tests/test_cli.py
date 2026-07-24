"""The `prism` CLI pinned: init generates identity+manifest (and refuses to clobber),
list is the self-filtering catalog, install runs the op.install verification semantics
client-side (sha gate, tamper refusal, pin check, capability gap NAMED, policy-gated
kinds refused typed), publish validates + sha-stamps before the PUT. The HTTP boundary
(`cli._http_get` / `cli._http_post`) is mocked — no network in tests."""
from __future__ import annotations

import json

import pytest

from prism.crystal_model import crystal_artifact

from prism import cli


# ── fixtures ─────────────────────────────────────────────────────────────────

def _crystal(name="crystal.demo", requires=("compute.local",)):
    return {
        "name": name,
        "facets": [{"name": "chat", "direction": "both"}],
        "tektons": [{"name": "sage", "domain": "knowledge"}],
        "organons": [{"name": "op.respond", "requires": list(requires)}],
        "created_by": "person-1",
    }


def _bundle_artifact(crystal_art, *, kind="artifact", content=""):
    pin = json.loads(crystal_art["content"])["sha256"]
    manifest = {"bundle_kind": "crystal", "environment": "any",
                "sha256": cli._sha256_of(content), "install": {"kind": kind},
                "crystals": [{"name": crystal_art["name"], "sha256": pin}],
                "prisms": [{"name": "prism-py", "environment": "py"}],
                "created_by": "person-1"}
    return {"id": "bundle.demo", "name": "bundle.demo",
            "content_type": cli.BUNDLE_CONTENT_TYPE,
            "context": json.dumps(manifest), "content": content}


@pytest.fixture()
def keys_dir(tmp_path, monkeypatch):
    kd = tmp_path / "keys"
    monkeypatch.setenv("KEYS_DIR", str(kd))
    monkeypatch.delenv("AGIENCE_TOKEN", raising=False)
    monkeypatch.delenv("AGIENCE_API_KEY", raising=False)
    return kd


def _mock_store(monkeypatch, artifacts):
    """Replace the HTTP seam with an in-memory artifact store; record posts."""
    posted = []

    def fake_get(url, token=None):
        if "/artifacts/visible" in url:
            ct = url.split("content_type=")[1]
            return [a for a in artifacts.values() if a["content_type"] == ct]
        aid = url.rstrip("/").split("/")[-1]
        return artifacts.get(aid)

    def fake_post(url, body, token=None):
        posted.append((url, body, token))
        return {"id": body.get("id")}

    monkeypatch.setattr(cli, "_http_get", fake_get)
    monkeypatch.setattr(cli, "_http_post", fake_post)
    return posted


def _init(keys_dir, caps="compute.local,store.read"):
    assert cli.main(["init", "--keys-dir", str(keys_dir), "--capabilities", caps]) == cli.EXIT_OK


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_generates_identity_and_manifest(keys_dir):
    _init(keys_dir)
    assert (keys_dir / "host.private.pem").is_file()
    assert (keys_dir / "host.public.pem").is_file()
    m = json.loads((keys_dir / cli.MANIFEST_NAME).read_text())
    assert m["environment"] == "py"
    assert m["capabilities"] == ["compute.local", "store.read"]


def test_init_refuses_to_clobber_an_identity(keys_dir):
    _init(keys_dir)
    before = (keys_dir / "host.private.pem").read_bytes()
    assert cli.main(["init", "--keys-dir", str(keys_dir)]) == cli.EXIT_ERROR
    assert (keys_dir / "host.private.pem").read_bytes() == before   # untouched


def test_init_without_a_keys_dir_is_a_clear_error(monkeypatch, capsys):
    monkeypatch.delenv("KEYS_DIR", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["init"])


# ── list: the self-filtering catalog ─────────────────────────────────────────

def test_list_filters_by_this_prisms_capabilities(keys_dir, monkeypatch, capsys):
    _init(keys_dir, caps="compute.local")
    fits = crystal_artifact(_crystal("crystal.fits", requires=("compute.local",)))
    gaps = crystal_artifact(_crystal("crystal.gaps", requires=("net.get", "compute.local")))
    _mock_store(monkeypatch, {"crystal.fits": fits, "crystal.gaps": gaps})
    assert cli.main(["list", "--keys-dir", str(keys_dir)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "crystal.fits" in out and "crystal.gaps" not in out


def test_list_all_names_the_gap(keys_dir, monkeypatch, capsys):
    _init(keys_dir, caps="compute.local")
    gaps = crystal_artifact(_crystal("crystal.gaps", requires=("net.get", "compute.local")))
    _mock_store(monkeypatch, {"crystal.gaps": gaps})
    assert cli.main(["list", "--keys-dir", str(keys_dir), "--all"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "crystal.gaps" in out and "GAP: missing net.get" in out


# ── install ──────────────────────────────────────────────────────────────────

def test_install_grounds_a_verified_artifact_bundle(keys_dir, monkeypatch):
    _init(keys_dir, caps="compute.local")
    cart = crystal_artifact(_crystal())
    _mock_store(monkeypatch, {"bundle.demo": _bundle_artifact(cart), "crystal.demo": cart})
    assert cli.main(["install", "bundle.demo", "--keys-dir", str(keys_dir)]) == cli.EXIT_OK
    rec = json.loads((keys_dir / "installed" / "bundle.demo.json").read_text())
    assert rec["crystals"][0]["name"] == "crystal.demo"
    assert rec["crystals"][0]["requires"] == ["compute.local"]


def test_install_refuses_a_tampered_bundle(keys_dir, monkeypatch):
    _init(keys_dir)
    cart = crystal_artifact(_crystal())
    b = _bundle_artifact(cart, content="payload")
    b["content"] = "payload-tampered"
    _mock_store(monkeypatch, {"bundle.demo": b, "crystal.demo": cart})
    with pytest.raises(SystemExit, match="integrity failure"):
        cli.main(["install", "bundle.demo", "--keys-dir", str(keys_dir)])


def test_install_refuses_a_tampered_crystal(keys_dir, monkeypatch, capsys):
    _init(keys_dir, caps="compute.local")
    cart = crystal_artifact(_crystal())
    b = _bundle_artifact(cart)
    tampered = json.loads(cart["content"])
    tampered["organons"].append({"name": "op.evil", "requires": []})
    bad = dict(cart)
    bad["content"] = json.dumps(tampered, sort_keys=True)
    _mock_store(monkeypatch, {"bundle.demo": b, "crystal.demo": bad})
    assert cli.main(["install", "bundle.demo", "--keys-dir", str(keys_dir)]) == cli.EXIT_ERROR
    assert "integrity failure" in capsys.readouterr().out


def test_install_capability_gap_is_refused_with_the_gap_named(keys_dir, monkeypatch, capsys):
    _init(keys_dir, caps="compute.local")
    cart = crystal_artifact(_crystal(requires=("compute.local", "net.get")))
    _mock_store(monkeypatch, {"bundle.demo": _bundle_artifact(cart), "crystal.demo": cart})
    assert cli.main(["install", "bundle.demo", "--keys-dir", str(keys_dir)]) == cli.EXIT_GAP
    assert "net.get" in capsys.readouterr().out          # the gap, NAMED


def test_install_policy_gated_kinds_are_typed_refusals(keys_dir, monkeypatch, capsys):
    _init(keys_dir)
    cart = crystal_artifact(_crystal())
    for kind in cli.POLICY_GATED_KINDS:
        _mock_store(monkeypatch,
                    {"bundle.demo": _bundle_artifact(cart, kind=kind), "crystal.demo": cart})
        assert cli.main(["install", "bundle.demo", "--keys-dir", str(keys_dir)]) == cli.EXIT_POLICY
        assert "requires host policy" in capsys.readouterr().out


# ── publish ──────────────────────────────────────────────────────────────────

def test_publish_requires_a_credential(keys_dir, tmp_path, capsys):
    f = tmp_path / "c.json"
    f.write_text(json.dumps(_crystal()))
    assert cli.main(["publish", str(f)]) == cli.EXIT_ERROR
    assert "AGIENCE_TOKEN" in capsys.readouterr().out


def test_publish_crystal_validates_stamps_and_posts(keys_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("AGIENCE_TOKEN", "tok")
    posted = _mock_store(monkeypatch, {})
    f = tmp_path / "c.json"
    f.write_text(json.dumps(_crystal()))
    assert cli.main(["publish", str(f)]) == cli.EXIT_OK
    url, body, token = posted[0]
    assert url.endswith("/artifacts") and token == "tok"
    assert body["content_type"] == cli.CRYSTAL_CONTENT_TYPE
    stamped = json.loads(body["content"])
    assert stamped["sha256"]                             # sha-stamped by the contract


def test_publish_refuses_an_invalid_crystal(keys_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGIENCE_TOKEN", "tok")
    _mock_store(monkeypatch, {})
    bad = _crystal()
    bad["facets"] = []                                   # sealed glass
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad))
    assert cli.main(["publish", str(f)]) == cli.EXIT_ERROR
    assert "invalid crystal" in capsys.readouterr().out


def test_publish_bundle_stamps_the_sha_over_the_canonical_payload(keys_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("AGIENCE_TOKEN", "tok")
    posted = _mock_store(monkeypatch, {})
    definition = {"name": "bundle.mine",
                  "manifest": {"bundle_kind": "crystal", "environment": "any",
                               "install": {"kind": "artifact"},
                               "crystals": [{"name": "c", "sha256": "x"}],
                               "prisms": [{"name": "p", "environment": "py"}],
                               "created_by": "person-1",
                               "sha256": "LIES"},        # never trusted from the file
                  "content": "hello"}
    f = tmp_path / "b.json"
    f.write_text(json.dumps(definition))
    assert cli.main(["publish", str(f)]) == cli.EXIT_OK
    _, body, _ = posted[0]
    assert json.loads(body["context"])["sha256"] == cli._sha256_of("hello")
