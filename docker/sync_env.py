#!/usr/bin/env python3
"""Дополнить существующий env без переноса чужих ключей и ротации рабочих секретов."""

import argparse
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path

DEFAULTS = {
    "LOCAL_LLM_API_KEY": "",
    "LOCAL_LLM_THREADS": "2",
    "LOCAL_LLM_CONTEXT_SIZE": "8192",
    "LOCAL_LLM_CPUS": "2",
    "LOCAL_LLM_MEMORY_LIMIT": "1536m",
    "AGENTS__LOCAL_API_KEY": "${LOCAL_LLM_API_KEY:-}",
    "AGENTS__LOCAL_BASE_URL": "http://local-llm:8080/v1",
    "AGENTS__LOCAL_TIMEOUT_SEC": "330",
    "AGENTS__LOCAL_MODELS_CACHE_TTL_SEC": "180",
    "AGENTS__HARNESS_REFINEMENT_ENABLED": "true",
    "AGENTS__IMAGE_ONLY_API_ENABLED": "false",
    "AGENTS__LLM_RETRY_BUDGET_SEC": "5",
    "AGENTS__MEMORY_CONTEXT_TIMEOUT_SEC": "2",
    "DEV_HARNESS_IDE_COMMANDS_ENABLED": "true",
    "DEV_HARNESS_IDE_ENABLED": "true",
    "DEV_HARNESS_PDF_ENABLED": "true",
    "MAIL__START_TLS": "true",
    "WORKSPACE_DOCKER_SCOPE": "1",
    "WORKSPACE_DOCUMENT_MAX_VISUAL_BYTES": "268435456",
    "SERVICE__APPLICATION_PROFILE": "simulation",
    "REACT_APP_APPLICATION_PROFILE": "simulation",
    "GENERATOR_URL": "http://generator:8090",
    "GENERATOR_TOKEN": "",
}
COORDINATION = "WORKSPACE_COORDINATION_SECRET"
EXTERNAL = "GPTHUB_WORKSPACE_COORDINATION_SECRET"
ASSIGNMENT = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$", re.MULTILINE)


def entries(body):
    result = {}
    for match in ASSIGNMENT.finditer(body):
        key, value = match.groups()
        if key in result:
            raise ValueError("повтор ключа: " + key)
        result[key] = value.strip()
    return result


def order_local_secret(body):
    """Compose читает dotenv последовательно: ссылка не должна опережать источник."""
    values = entries(body)
    if values.get("AGENTS__LOCAL_API_KEY") not in {
        "${LOCAL_LLM_API_KEY:-}", "${LOCAL_LLM_API_KEY}",
    }:
        return body
    lines = body.splitlines(keepends=True)
    source = next((i for i, line in enumerate(lines) if line.startswith("LOCAL_LLM_API_KEY=")), None)
    alias = next((i for i, line in enumerate(lines) if line.startswith("AGENTS__LOCAL_API_KEY=")), None)
    if source is not None and alias is not None and source > alias:
        value = lines.pop(source)
        lines.insert(alias, value if value.endswith("\n") else value + "\n")
    return "".join(lines)


