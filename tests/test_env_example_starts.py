"""Шаблон окружения не должен кодировать комбинацию, которая РОНЯЕТ СТАРТ.

⚠️ ЧТО СЛУЧИЛОСЬ. `docker/.env.example` (и скопированный с него `.env.dev`) задавал
`AUTH__DEV_MODE=True` и НЕ задавал `AUTH__AUTH_MODE`. Дефолт `auth_mode` — «prod», а
`_assert_prod_safety` отвергает именно эту пару: кука ушла бы `Secure=False` на боевом
домене. Backend падал на импорте приложения и уходил в цикл перезапуска — 56 раз подряд.

Наружу это выглядит как «сломалась авторизация, ошибка сервера»: API просто нет, и
отличить «упал старт» от «отвалилась авторизация» по поведению невозможно.

## Почему стража не было

`.env.dev`/`.env.prod` лежат в `.gitignore` и на CI не попадают — проверить их нечем. Но
`.env.example` ОТСЛЕЖИВАЕТСЯ, а гард безопасности — обычная функция. Значит образец можно
прогнать через него прямо здесь: если шаблон кодирует падающую комбинацию, это видно в
CI, а не через 56 рестартов в контейнере.
"""

from __future__ import annotations

import pathlib

import pytest

_EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "docker" / ".env.example"


def _parse_env(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


@pytest.fixture(scope="module")
def env_example() -> dict[str, str]:
    if not _EXAMPLE.exists():  # pragma: no cover — суперпроект не рядом
        pytest.skip("docker/.env.example недоступен")
    return _parse_env(_EXAMPLE)


def test_example_is_not_empty(env_example):
    """Контроль предпосылки: пустой разбор сделал бы проверки ниже бессмысленными."""
    assert len(env_example) > 30


def test_example_passes_the_prod_safety_guard(env_example, monkeypatch):
    """⚠️ ГЛАВНОЕ: шаблон обязан пережить тот самый гард, что роняет старт.

    Проверяем не «правильные ли значения», а ровно то, что делает прод: собираем конфиг
    из шаблона и зовём `_assert_prod_safety`. Любая будущая пара, которую гард сочтёт
    небезопасной, упадёт здесь.
    """
    from service.main import _assert_prod_safety
    from service.settings import Config

    for key, value in env_example.items():
        monkeypatch.setenv(key, value)

    # ⚠️ СВЕЖИЙ ЭКЗЕМПЛЯР, А НЕ `importlib.reload(settings)`. Перезагрузка модуля
    # подменяет ГЛОБАЛЬНЫЙ `config`, и патчи, наложенные другими тестами на прежний
    # объект, перестают действовать — это загрязнение всего прогона, а не локальная
    # подмена. В соседнем сервисе такой приём уже сломал десять чужих тестов.
    cfg = Config(_env_file=None)

    try:
        _assert_prod_safety(cfg)
    except RuntimeError as exc:
        pytest.fail(
            f"docker/.env.example кодирует комбинацию, на которой backend НЕ СТАРТУЕТ: "
            f"{exc}. Скопировавший шаблон получит цикл перезапуска, а снаружи это "
            f"выглядит как «сломалась авторизация»."
        )


def test_auth_mode_is_declared_explicitly(env_example):
    """⚠️ Отдельно и поимённо: `auth_mode` нельзя оставлять на дефолт.

    Его дефолт — «prod», то есть «не указать» здесь значит ВЫБРАТЬ prod, а рядом в
    шаблоне стоит `AUTH__DEV_MODE=True`. Пара расходится молча, и узнаёшь об этом
    только по упавшему контейнеру.
    """
    assert "AUTH__AUTH_MODE" in env_example, (
        "AUTH__AUTH_MODE не объявлен в шаблоне: дефолт «prod» вместе с AUTH__DEV_MODE роняет старт"
    )
