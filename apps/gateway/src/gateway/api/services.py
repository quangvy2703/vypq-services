from fastapi import APIRouter, Depends
from vypq_contracts.gateway import ServicesResponse

from gateway.auth import make_token_dependency
from gateway.registry.services import ServiceRegistry
from gateway.settings import GatewaySettings


def build_services_router(registry: ServiceRegistry, settings: GatewaySettings) -> APIRouter:
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    @router.get("/services", response_model=ServicesResponse)
    async def list_services() -> ServicesResponse:
        return ServicesResponse(services=registry.states())

    return router
