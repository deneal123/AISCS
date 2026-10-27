"""Console composition keeps observation/Stop available when new execution is disabled."""

from types import SimpleNamespace

from service.composition.ide import build_ide_runtime
from service.composition.ide_checkpoints import build_saved_projects
from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.console import IdeConsoleService
from service.settings import config


def build_agent_console(infra, *, prepare=False):
    runtime = build_ide_runtime(infra.pg_connector)
    console = IdeConsoleService(runtime, infra.redis_client)
    options = config.ide_checkpoints
    if prepare:
        saved = build_saved_projects(infra, runtime, infra.redis_client, options)
    else:
        saved = SimpleNamespace(
            limits=CapturePolicy(
                options.entries,
                options.max_file_bytes,
                options.max_total_bytes,
                options.max_snapshot_bytes,
                options.manifest_bytes,
                options.depth,
            )
        )
    return console.agent_entry(saved, infra)
