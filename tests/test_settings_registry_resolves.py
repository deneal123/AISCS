"""Каждая запись реестра админки резолвится в реальное поле конфига.

⚠️ ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ СТРАЖ, А НЕ СЛЕДСТВИЕ ДРУГИХ ТЕСТОВ.

`AdminService.get_settings_view` резолвит спеки голым
``getattr(getattr(config, spec.section), spec.field)`` — без дефолта. Запись, ссылающаяся
на несуществующее поле, роняет не свою строку, а ВСЮ страницу настроек: ручка отдаёт
500, админ не может открыть панель вообще и не видит ни одной настройки, включая те, что
работают.

Так и случилось: в реестр добавили `agents.search_engine_timeout_sec` (поле есть у
сайдкара), а в зеркало `AgentsConfig` у backend'а его не внесли. Зеркало существует
именно потому, что настройки сайдкара админка раздаёт из своего процесса, — и рассинхрон
здесь ничем не проверялся.

Этот тест дешевле любого другого способа: он перебирает реестр целиком, поэтому ловит
пропуск в момент правки, а не когда кто-то откроет админку.
"""

from __future__ import annotations

import pytest

from service.services.admin.application.settings_registry import all_specs
from service.settings import config


def test_registry_is_not_empty():
    """Контроль предпосылки: пустой реестр сделал бы проверку ниже бессмысленной."""
    assert len(all_specs()) > 10


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.key)
def test_every_spec_resolves_to_a_real_config_field(spec):
    """Ровно та операция, которую делает `get_settings_view`, — без запаса прочности."""
    section = getattr(config, spec.section, None)
    assert section is not None, (
        f"{spec.key}: секции '{spec.section}' нет в конфиге — страница настроек упадёт"
    )
    assert hasattr(section, spec.field), (
        f"{spec.key}: поля '{spec.field}' нет в {type(section).__name__} — "
        f"get_settings_view уронит ВСЮ страницу настроек, а не эту строку"
    )


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.key)
def test_numeric_defaults_lie_within_declared_bounds(spec):
    """Дефолт вне собственных границ спеки — настройка, которую нельзя сохранить как есть.

    Админ открывает панель, ничего не трогает, жмёт «сохранить» — и получает отказ
    валидации на значении, которое сервис использует прямо сейчас.
    """
    if spec.type not in ("int", "float"):
        return
    value = getattr(getattr(config, spec.section), spec.field)
    if value is None:
        return
    if spec.minimum is not None:
        assert value >= spec.minimum, f"{spec.key}: дефолт {value} < минимума {spec.minimum}"
    if spec.maximum is not None:
        assert value <= spec.maximum, f"{spec.key}: дефолт {value} > максимума {spec.maximum}"
