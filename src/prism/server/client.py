"""AgienceClient — typed HTTP helpers to Agience core, authed via a Server.

Thin wrapper over ``httpx`` that prefixes the right plane's base URI and attaches
the Server's delegation/API-key headers. Each call is routed by path: artifact
OPERATIONS (``/artifacts/{id}/op/*``, ``/create``, ``/resolve/*``, ``/embed``)
dispatch through Crystal, the content-type gateway (``server.crystal_uri``); raw
CRUD, search and events stay on Mantle (``server.api_uri``). Crystal forwards the
caller's token and Mantle/personas still enforce keyed access. Functions raise
``httpx`` errors; callers (server tools) shape them into results.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

import httpx

from .auth import Server

# artifact op dispatch — the paths Crystal owns (mirrors facet + prism-js).
_OP_PATH = re.compile(r"/artifacts/[^/]+/op/")


class AgienceClient:
    def __init__(self, server: Server, *, timeout: float = 60.0) -> None:
        self._b = server
        self._timeout = timeout

    def _base_for(self, path: str) -> str:
        """Crystal for artifact op dispatch, else Mantle for raw CRUD / search."""
        is_op = bool(_OP_PATH.search(path)) or path.split("?", 1)[0] in (
            "/create",
            "/embed",
        ) or path.startswith("/resolve/")
        return self._b.crystal_uri if is_op else self._b.api_uri

    # ------------------------------------------------------------------
    # Generic verbs
    # ------------------------------------------------------------------
    async def get(self, path: str, *, params: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self._base_for(path)}{path}",
                headers=self._b.user_headers(),
                params=params,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json() if r.content else None

    async def post(self, path: str, *, json: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self._base_for(path)}{path}",
                headers=self._b.user_headers(),
                json=json,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json() if r.content else None

    # ------------------------------------------------------------------
    # Common Agience surfaces
    # ------------------------------------------------------------------
    async def search_query(
        self,
        *,
        query_text: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        scope: Optional[List[str]] = None,
        candidate_budget: int = 200,
        include_vectors: bool = False,
    ) -> dict:
        """Call the raw query primitive — returns the caller's authorized candidates."""
        body: dict = {"candidate_budget": candidate_budget, "include_vectors": include_vectors}
        if query_text:
            body["query_text"] = query_text
        if embedding is not None:
            body["embedding"] = embedding
        if scope:
            body["scope"] = scope
        return await self.post("/search/query", json=body)

    async def invoke(
        self,
        artifact_id: str,
        name: str,
        arguments: dict,
        *,
        workspace_id: Optional[str] = None,
    ) -> Any:
        """Invoke a tool/operation on an artifact — dispatched via Crystal."""
        body: dict = {"name": name, "arguments": arguments}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self.post(f"/artifacts/{artifact_id}/op/invoke", json=body)

    async def create(self, content_type: str, **fields: Any) -> Any:
        """Create an artifact by content type — Crystal resolves the type's
        ``create`` op and routes it. Extra fields (``container_id``, ``content``,
        …) are merged into the body alongside ``content_type``."""
        return await self.post("/create", json={"content_type": content_type, **fields})

    async def resolve(self, content_type: str) -> Any:
        """Resolve a content type to its declared operations (via Crystal)."""
        return await self.get(f"/resolve/{content_type}")

    async def embed(self, body: dict) -> Any:
        """Embed text/content through Crystal's embedding gateway."""
        return await self.post("/embed", json=body)

    async def get_artifact(self, artifact_id: str) -> dict:
        """Read a raw artifact — CRUD, served by Mantle."""
        return await self.get(f"/artifacts/{artifact_id}")
