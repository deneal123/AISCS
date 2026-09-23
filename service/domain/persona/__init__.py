"""Личности: специализация агента, текущая вглубь до субагентов и внешних операций.

Три слоя ответственности, и границы между ними — намеренные:

* ИНСТРУМЕНТЫ (`tools/function_tools.py`) — субатомные и ДЕТЕРМИНИРОВАННЫЕ. Личность не
  меняет ни их схемы, ни описания: предсказуемость инструмента дороже стилизации.
* СУБАГЕНТЫ и аналитики — универсальные «кирпичики», которые личность ДОНАСТРАИВАЕТ
  через слоты. Без личности они обязаны работать ровно как прежде.
* ЛИЧНОСТЬ — надстройка над всем этим.

Использование в любой точке кода:

    from service.domain import persona

    persona.current().slot("analyst.image")        # фрагмент или ""
    persona.current().wrap(base_prompt, "search.query")

Без активной личности всё возвращает пустоту, а `wrap` отдаёт промпт БЕЗ ИЗМЕНЕНИЙ —
поэтому впрыск безопасно ставить где угодно.
"""

from service.domain.persona.context import current, use_persona
from service.domain.persona.lens import SECTION_TITLE, PersonaLens
from service.domain.persona.registry import build_lens, catalog, load_specs
from service.domain.persona.schema import MAX_ACTIVE, PersonaSpec
from service.domain.persona.slots import SLOTS

__all__ = [
    "MAX_ACTIVE",
    "SECTION_TITLE",
    "SLOTS",
    "PersonaLens",
    "PersonaSpec",
    "build_lens",
    "catalog",
    "current",
    "load_specs",
    "use_persona",
]
