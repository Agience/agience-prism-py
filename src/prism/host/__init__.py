"""The host surface — embeddable SDK for building Agience hosts and operators.

Installed with `pip install "agience-prism[host]"`.

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

from .. import __version__          # one version for the package, read from `prism`
__all__ = ["Host", "TokenVerifier", "AuthError", "__version__"]
