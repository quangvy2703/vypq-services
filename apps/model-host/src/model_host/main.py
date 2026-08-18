from vypq_core.app import create_app

from model_host.api.routes import build_router
from model_host.registry import ModelRegistry
from model_host.runners import RUNNERS
from model_host.settings import ModelHostSettings
from model_host.spec import load_host_config


def build_app():
    settings = ModelHostSettings()
    config = load_host_config(settings.models_path)
    registry = ModelRegistry(config, runners=RUNNERS)
    return create_app(
        settings, routers=[build_router(registry, settings)], expose_docs=settings.expose_docs
    )


app = build_app()
