"""The host surface — embeddable SDK for building Agience hosts and operators.

Installed with `pip install "agience-prism-py[host]"`.

Apache-2.0, permissive on purpose: hosts and operators (first-party or third-
party, open or closed) embed this without copyleft reaching their code. The AGPL
platform is reached over the wire rather than linked, and no platform IP lives
here.

    from prism import Host

    host = Host("agience-prism")

    @host.operator("embeddings.embed", path="/embed")
    def embed(req): ...

    app = host.app
"""
from .auth import AuthError, TokenVerifier
from .host import Host

__version__ = "0.1.0"
__all__ = ["Host", "TokenVerifier", "AuthError", "__version__"]
