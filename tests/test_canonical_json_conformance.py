"""Canonical JSON is canonical across SDKs — the property all content-addressing rests on.

`prism-c/src/json.cpp:1-4` promises canonical output "makes signatures and content hashes reproducible
across all three SDKs". A sha is only a stable cross-environment ref if every SDK turns the same logical
structure into the same bytes.

RFC 8785 / JCS: raw UTF-8, everywhere.
"""
import json

from prism.crystal_model import canonical_json, crystal_sha

# Non-ASCII is not exotic here: this project ingests Open Multilingual WordNet, and any accented host
# name, capability scope, persona label or artifact title reaches the same code path.
SAMPLE = {"name": "capteur-température", "kind": "sensor.capture"}


def test_ascii_only_payloads_are_unaffected():
    assert canonical_json({"b": 2, "a": "plain"}) == b'{"a":"plain","b":2}'


def test_canonical_json_is_sorted_and_whitespace_free():
    assert canonical_json({"z": 1, "a": {"d": 4, "c": 3}}) == b'{"a":{"c":3,"d":4},"z":1}'


def test_non_ascii_is_raw_utf8_never_escaped():
    """RFC 8785: no `\\uXXXX` escaping. This is the byte sequence prism-c emits and prism-js's
    `JSON.stringify` produces natively."""
    out = canonical_json(SAMPLE)
    assert "é".encode("utf-8") in out              # raw UTF-8 bytes present
    assert b"\\u00e9" not in out                    # and NOT the escaped form
    assert out.decode("utf-8") == json.dumps(
        SAMPLE, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_matches_prism_c_utf8_passthrough_byte_for_byte():
    """What prism-c writes: same JSON grammar, non-ASCII passed through as UTF-8."""
    expected = json.dumps(SAMPLE, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    assert canonical_json(SAMPLE) == expected


def test_a_non_ascii_crystal_has_a_stable_cross_sdk_address():
    """The point of the whole exercise: the content address of a crystal carrying non-ASCII is now the
    same value every SDK computes, so a host cannot sign something the platform then rejects."""
    crystal = {"name": "crystal.capteur-température",
               "organons": [{"name": "op.sense", "requires": ["sensor.capture"]}]}
    body = json.dumps({k: v for k, v in crystal.items() if k != "sha256"},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    import hashlib
    assert crystal_sha(crystal) == hashlib.sha256(body).hexdigest()
