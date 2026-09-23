"""Policy-решения маршрутизации: приоритет флагов, форс по модальности, фолбэк.

Отделено от исполнения роутера. Словари имён здесь не живут — они выводятся из реестра
способностей: агент, забытый в прежнем литеральном множестве, молча игнорировал тумблер
человека.
"""

from service.domain.capabilities import forced_allowlist, forced_by_input_type

LEGACY_ROUTE_ALIASES = {
    "pptx_gen": "pdf_gen",
    "research_deck": "research_pdf_presentation",
}


def canonical_route(value: str | None) -> str | None:
    normalized = str(value or "").strip() or None
    return LEGACY_ROUTE_ALIASES.get(normalized, normalized)


def resolve_forced_category(
    *,
    route_override: str | None,
    input_type: str | None,
    web_search: bool,
    deep_research: bool,
) -> str | None:
    """Return category forced by upstream flags/input type, if any."""
    route_override = canonical_route(route_override)
    if route_override and route_override in forced_allowlist():
        return route_override
    # ⚠️ Модальности стоят по РАЗНЫЕ стороны от тумблеров, и это не оплошность порядка:
    # голосовое сообщение — факт, который сильнее переключателя, а по загруженной картинке
    # человек вправе потребовать ресёрч. Перепутав, «включил deep research и приложил
    # картинку» отвечало бы обычным ответом.
    if forced := forced_by_input_type(input_type, beats_toggles=True):
        return forced
    if deep_research:
        return "deep_research"
    if web_search:
        return "web_search"
    return forced_by_input_type(input_type, beats_toggles=False)


def finalize_category(llm_category: str | None) -> str:
    """Finalize category with safe fallback."""
    return llm_category or "general"
