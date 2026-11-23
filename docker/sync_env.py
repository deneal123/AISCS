#!/usr/bin/env python3
"""Дополнить существующий env без переноса чужих ключей и ротации рабочих секретов.

Конфигураций ровно две (.env.dev и .env.prod), и обе происходят из .env.example.
Скрипт не копирует значения образа вслепую: он проверяет, что набор ключей полон,
и умеет выдать только один секрет — общий токен backend→generator.
"""

import argparse
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path

# Единственный секрет, который скрипт вправе сгенерировать сам: он внутренний,
# никуда не уходит и должен совпадать у backend и generator.
GENERATOR = "GENERATOR_TOKEN"
ASSIGNMENT = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$", re.MULTILINE)
SECRET = re.compile(r"[A-Za-z0-9_+/=-]{32,256}")


def entries(body):
    result = {}
    for match in ASSIGNMENT.finditer(body):
        key, value = match.groups()
        if key in result:
            raise ValueError("повтор ключа: " + key)
        result[key] = value.strip()
    return result


def synchronize(body, example, *, provision_generator=False):
    """Все отказы проверяются до записи; неизвестные дефолты не копируются вслепую."""
    current = entries(body)
    expected = entries(example)
    missing = sorted(expected.keys() - current.keys())
    if missing:
        raise ValueError("нужна ручная настройка ключей: " + ", ".join(missing))
    if provision_generator:
        generator_key = current.get(GENERATOR, "")
        if not generator_key:
            line = GENERATOR + "=" + secrets.token_urlsafe(48)
            body = re.sub(r"^" + GENERATOR + r"=.*$", lambda _: line, body, flags=re.M)
        elif not SECRET.fullmatch(generator_key):
            raise ValueError("unsupported generator credential format")
    return body, missing


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
            provision_generator=args.provision_generator_secret,
        )
        if updated != original:
            save(path, original, updated)
        print("[OK] env сверен с .env.example; недостающих ключей: " + str(len(missing)))
        print("[OK] Значения секретов не выводились; сервисы не запускались.")
        return 0
    except ValueError as exc:
        print("[ERROR] " + str(exc))
    except OSError:
        print("[ERROR] env недоступен для безопасного чтения или записи")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
