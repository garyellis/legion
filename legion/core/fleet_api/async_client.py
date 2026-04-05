"""Asynchronous HTTP client for the Legion Fleet API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from legion.core.fleet_api.client import FleetAPIError
from legion.core.fleet_api.models import AgentRegistrationResponse

logger = logging.getLogger(__name__)


class AsyncFleetAPIClient:
    """Typed async Fleet API client for the agent runner surface."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
        )

    async def register_agent(
        self,
        registration_token: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> AgentRegistrationResponse:
        data = await self._post(
            "/agents/register",
            json={
                "registration_token": registration_token,
                "name": name,
                "capabilities": capabilities or [],
            },
        )
        return AgentRegistrationResponse.model_validate(data)

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        logger.debug("POST %s", path)
        response = await self._client.post(path, json=json)
        self._raise_for_status(response)
        return response.json()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise FleetAPIError(response.status_code, detail)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncFleetAPIClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object,
    ) -> None:
        await self.aclose()
