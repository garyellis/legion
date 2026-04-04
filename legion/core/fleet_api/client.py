"""Synchronous HTTP client for the Legion Fleet API."""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from legion.core.fleet_api.models import AgentGroupResponse, AgentResponse, OrgResponse
from legion.plumbing.exceptions import CoreError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 502, 503, 504})


class FleetAPIError(CoreError):
    """Raised when the Fleet API returns a non-2xx status."""

    _serializable_fields: tuple[str, ...] = ("message", "retryable", "status_code", "detail")

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"HTTP {status_code}: {detail}",
            retryable=status_code in _RETRYABLE_STATUS_CODES,
        )


@runtime_checkable
class FleetAPI(Protocol):
    """Interface for Fleet API access — any surface depends on this, not the implementation."""

    def create_org(self, name: str, slug: str) -> OrgResponse: ...
    def get_org(self, org_id: str) -> OrgResponse: ...
    def list_orgs(self) -> list[OrgResponse]: ...

    def create_agent_group(
        self,
        org_id: str,
        name: str,
        slug: str,
        environment: str = "dev",
        provider: str = "on-prem",
    ) -> AgentGroupResponse: ...
    def get_agent_group(self, agent_group_id: str) -> AgentGroupResponse: ...
    def list_agent_groups(self, org_id: str) -> list[AgentGroupResponse]: ...

    def get_agent(self, agent_id: str) -> AgentResponse: ...
    def list_agents(self, agent_group_id: str) -> list[AgentResponse]: ...


class FleetAPIClient:
    """Typed HTTP client for the Legion Fleet API.

    Usable from any surface that needs remote access to the control plane.
    """

    def __init__(self, base_url: str, api_key: str = "") -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
        )

    # -- Organizations ------------------------------------------------------

    def create_org(self, name: str, slug: str) -> OrgResponse:
        data = self._post("/organizations/", json={"name": name, "slug": slug})
        return OrgResponse.model_validate(data)

    def get_org(self, org_id: str) -> OrgResponse:
        data = self._get(f"/organizations/{org_id}")
        return OrgResponse.model_validate(data)

    def list_orgs(self) -> list[OrgResponse]:
        data = self._get("/organizations/")
        return [OrgResponse.model_validate(item) for item in data]

    # -- Agent Groups -------------------------------------------------------

    def create_agent_group(
        self,
        org_id: str,
        name: str,
        slug: str,
        environment: str = "dev",
        provider: str = "on-prem",
    ) -> AgentGroupResponse:
        data = self._post("/agent-groups/", json={
            "org_id": org_id,
            "name": name,
            "slug": slug,
            "environment": environment,
            "provider": provider,
        })
        return AgentGroupResponse.model_validate(data)

    def get_agent_group(self, agent_group_id: str) -> AgentGroupResponse:
        data = self._get(f"/agent-groups/{agent_group_id}")
        return AgentGroupResponse.model_validate(data)

    def list_agent_groups(self, org_id: str) -> list[AgentGroupResponse]:
        data = self._get("/agent-groups/", params={"org_id": org_id})
        return [AgentGroupResponse.model_validate(item) for item in data]

    # -- Agents -------------------------------------------------------------

    def get_agent(self, agent_id: str) -> AgentResponse:
        data = self._get(f"/agents/{agent_id}")
        return AgentResponse.model_validate(data)

    def list_agents(self, agent_group_id: str) -> list[AgentResponse]:
        data = self._get("/agents/", params={"agent_group_id": agent_group_id})
        return [AgentResponse.model_validate(item) for item in data]

    # -- Transport ----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        logger.debug("GET %s params=%s", path, params)
        response = self._client.get(path, params=params)
        self._raise_for_status(response)
        return response.json()

    def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        logger.debug("POST %s", path)
        response = self._client.post(path, json=json)
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

    def __enter__(self) -> FleetAPIClient:
        return self

    def __exit__(self, _exc_type: type[BaseException] | None, _exc_val: BaseException | None, _exc_tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
