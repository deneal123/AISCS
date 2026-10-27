"""Скрипты сборки и запуска: нативный вывод Docker и приватный preflight."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

import pytest

ROOT = Path(__file__).resolve().parents[2]


def harness(
    tmp_path,
    mode,
    *,
    fail=False,
    require_secret=False,
    diagnostic=None,
    fail_environment_only=False,
    fail_start=False,
    fail_setup=None,
    missing_source=False,
    progress_release=None,
    extra_progress="",
):
    if not (ROOT / "docker" / "build.sh").is_file():
        pytest.skip("root deployment scripts are not shipped in standalone backend")
    bash = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash shell required")
    folder = tmp_path / "docker"
    folder.mkdir()
    for script in ("build.sh", "run.sh"):
        shutil.copyfile(ROOT / "docker" / script, folder / script)
    for name in (
        "compose_preflight.sh",
        "local_llm_bootstrap.sh",
        "sync_env.py",
    ):
        shutil.copyfile(ROOT / "docker" / name, folder / name)
    if not missing_source:
        source = tmp_path / "local_llm" / "docker"
        source.mkdir(parents=True)
        (source / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (folder / f".env.{mode}").write_text(
        "WORKSPACE_IMAGE=fixture-workspace:custom\n"
        "WORKSPACE_DOCUMENT_IMAGE=fixture-document:custom\n"
        "WORKSPACE_COORDINATION_SECRET=fixture-existing-coordination\n",
        encoding="utf-8",
    )
    (folder / ".env.example").write_text(
        "LOCAL_LLM_API_KEY=\nAGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n",
        encoding="utf-8",
    )
    (folder / ("docker-compose.dev.yaml" if mode == "dev" else "docker-compose.yaml")).write_text(
        "{}"
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    fake = tools / "docker"
    fake.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$PROBE_LOG"\n'
        'case "$*" in\n'
        ' *"config --environment"*|*"config --quiet"*)\n'
        '  if [ "$PROBE_REQUIRE_SECRET" = 1 ] && '
        '[ -z "${GPTHUB_WORKSPACE_COORDINATION_SECRET:-}" ]; then\n'
        "   echo private-config-marker >&2; exit 17; fi\n"
        '  if [ "$PROBE_FAIL" = 1 ]; then '
        'printf "%s\\n" "$PROBE_DIAGNOSTIC" >&2; exit 17; fi\n'
        '  if [ "$PROBE_FAIL_ENVIRONMENT_ONLY" = 1 ] && '
        '[[ "$*" == *"--environment"* ]]; then\n'
        "   echo SECRET=private-config-marker; echo private-config-marker >&2; exit 17; fi\n"
        '  if [[ "$*" == *"--environment"* ]]; then cat ".env.$PROBE_MODE"; fi;;\n'
        ' *"config --services"*) exit 0;;\n'
        ' *"run --rm --no-deps -T local-llm-model"*)\n'
        '  if [ -n "$PROBE_FAIL_SETUP" ]; then '
        'printf "%s\\n" "$PROBE_FAIL_SETUP" >&2; exit 18; fi; '
        "echo model_verified;;\n"
        ' *"up -d"*) printf " Container gpthub-$PROBE_MODE-local-llm-1 Starting\\n";\n'
        '  printf "%s\\n" "$PROBE_EXTRA_PROGRESS";\n'
        '  if [ -n "$PROBE_PROGRESS_RELEASE" ]; then\n'
        '   while [ ! -f "$PROBE_PROGRESS_RELEASE" ]; do sleep 0.05; done; fi;\n'
        '  if [ "$PROBE_FAIL_START" = 1 ]; then '
        "echo fixture-native-docker-error >&2; exit 19; fi;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    python = tools / "python3"
    python.write_text('#!/bin/bash\nexec "$PROBE_PYTHON" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    log = tmp_path / "commands"
    env = dict(
        os.environ,
        PROBE_LOG=log.as_posix(),
        PROBE_MODE=mode,
        PROBE_FAIL=str(int(fail)),
        PROBE_REQUIRE_SECRET=str(int(require_secret)),
        PROBE_DIAGNOSTIC=diagnostic or "private-config-marker",
        PROBE_FAIL_ENVIRONMENT_ONLY=str(int(fail_environment_only)),
        PROBE_FAIL_START=str(int(fail_start)),
        PROBE_FAIL_SETUP=fail_setup or "",
        PROBE_PYTHON=Path(sys.executable).as_posix(),
        PROBE_PROGRESS_RELEASE=progress_release.as_posix() if progress_release else "",
        PROBE_EXTRA_PROGRESS=extra_progress,
    )
    for key in (
        "WORKSPACE_IMAGE",
        "WORKSPACE_DOCUMENT_IMAGE",
        "GPTHUB_WORKSPACE_COORDINATION_SECRET",
        "LOCAL_LLM_API_KEY",
        "AGENTS__LOCAL_API_KEY",
    ):
        env.pop(key, None)
    prefix = (
        'export PATH="$(cygpath -u "$1"):$PATH";' if os.name == "nt" else 'export PATH="$1:$PATH";'
    )

    def run(script, action=None, *, streaming=False):
        arguments = [
            str(bash),
            "--noprofile",
            "--norc",
            "-c",
            prefix + 'shift; exec bash "$@"',
            "--",
            tools.as_posix(),
            (folder / script).as_posix(),
            "--" + mode,
            *([action] if action else []),
        ]
        if streaming:
            return subprocess.Popen(
                arguments, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        result = subprocess.run(
            arguments,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    return run


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_startup_dispatches_without_a_script_readiness_barrier(tmp_path, mode):
    result, commands = harness(tmp_path, mode)("run.sh")
    assert result.returncode == 0
    startup = [command for command in commands if "up -d" in command]
    assert len(startup) == 1 and startup[0].endswith("up -d")
    for flag in ("--wait", "--wait-timeout", "--ansi", "--progress"):
        assert flag not in startup[0]
    setup = next(i for i, command in enumerate(commands) if "local-llm-model" in command)
    assert setup < commands.index(startup[0])
    assert not any("inspect " in command or "logs " in command for command in commands)
    output = result.stdout + result.stderr
    assert "Готовность сервисов не проверялась".encode() in output
    assert "Ожидание готовности сервисов".encode() not in output


def test_docker_progress_is_visible_before_startup_finishes(tmp_path):
    release = tmp_path / "release-startup"
    run = harness(tmp_path, "prod", progress_release=release)
    process = run("run.sh", streaming=True)
    lines = Queue()

    def collect():
        for line in iter(process.stdout.readline, b""):
            lines.put(line)
        lines.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        while True:
            try:
                line = lines.get(timeout=15)
            except Empty:
                pytest.fail("Docker-прогресс буферизуется до завершения up")
            assert line is not None, "Запуск закончился до барьера прогресса"
            if b"Container gpthub-prod-local-llm-1 Starting" in line:
                break
        assert process.poll() is None
        release.write_text("continue", encoding="utf-8")
        assert process.wait(timeout=30) == 0
    finally:
        release.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        reader.join(timeout=2)
        process.stdout.close()


def test_native_docker_output_is_not_filtered_or_reformatted(tmp_path):
    native = (
        "\x1b[32m[+] Running 3/3\x1b[0m\r\n"
        " ✔ Container gpthub-prod-backend Started 0.2s\n"
        "Docker diagnostic: fixture-native-message\n"
    )
    result, _ = harness(
        tmp_path,
        "prod",
        fail_start=True,
        extra_progress=native,
    )("run.sh")
    output = result.stdout + result.stderr
    assert result.returncode == 19
    assert native.encode() in output
    assert b"fixture-native-docker-error" in result.stderr
    assert "Дополнительное сообщение скрыто".encode() not in output


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_runtime_prepares_shared_key_once_without_rotating_existing_secrets(tmp_path, mode):
    run = harness(tmp_path, mode)
    first, _ = run("run.sh")
    dotenv = tmp_path / "docker" / f".env.{mode}"
    prepared = dotenv.read_text(encoding="utf-8")
    second, _ = run("run.sh")
    assert first.returncode == second.returncode == 0
    assert dotenv.read_text(encoding="utf-8") == prepared
    assert "WORKSPACE_COORDINATION_SECRET=fixture-existing-coordination\n" in prepared
    key = next(
        line.partition("=")[2]
        for line in prepared.splitlines()
        if line.startswith("LOCAL_LLM_API_KEY=")
    )
    assert len(key) >= 48
    assert "AGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}" in prepared
    assert key.encode() not in first.stdout + first.stderr + second.stdout + second.stderr
    assert len(list(dotenv.parent.glob(f".env.{mode}.backup-*"))) == 1


@pytest.mark.parametrize("script", ["build.sh", "run.sh"])
@pytest.mark.parametrize("failure", ["model_digest_mismatch", "private-download-diagnostic"])
def test_model_setup_failure_prevents_success_and_startup(tmp_path, script, failure):
    result, commands = harness(tmp_path, "prod", fail_setup=failure)(script)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"private-download-diagnostic" not in output
    expected = failure if failure.startswith("model_") else "local_llm_model_setup_failed"
    assert f"code={expected}".encode() in output
    assert not any(" up " in command for command in commands)
    assert "Сборка завершена!".encode() not in output
    assert "Сервисы запущены!".encode() not in output


def test_model_setup_failure_on_restart_never_stops_existing_stack(tmp_path):
    result, commands = harness(tmp_path, "prod", fail_setup="model_download_busy")(
        "run.sh", "--restart"
    )
    assert result.returncode != 0
    assert not any(" down" in command or " up " in command for command in commands)


@pytest.mark.parametrize("action", ["--status", "--logs", "--stop"])
def test_readonly_and_stop_do_not_prepare_env_or_download_model(tmp_path, action):
    run = harness(tmp_path, "prod", fail_setup="must-not-run")
    dotenv = tmp_path / "docker" / ".env.prod"
    original = dotenv.read_bytes()
    result, commands = run("run.sh", action)
    assert result.returncode == 0
    assert not any("local-llm-model" in command or " up " in command for command in commands)
    assert dotenv.read_bytes() == original
    assert not list(dotenv.parent.glob(".env.prod.backup-*"))


def test_missing_model_submodule_blocks_build_before_docker_mutations(tmp_path):
    result, commands = harness(tmp_path, "prod", missing_source=True)("build.sh")
    assert result.returncode != 0 and commands == []
    assert b"git submodule update --init --recursive local_llm" in result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_failed_docker_dispatch_preserves_native_error_and_exit_code(tmp_path, mode):
    result, commands = harness(tmp_path, mode, fail_start=True)("run.sh")
    output = result.stdout + result.stderr
    assert result.returncode == 19
    assert b"code=compose_up_failed" in output
    assert b"fixture-native-docker-error" in result.stderr
    assert "Команда запуска Docker выполнена".encode() not in output
    assert not any("--wait" in command for command in commands)
    assert len([command for command in commands if "up -d" in command]) == 1


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_build_uses_compose_resolved_runtime_image_tags(tmp_path, mode):
    result, commands = harness(tmp_path, mode)("build.sh")
    assert result.returncode == 0
    images = [line for line in commands if line.startswith("build ")]
    assert len(images) == 2
    assert "-t fixture-workspace:custom" in images[0]
    assert "-t fixture-document:custom" in images[1]
    assert "config --environment" in commands[0]
    build = next(i for i, command in enumerate(commands) if " build" in command)
    setup = next(i for i, command in enumerate(commands) if "local-llm-model" in command)
    assert build < setup
    assert not any(" up " in command for command in commands)


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_build_and_run_use_the_same_model_volume_scope(tmp_path, mode):
    run = harness(tmp_path, mode)
    built, _ = run("build.sh", "--no-cache")
    started, commands = run("run.sh")
    assert built.returncode == started.returncode == 0
    setup = [command for command in commands if "local-llm-model" in command]
    assert len(setup) == 2
    for command in setup:
        assert f"--env-file .env.{mode} -p aspa-{mode}" in command
        assert "--profile local-llm-setup run --rm --no-deps -T" in command
        assert "--no-cache" not in command


def test_setup_flags_are_supported_by_actual_compose_cli(tmp_path):
    executable = shutil.which("docker")
    if not executable:
        pytest.skip("Нужен только Compose CLI, без запуска Docker Engine")
    help_result = subprocess.run(
        [executable, "compose", "run", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert help_result.returncode == 0, "compose_run_help_unavailable"
    supported = set(re.findall(r"(?<!\S)(--?[A-Za-z][A-Za-z0-9-]*)", help_result.stdout))
    result, commands = harness(tmp_path, "prod")("build.sh")
    assert result.returncode == 0
    setup = shlex.split(next(command for command in commands if "local-llm-model" in command))
    flags = {arg for arg in setup[setup.index("run") + 1 :] if arg.startswith("-")}
    assert flags <= supported, "unsupported_compose_run_flag"


@pytest.mark.parametrize("mode", ["dev", "prod"])
@pytest.mark.parametrize("script", ["build.sh", "run.sh"])
def test_invalid_configuration_fails_before_mutation_without_raw_detail(tmp_path, mode, script):
    result, commands = harness(tmp_path, mode, fail=True)(script)
    assert result.returncode != 0
    assert b"private-config-marker" not in result.stdout + result.stderr
    assert not any(line.startswith("build ") or " up " in line for line in commands)


def test_build_only_validation_placeholder_never_relaxes_startup(tmp_path):
    run = harness(tmp_path, "prod", require_secret=True)
    built, _ = run("build.sh")
    started, commands = run("run.sh")
    assert built.returncode == 0
    assert started.returncode != 0
    assert b"private-config-marker" not in started.stdout + started.stderr
    assert not any(" up " in line for line in commands)


def test_invalid_restart_configuration_never_stops_existing_stack(tmp_path):
    result, commands = harness(tmp_path, "prod", fail=True)("run.sh", "--restart")
    assert result.returncode != 0
    assert not any(" down" in line or " up " in line for line in commands)


@pytest.mark.parametrize("script", ["build.sh", "run.sh"])
@pytest.mark.parametrize(
    "key", ["GPTHUB_WORKSPACE_COORDINATION_SECRET", "MINIO__SECRET_KEY", "NEO4J_PASSWORD"]
)
def test_missing_required_configuration_reports_only_known_key(tmp_path, script, key):
    diagnostic = (
        f"failed to read /private/path/.env.prod: required variable {key} "
        "is missing a value: postgres://user:private-config-marker@private-host/db"
    )
    result, commands = harness(tmp_path, "prod", fail=True, diagnostic=diagnostic)(script)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"code=missing_required_variable" in output
    assert f"variable={key}".encode() in output
    for private in (b"private-config-marker", b"postgres://", b"private-host", b"/private/path"):
        assert private not in output
    assert not any(line.startswith("build ") or " up " in line for line in commands)


@pytest.mark.parametrize("script", ["build.sh", "run.sh"])
def test_unknown_variable_or_parser_body_is_never_projected(tmp_path, script):
    result, _ = harness(
        tmp_path,
        "prod",
        fail=True,
        diagnostic=(
            "required variable PRIVATE_CUSTOM_MARKER is missing a value: private-config-marker"
        ),
    )(script)
    output = result.stdout + result.stderr
    assert b"code=invalid_configuration" in output
    assert b"PRIVATE_CUSTOM_MARKER" not in output
    assert b"private-config-marker" not in output


def test_missing_secret_restart_reports_key_without_stopping_stack(tmp_path):
    result, commands = harness(
        tmp_path,
        "prod",
        fail=True,
        diagnostic=(
            "required variable MINIO__ACCESS_KEY is missing a value: private-config-marker"
        ),
    )("run.sh", "--restart")
    assert b"variable=MINIO__ACCESS_KEY" in result.stdout + result.stderr
    assert b"private-config-marker" not in result.stdout + result.stderr
    assert result.returncode != 0
    assert not any(" down" in line or " up " in line for line in commands)


def test_failed_environment_snapshot_still_stops_build_when_quiet_config_succeeds(tmp_path):
    result, commands = harness(tmp_path, "prod", fail_environment_only=True)("build.sh")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"code=invalid_configuration" in output
    assert b"private-config-marker" not in output
    assert not any(line.startswith("build ") for line in commands)


@pytest.mark.parametrize("script", ["build.sh", "run.sh"])
def test_variable_name_prefix_cannot_escape_closed_allowlist(tmp_path, script):
    result, _ = harness(
        tmp_path,
        "prod",
        fail=True,
        diagnostic=(
            "required variable MINIO__SECRET_KEY_PRIVATE is missing a value: private-config-marker"
        ),
    )(script)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"code=invalid_configuration" in output
    assert b"MINIO__SECRET_KEY_PRIVATE" not in output
    assert b"private-config-marker" not in output


@pytest.mark.skipif(os.getenv("S37_LIVE_COMPOSE_CONFIG") != "1", reason="read-only Compose opt-in")
@pytest.mark.parametrize(
    "key",
    [
        "GPTHUB_WORKSPACE_COORDINATION_SECRET",
        "MINIO__ACCESS_KEY",
        "MINIO__SECRET_KEY",
        "NEO4J_PASSWORD",
        "PRIVATE_CUSTOM_MARKER",
        None,
    ],
)
def test_actual_compose_failed_preflight_redacts_interpolation_and_dotenv(tmp_path, key):
    bash = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash shell required")
    compose = tmp_path / "compose.yaml"
    dotenv = tmp_path / ".env.fixture"
    compose.write_text(
        "services:\n  fixture:\n    image: busybox\n    environment:\n"
        + (f"      TEST: ${{{key}:?private-config-marker}}\n" if key else "      TEST: safe\n"),
        encoding="utf-8",
    )
    dotenv.write_text(
        "# synthetic only\n" if key else 'BAD="unterminated-private-config-marker\n',
        encoding="utf-8",
    )
    env = dict(os.environ)
    if key:
        env.pop(key, None)
    result = subprocess.run(
        [
            str(bash),
            "--noprofile",
            "--norc",
            "-c",
            'source "$1"; shift; compose_config_preflight "$@"',
            "--",
            (ROOT / "docker" / "compose_preflight.sh").as_posix(),
            "docker",
            "compose",
            "--env-file",
            dotenv.as_posix(),
            "-f",
            compose.as_posix(),
        ],
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    if key and key != "PRIVATE_CUSTOM_MARKER":
        assert f"code=missing_required_variable variable={key}".encode() in output
    else:
        assert b"code=invalid_configuration" in output
    assert b"private-config-marker" not in output
    assert b"PRIVATE_CUSTOM_MARKER" not in output
    assert tmp_path.name.encode() not in output


@pytest.mark.skipif(os.getenv("S37_LIVE_COMPOSE_CONFIG") != "1", reason="read-only Compose opt-in")
@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_actual_compose_interpolation_matches_workspace_runtime_environment(mode):
    env = dict(
        os.environ,
        GPTHUB_WORKSPACE_COORDINATION_SECRET="synthetic-config-validation-only",
        WORKSPACE_IMAGE="fixture-workspace:qualified",
        WORKSPACE_DOCUMENT_IMAGE="fixture-document:qualified",
    )
    compose = "docker-compose.dev.yaml" if mode == "dev" else "docker-compose.yaml"
    args = [
        "docker",
        "compose",
        "--env-file",
        f"docker/.env.{mode}",
        "-f",
        f"docker/{compose}",
        "--profile",
        mode,
        "config",
    ]
    resolved = subprocess.run(
        args + ["--environment"], cwd=ROOT, env=env, capture_output=True, timeout=30, check=False
    )
    configured = subprocess.run(
        args + ["--format", "json"], cwd=ROOT, env=env, capture_output=True, timeout=30, check=False
    )
    assert resolved.returncode == configured.returncode == 0, "compose_config_failed"
    values = dict(
        line.partition("=")[::2] for line in resolved.stdout.decode().splitlines() if "=" in line
    )
    runtime = json.loads(configured.stdout)["services"]["workspace"]["environment"]
    for key in ("WORKSPACE_IMAGE", "WORKSPACE_DOCUMENT_IMAGE"):
        assert values.get(key) == runtime.get(key) == env[key], "runtime_image_resolution_mismatch"
    services = json.loads(configured.stdout)["services"]
    assert "local-llm" in services and "local-llm-model" not in services
    model = services["local-llm"]
    assert mode in model["profiles"]
    assert model["read_only"] is True
    assert not model.get("ports")
    assert set(model["networks"]) == {"internal"}
    assert model["volumes"] == [
        {
            "type": "volume",
            "source": "local_llm_models",
            "target": "/models",
            "read_only": True,
            "volume": {},
        }
    ]
    keys_match = (
        model["environment"]["LOCAL_LLM_API_KEY"]
        == (services["agents"]["environment"]["AGENTS__LOCAL_API_KEY"])
    )
    assert keys_match, "local_provider_key_mismatch"
    setup_config = subprocess.run(
        args[:-1] + ["--profile", "local-llm-setup", "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert setup_config.returncode == 0, "model_setup_config_failed"
    setup = json.loads(setup_config.stdout)["services"]["local-llm-model"]
    assert setup["image"] == model["image"]
    assert not setup.get("environment") and not setup.get("ports")
    assert set(setup["networks"]) == {"default"}
    assert setup["read_only"] is True and setup["cap_drop"] == ["ALL"]
    mount = setup["volumes"][0]
    assert mount["source"] == "local_llm_models" and mount["target"] == "/models"
    assert not mount.get("read_only", False)
