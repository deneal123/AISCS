"""Приоритет слоёв конфигурации: env > settings.toml > дефолт в коде.

Тест существует потому, что порядок здесь легко перепутать, а перепутанный он
даёт худший из возможных отказов: закоммиченный файл начинает молча перебивать
конфигурацию деплоя. Ошибка не видна ни в логах, ни в `docker compose config` —
только в поведении.

Имена секций здесь НАРОЧНО выдуманные. Проверяется загрузчик, а не набор ручек
конкретного сервиса: привязка к реальным ключам сделала бы тест хрупким к любому
переименованию и при этом не проверяла бы ничего дополнительно. Поэтому файл
одинаков у всех четырёх сайдкаров.
"""

from __future__ import annotations

import os

import settings


def _toml(tmp_path, monkeypatch, body: str):
    path = tmp_path / "settings.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("GPTHUB_SETTINGS_TOML", str(path))
    return path


def test_env_beats_toml(tmp_path, monkeypatch):
    _toml(tmp_path, monkeypatch, "[probe]\nvalue = 111\n")
    monkeypatch.setenv("PROBE_VALUE", "7")

    settings.load()

    assert os.environ["PROBE_VALUE"] == "7", "файл перебил окружение — приоритет инвертирован"


def test_toml_fills_the_gap(tmp_path, monkeypatch):
    _toml(tmp_path, monkeypatch, "[probe]\nvalue = 111\n")
    monkeypatch.delenv("PROBE_VALUE", raising=False)

    assert settings.load()["PROBE_VALUE"] == "111"


def test_missing_file_is_not_an_error(tmp_path, monkeypatch):
    """Отсутствие необязательного слоя дефолтов не должно ронять сервис.

    Иначе ни тесты, ни голый `docker run` без настроек невозможны.
    """
    monkeypatch.setenv("GPTHUB_SETTINGS_TOML", str(tmp_path / "нет-такого.toml"))

    assert settings.load() == {}


def test_empty_string_counts_as_unset(tmp_path, monkeypatch):
    """compose передаёт незаданную переменную как `""`, а не как отсутствие.

    Если считать пустую строку заданным значением, TOML перестанет действовать
    ровно там, где переменная объявлена в compose «на всякий случай».
    """
    _toml(tmp_path, monkeypatch, '[probe]\nvalue = "из-файла"\n')
    monkeypatch.setenv("PROBE_VALUE", "")

    assert settings.load().get("PROBE_VALUE") == "из-файла"


def test_booleans_use_the_same_spelling_as_compose(tmp_path, monkeypatch):
    """`true`/`false`, а не `True`/`False`: код читает их так же, как из compose."""
    _toml(tmp_path, monkeypatch, "[probe]\nyes = true\nno = false\n")
    monkeypatch.delenv("PROBE_YES", raising=False)
    monkeypatch.delenv("PROBE_NO", raising=False)

    applied = settings.load()

    assert applied["PROBE_YES"] == "true"
    assert applied["PROBE_NO"] == "false"


def test_nested_tables_become_underscored_names(tmp_path, monkeypatch):
    _toml(tmp_path, monkeypatch, "[a]\n[a.b]\nc = 1\n")
    monkeypatch.delenv("A_B_C", raising=False)

    assert settings.load()["A_B_C"] == "1"


def test_real_settings_file_declares_only_non_secrets():
    """Файл коммитится — секретов в нём быть не должно.

    Проверка локальная и дешёвая; в CI суперпроекта то же самое делается разом по
    всем сервисам (`scripts/check_settings_manifest.py`).
    """
    import pathlib

    real = pathlib.Path(settings.__file__).resolve().parent / "settings.toml"
    if not real.exists():
        return

    text = real.read_text(encoding="utf-8").lower()
    forbidden = ("api_key", "secret", "password", "token", "private")
    hits = [word for word in forbidden if word in text]

    assert not hits, f"в settings.toml похоже на секрет: {hits}"
