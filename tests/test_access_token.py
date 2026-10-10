"""`prism.access_token` — the claim rule every verifier applies after the signature.

The claims below are the shapes Origin mints (`origin/services/auth_service.py`,
`origin/routers/auth_router.py`), written out by hand so nothing under test builds its own input.
Each refusal sits beside an accepted token that differs from it in the one claim under test.
"""
from __future__ import annotations

import pytest

from prism.access_token import caller_refusal, issuer_origin, purpose_refusal

ISSUER = "https://my.agience.test"


def _user(**extra):
    claims = {"sub": "person-1", "aud": ISSUER, "iss": ISSUER, "client_id": "agience-web"}
    claims.update(extra)
    return claims


def _delegation(aud="agience-server-aria", actor="agience-server-aria", **extra):
    claims = {"sub": "person-1", "aud": aud, "act": {"sub": actor},
              "principal_type": "delegation", "iss": ISSUER}
    claims.update(extra)
    return claims


def test_an_access_token_passes():
    assert purpose_refusal(_user()) is None
    assert caller_refusal(_user(), issuer=ISSUER) is None


@pytest.mark.parametrize("token_type", ["refresh", "email_verify", "pwd_reset", "bearer", "", None])
def test_any_token_type_claim_is_a_special_purpose_token(token_type):
    """Origin never writes `token_type` on an access token, so its presence alone refuses."""
    claims = _user(token_type=token_type)
    assert purpose_refusal(claims)
    assert caller_refusal(claims, issuer=ISSUER)
    assert caller_refusal(_delegation(token_type=token_type), issuer=ISSUER)


def test_a_user_token_must_be_addressed_to_the_authority():
    assert caller_refusal(_user(aud="agience"), issuer=ISSUER)
    assert caller_refusal(_user(aud="https://elsewhere.test"), issuer=ISSUER)
    assert caller_refusal(_user(aud=[ISSUER, "x"]), issuer=ISSUER) is None
    # the manifest writes the environment value unreduced; Origin reduces it to scheme://host
    assert caller_refusal(_user(), issuer=ISSUER + "/") is None
    assert caller_refusal(_user(aud=ISSUER.upper()), issuer=ISSUER) is None


def test_with_no_issuer_a_user_token_is_refused_not_waved_through():
    assert caller_refusal(_user(), issuer=None)
    assert caller_refusal(_user(), issuer="")


def test_a_token_without_subject_or_audience_is_refused():
    assert caller_refusal(_user(sub=""), issuer=ISSUER)
    assert caller_refusal({k: v for k, v in _user().items() if k != "sub"}, issuer=ISSUER)
    assert caller_refusal({k: v for k, v in _user().items() if k != "aud"}, issuer=ISSUER)


@pytest.mark.parametrize("principal_type", ["server", "service", "api_key", "unknown"])
def test_a_program_token_is_not_a_caller(principal_type):
    assert caller_refusal(_user(principal_type=principal_type, aud="agience"), issuer=ISSUER)
    assert caller_refusal(_user(principal_type=principal_type), issuer=ISSUER)


def test_an_mcp_client_token_needs_only_an_audience():
    claims = {"sub": "person-1", "aud": "some-client", "principal_type": "mcp_client"}
    assert caller_refusal(claims, issuer=ISSUER) is None
    assert caller_refusal({**claims, "aud": ""}, issuer=ISSUER)


def test_a_delegation_is_checked_against_the_services_own_ids():
    assert caller_refusal(_delegation(), issuer=ISSUER) is None
    assert caller_refusal(_delegation(), issuer=ISSUER,
                          delegation_audiences={"agience-server-aria"}) is None
    assert caller_refusal(_delegation(aud="mantle"), issuer=ISSUER,
                          delegation_audiences={"agience-server-aria"})
    assert caller_refusal(_delegation(), issuer=ISSUER, delegation_audiences=())


def test_a_delegation_names_its_acting_server():
    assert caller_refusal(_delegation(actor=""), issuer=ISSUER)
    assert caller_refusal({**_delegation(), "act": "agience-server-aria"}, issuer=ISSUER)


def test_issuer_origin_drops_path_and_case():
    assert issuer_origin("https://My.Agience.test/some/path?q=1") == "https://my.agience.test"
    assert issuer_origin("") == ""
    assert issuer_origin(None) == ""
