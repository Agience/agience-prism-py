"""Host template — a minimal Agience host built on agience-prism-py.

A *host* is compute that serves capabilities (operators) over HTTP. Copy this,
add your operators, deploy it anywhere, and point the platform at its URL
(e.g. Mantle's EMBEDDINGS_URI for an embeddings host). The platform reaches you
over the wire — you never import core.

Run:
    pip install agience-prism-py uvicorn
    python examples/host/host_template.py            # serves on :8083
"""
from prism import Host
from pydantic import BaseModel

# api_key=... to require a bearer (proxy URLs are public — set one in prod).
# Pass AGIENCE_API_URI + AGIENCE_TOKEN to self-register with the platform on start.
host = Host("my-host")


class EchoIn(BaseModel):
    text: str


@host.operator("echo", path="/echo")
def echo(req: EchoIn) -> dict:
    """Your capability. The platform invokes it; it operates on artifacts.

    The function's type hints drive request/response validation automatically.
    """
    return {"echo": req.text}


app = host.app  # uvicorn examples.host.host_template:app --port 8083


if __name__ == "__main__":
    host.serve(port=8083)
