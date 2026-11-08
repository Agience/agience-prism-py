"""Review 27: a persona exchanges only the delegation Origin narrowed to it, never a person's own
token. Origin's `/internal/delegation-token` refuses any other subject token, and the verifier has
no path that sends one: the gateway-model exchange of a forwarded user token is gone."""
from prism.trust import server_auth


def test_there_is_no_exchange_of_a_person_s_own_token():
    for name in dir(server_auth):
        cls = getattr(server_auth, name)
        if isinstance(cls, type):
            assert not hasattr(cls, "_mint_delegation_for_user"), name
    src = open(server_auth.__file__, encoding="utf-8").read()
    assert "_mint_delegation_for_user" not in src