def synchronize(body, example, *, provision=False, provision_local=False, provision_generator=False):
    """Все отказы проверяются до записи; неизвестные дефолты не копируются вслепую."""
    current = entries(body)
    expected = entries(example)
    missing = sorted(expected.keys() - current.keys())
    unsupported = sorted(set(missing) - DEFAULTS.keys() - ({COORDINATION} if provision else set()))
    if unsupported:
        raise ValueError("нужна ручная настройка ключей: " + ", ".join(unsupported))
    if any(expected[key] != DEFAULTS[key] for key in missing if key in DEFAULTS):
        raise ValueError("изменились согласованные дефолты; требуется проверка")
    value = current.get(COORDINATION, "")
    external = re.fullmatch(r"\$\{GPTHUB_WORKSPACE_COORDINATION_SECRET:\?[^}]*\}", value)
    needs_secret = not value or external is not None or value.startswith("change-me-")
    if provision and needs_secret:
        # Существующий прямой секрет никогда не меняется. Адресная замена касается
        # только отсутствующего значения или известной внешней обязательной ссылки.
        supplied = os.environ.get(EXTERNAL, "")
        secret = supplied or secrets.token_urlsafe(48)
        if not re.fullmatch(r"[A-Za-z0-9_+/=-]{32,256}", secret):
            raise ValueError("неподдерживаемый формат внешнего секрета")
        line = COORDINATION + "=" + secret
        if COORDINATION in current:
            body = re.sub(r"^WORKSPACE_COORDINATION_SECRET=.*$", lambda _: line, body, flags=re.M)
        else:
            body = body.rstrip("\n") + "\n" + line + "\n"
    elif needs_secret and not os.environ.get(EXTERNAL):
        raise ValueError("секрет не подготовлен; требуется --provision-coordination-secret")
    if missing:
        body = body.rstrip("\n") + "\n# Дополнено согласованными настройками выпуска.\n"
        body += "".join(key + "=" + DEFAULTS[key] + "\n" for key in missing if key in DEFAULTS)
    if provision_local:
        if "LOCAL_LLM_API_KEY" not in expected:
            raise ValueError("локальный секрет отсутствует в контракте env")
        local_key = entries(body).get("LOCAL_LLM_API_KEY", "")
        if not local_key:
            body = re.sub(
                r"^LOCAL_LLM_API_KEY=.*$",
                lambda _: "LOCAL_LLM_API_KEY=" + secrets.token_urlsafe(48),
                body,
                flags=re.M,
            )
        elif not re.fullmatch(r"[A-Za-z0-9_+/=-]{32,256}", local_key):
            raise ValueError("неподдерживаемый формат локального секрета")
        current = entries(body)
        agent_key = current.get("AGENTS__LOCAL_API_KEY", "${LOCAL_LLM_API_KEY:-}")
        if agent_key not in {
            "${LOCAL_LLM_API_KEY:-}",
            "${LOCAL_LLM_API_KEY}",
            current["LOCAL_LLM_API_KEY"],
        }:
            raise ValueError("локальные ключи сервиса и провайдера не согласованы")
    if provision_generator:
        generator_key = entries(body).get("GENERATOR_TOKEN", "")
        if not generator_key:
            line = "GENERATOR_TOKEN=" + secrets.token_urlsafe(48)
            if "GENERATOR_TOKEN" in entries(body):
                body = re.sub(r"^GENERATOR_TOKEN=.*$", lambda _: line, body, flags=re.M)
            else:
                body = body.rstrip("\n") + "\n" + line + "\n"
        elif not re.fullmatch(r"[A-Za-z0-9_+/=-]{32,256}", generator_key):
            raise ValueError("unsupported generator credential format")
    return order_local_secret(body), missing


def save(path, original, updated):
    """Приватная резервная копия и атомарная замена; существующий env не теряется."""
    if path.is_symlink() or path.read_text(encoding="utf-8") != original:
        raise ValueError("env изменён параллельно или является символической ссылкой")
    backup_fd, backup_name = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
    with os.fdopen(backup_fd, "w", encoding="utf-8", newline="\n") as backup:
        os.chmod(backup_name, stat.S_IRUSR | stat.S_IWUSR)
        backup.write(original)
        backup.flush()
        os.fsync(backup.fileno())
    fd, name = tempfile.mkstemp(prefix=path.name + ".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as pending:
            os.chmod(name, stat.S_IRUSR | stat.S_IWUSR)
            pending.write(updated)
            pending.flush()
            os.fsync(pending.fileno())
        if path.read_text(encoding="utf-8") != original or path.is_symlink():
            raise ValueError("env изменён параллельно; замена отменена")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dev", "prod"), required=True)
    parser.add_argument("--provision-coordination-secret", action="store_true")
    parser.add_argument("--provision-local-llm-secret", action="store_true")
    parser.add_argument("--provision-generator-secret", action="store_true")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    path = folder / (".env." + args.mode)
    try:
        if path.is_symlink():
            raise ValueError("символическая ссылка вместо env запрещена")
        original = path.read_text(encoding="utf-8")
        updated, missing = synchronize(
            original,
            (folder / ".env.example").read_text(encoding="utf-8"),
            provision=args.provision_coordination_secret,
            provision_local=args.provision_local_llm_secret,
            provision_generator=args.provision_generator_secret,
        )
        if updated != original:
            save(path, original, updated)
        print("[OK] env синхронизирован; добавлено ключей: " + str(len(missing)))
        print("[OK] Значения секретов не выводились; сервисы не запускались.")
        return 0
    except ValueError as exc:
        print("[ERROR] " + str(exc))
    except OSError:
        print("[ERROR] env недоступен для безопасного чтения или записи")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
