from __future__ import annotations

import os

import httpx

from service.composition.infra import build_infra
from service.composition.state import get_current_container
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository
from service.settings import config


def simulation_queue() -> str:
    """Keep isolated deployments on their configured queue; preserve the default."""
    name = os.environ.get("SIMULATION_QUEUE", "simulation")
    if not name or len(name) > 100 or not all(ch.isascii() and (ch.isalnum() or ch in "-_")
                                              for ch in name):
        raise RuntimeError("simulation_queue_invalid")
    return name


def generator_client() -> httpx.AsyncClient:
    token = os.environ.get("GENERATOR_TOKEN", "")
    if len(token) < 24:
        raise RuntimeError("generator_not_configured")
    return httpx.AsyncClient(
        base_url=os.environ.get("GENERATOR_URL", "http://generator:8090"),
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    )


def infrastructure():
    try:
        return get_current_container().infra
    except RuntimeError:
        return build_infra(config)


def file_service(infra) -> FileSaverService:
    return FileSaverService(FileRepository(infra.pg_connector), "simulations", infra.storage)
