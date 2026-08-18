from collections.abc import Sequence

from fastapi import APIRouter, FastAPI
from vypq_core.app import create_app

from gateway.settings import GatewaySettings


def build_app(
    session_factory,
    settings: GatewaySettings,
    routers: Sequence[APIRouter] = (),
    lifespan=None,
) -> FastAPI:
    return create_app(settings, routers=list(routers), lifespan=lifespan)
