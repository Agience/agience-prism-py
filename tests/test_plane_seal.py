"""The sealed envelope — AES-256-GCM, asserted against `prism.vectors/plane_seal_vectors.json`.

Fernet is AES-128-CBC + HMAC-SHA256 in a container of its own design that no browser implements, so
a browser extension could not open a sealed signal with it at all. AES-GCM and HKDF are both
WebCrypto primitives, so a seal is readable everywhere the edge profile needs it; a signal sealed
under the legacy Fernet format stays readable from the same derived key.

Two things are pinned, and they are pinned differently on purpose. The key derivation is
deterministic, so its output is fixed in the vector file and a second implementation matches it
exactly. The envelope carries a random nonce, so a fixed ciphertext would pin the nonce rather than
the format — it is verified by decrypting the stored examples instead.
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from prism.plane import SEAL_MAGIC, Keyring, Lightcone, open_sealed, seal
# Read from the installed prism package rather than a local `vectors/` directory. `load_vectors`
# raises when the set is absent, so this module fails to import rather than collecting zero cases
# and reporting success.
from prism.vectors import load_vectors

VECTORS = "plane_seal_vectors"
DOC = load_vectors(VECTORS)
ROOT = bytes.fromhex(DOC["root_hex"])


# ── the derivation ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("case", DOC["derivation"]["vectors"], ids=lambda c: c["group"] or "empty")
def test_group_key_reproduces_the_pinned_derivation(case):
    """These bytes are what a WebCrypto `deriveBits` must produce. If they move, every node that
    already holds a derived key stops being able to open anything sealed by an updated one."""
    assert Keyring(ROOT).group_key(case["group"]).hex() == case["key_hex"], (
        "group %r: derivation moved" % case["group"])


def test_the_key_is_32_raw_bytes_not_a_fernet_key():
    """Fernet's key format is base64 of 32 bytes, and Fernet splits those into two 16-byte halves —
    so the same material bought AES-128 plus HMAC. Used directly it is AES-256."""
    from cryptography.fernet import Fernet

    key = Keyring(ROOT).group_key("fleet")
    assert isinstance(key, bytes) and len(key) == 32
    with pytest.raises(ValueError):
        Fernet(key)          # Fernet wants base64 of 32 bytes; these are the 32 bytes
    assert Fernet(base64.urlsafe_b64encode(key)), "the legacy key is still derivable from the raw one"


def test_the_derivation_matches_a_hand_built_hkdf():
    """An independent oracle: HKDF built here from the documented parameters, rather than `prism.plane`
    agreeing with its own stored output. This is what makes the pins above meaningful."""
    for case in DOC["derivation"]["vectors"]:
        expected = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                        info=("comms:group:%s" % case["group"]).encode("utf-8")).derive(ROOT)
        assert expected.hex() == case["key_hex"], (
            "group %r: the pinned key does not match HKDF-SHA256 over the documented parameters"
            % case["group"])


def test_different_groups_derive_different_keys():
    """The negative control for isolation. Identical keys across groups would make every membership
    test below pass while the plane leaked everything to everyone."""
    kr = Keyring(ROOT)
    keys = {g: kr.group_key(g) for g in ("a", "b", "c", "a/b")}
    assert len(set(keys.values())) == len(keys)


def test_a_different_root_derives_different_keys():
    """Two fleets with different roots share no group keys, whatever their groups are named."""
    assert Keyring(ROOT).group_key("fleet") != Keyring(bytes(32)).group_key("fleet")


# ── the envelope ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ex", DOC["envelope"]["sealed_examples"], ids=lambda e: e["group"])
def test_the_stored_envelopes_still_open(ex):
    """Decrypting rather than byte-comparing: the nonce is random, so the format is what is pinned."""
    key = Keyring(ROOT).group_key(ex["group"])
    assert open_sealed(ex["sealed"], [key], aad=ex["aad"]) == ex["signal"]


def test_the_envelope_is_readable_without_a_python_library():
    """The whole point, asserted directly: the envelope is parsed here by slicing, and decrypted with
    a bare AES-GCM call — the two operations WebCrypto offers. Fernet's container could not be."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = Keyring(ROOT).group_key("fleet")
    raw = base64.urlsafe_b64decode(seal({"a": 1}, key, aad="fleet"))

    assert raw[:4] == SEAL_MAGIC
    nonce, ct = raw[4:16], raw[16:]
    assert len(nonce) == 12, "a 96-bit nonce is what AES-GCM takes everywhere"
    assert json.loads(AESGCM(key).decrypt(nonce, ct, b"fleet")) == {"a": 1}
    assert len(ct) >= 16, "the 16-byte tag is appended to the ciphertext"


