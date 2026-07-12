"""AgienceClient — typed HTTP helpers to Agience core, authed via a Bridge.

Thin wrapper over ``httpx`` that prefixes the Agience base URI and attaches the
Bridge's delegation/API-key headers. Generic ``get``/``post`` plus convenience
methods for the most common surfaces. Functions raise ``httpx`` errors; callers
(server tools) shape them into results.
"""

from __future__ import annotations

from typing import Any, List, Optional

import httpx

from .auth import Bridge


class AgienceClient:
    def __init__(self, bridge: Bridge, *, timeout: float = 60.0) -> None:
        self._b = bridge
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Generic verbs
    # ------------------------------------------------------------------
    async def get(self, path: str, *, params: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self._b.api_uri}{path}",
                headers=self._b.user_headers(),
                params=params,
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json() if r.content else None

    async def post(self, path: str, *, json: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self._b.api_uri}{path}",
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
        """Invoke a tool/operation on an artifact via the artifact-native invoke path."""
        body: dict = {"name": name, "arguments": arguments}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self.post(f"/artifacts/{artifact_id}/op/invoke", json=body)

    async def get_artifact(self, artifact_id: str) -> dict:
        return await self.get(f"/artifacts/{artifact_id}")
