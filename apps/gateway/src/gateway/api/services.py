from fastapi import APIRouter
from vypq_contracts.gateway import ServicesResponse

from gateway.registry.services import ServiceRegistry


def build_services_router(registry: ServiceRegistry) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/services", response_model=ServicesResponse)
    async def list_services() -> ServicesResponse:
        return ServicesResponse(services=registry.states())

    return router