def test_a_signal_cannot_be_moved_to_another_target():
    """The AAD, asserted. A ciphertext lifted from one leaf and dropped on another fails its tag
    rather than opening — mantle's invariant 3, now true on the wire.

    The same key is used for both attempts, so the AAD is the only thing that keeps the move from
    succeeding.
    """
    key = Keyring(ROOT).group_key("fleet")
    sealed = seal({"secret": 1}, key, aad="fleet")

    assert open_sealed(sealed, [key], aad="fleet") == {"secret": 1}
    assert open_sealed(sealed, [key], aad="other-group") is None
    assert open_sealed(sealed, [key], aad="") is None


def test_tampering_yields_silence_not_a_wrong_plaintext():
    """Every byte is authenticated. A flipped bit anywhere fails the tag."""
    key = Keyring(ROOT).group_key("fleet")
    raw = bytearray(base64.urlsafe_b64decode(seal({"a": 1}, key, aad="fleet")))
    for i in (5, len(raw) // 2, len(raw) - 1):        # nonce, ciphertext, tag
        bad = bytearray(raw)
        bad[i] ^= 0x01
        assert open_sealed(base64.urlsafe_b64encode(bytes(bad)).decode(), [key], aad="fleet") is None


def test_a_non_member_key_opens_nothing():
    """Isolation is cryptographic. A principal outside the group holds no key that opens the signal,
    so the leaf is noise rather than filtered content."""
    kr = Keyring(ROOT)
    sealed = seal({"a": 1}, kr.group_key("fleet"), aad="fleet")
    outsider = Lightcone().join("nobody", "elsewhere")
    assert open_sealed(sealed, kr.principal_keys("nobody", outsider), aad="fleet") is None


def test_the_same_signal_seals_differently_each_time():
    """A random nonce per seal. Deterministic ciphertext would leak equality of plaintexts to anyone
    watching the carrier — every repeat of a message would be visibly a repeat."""
    key = Keyring(ROOT).group_key("fleet")
    seals = {seal({"a": 1}, key, aad="fleet") for _ in range(16)}
    assert len(seals) == 16
    assert all(open_sealed(s, [key], aad="fleet") == {"a": 1} for s in seals)


def test_legacy_fernet_signals_still_open():
    """A carrier is store-and-forward, so a leaf outlives the code that wrote it by however long a
    node was partitioned. A signal sealed with the legacy Fernet format stays readable from the same
    derived key.
    """
    from cryptography.fernet import Fernet

    from prism.plane import _jcs_string

    key = Keyring(ROOT).group_key("fleet")
    legacy = Fernet(base64.urlsafe_b64encode(key)).encrypt(
        _jcs_string({"old": True}).encode("utf-8")).decode("ascii")

    assert not legacy.startswith(base64.urlsafe_b64encode(SEAL_MAGIC).decode()[:4]), (
        "the two envelopes must be distinguishable for this test to mean anything")
    assert open_sealed(legacy, [key], aad="fleet") == {"old": True}, "a legacy signal became unreadable"


def test_malformed_input_is_absent_not_an_error():
    """Most leaves on a shared carrier are addressed to groups this principal is not in. Silence is
    the normal case; an exception here would make an ordinary poll fail."""
    key = Keyring(ROOT).group_key("fleet")
    for bad in ("", "!!!not base64!!!", base64.urlsafe_b64encode(b"BSL1short").decode(),
                base64.urlsafe_b64encode(b"XXXX" + b"\x00" * 40).decode()):
        assert open_sealed(bad, [key], aad="fleet") is None, "%r raised or opened" % bad
