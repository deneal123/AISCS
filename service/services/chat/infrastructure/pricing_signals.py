"""Сигналы для тарификации ответа: сложность и список инструментов с надбавкой.

Вынесено из ``chat_worker_tasks`` (тот перерос лимит размера): чистая функция над
``execution_result``, без побочных эффектов и зависимостей воркера.
"""

from __future__ import annotations

# Инструменты, надбавка за которые оправдана ТОЛЬКО получившимся артефактом. Генерация
# картинки/презентации — это плата за ФАЙЛ, а не за попытку: нет файла → нет основания.
# Инструмент → ТИП артефакта, за который он берёт надбавку. Надбавка правомерна, только
# если создан файл ИМЕННО этого типа (image_gen — картинку, pptx_gen — презентацию).
_ARTIFACT_TOOLS = {"image_gen": "image", "pptx_gen": "pptx", "pdf_gen": "pdf"}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _surcharge_names() -> set[str]:
    """Имена, за которые вообще берётся надбавка, — из ПРАЙС-СПИСКА, не из копии.

    Второй список рано или поздно отстал бы от первого, а расхождение здесь не падает
    нигде: цена ищется через `.get`, промах молча даёт ноль.
    """
    try:
        from service.settings import config

        return set(config.billing.tool_surcharge_rub or {})
    except Exception:  # noqa: BLE001 — тарификация не должна падать из-за конфига
        return set()


def _artifact_kinds(execution_result: dict, metadata: dict) -> set[str]:
    """Какие ТИПЫ артефактов реально созданы: {"image"} и/или {"pptx"}.

    🔴 Различаем по типу, а не «есть хоть какой-то файл». Мульти-интент запускает несколько
    artifact-субагентов (pptx_gen + image_gen); если pptx удался, а картинка НЕТ, грубый
    гейт «есть артефакт» разрешал надбавку и за image_gen — плата за изображение, которого
    пользователь не получил (тот же класс, что чинили для одиночного пути, но в
    мульти-интенте оставался). Признаки типов однозначны: b64_json — картинка, pptx_b64 —
    презентация; file_url/generated_files различаем по расширению/kind.
    """
    kinds: set[str] = set()
    # Инлайновые артефакты (top-level метаданные и список под-шагов мульти-интента).
    blobs = [metadata, *(metadata.get("multi_intent_artifacts") or [])]
    for a in blobs:
        if not isinstance(a, dict):
            continue
        if a.get("b64_json"):
            kinds.add("image")
        if a.get("pptx_b64"):
            kinds.add("pptx")
        for gf in a.get("generated_files") or []:
            if isinstance(gf, dict):
                if gf.get("kind") == "image":
                    kinds.add("image")
                if gf.get("kind") == "document" and str(gf.get("mime_type")) == "application/pdf":
                    kinds.add("pdf")
                if str(gf.get("file_key") or gf.get("filename") or "").lower().endswith(".pptx"):
                    kinds.add("pptx")
    # Сохранённые файлы — по расширению презайнед-ссылки.
    for url in (execution_result.get("file_url"), metadata.get("file_url")):
        low = str(url or "").lower().split("?", 1)[0]
        if low.endswith(".pptx"):
            kinds.add("pptx")
        elif any(low.endswith(e) for e in _IMAGE_EXTS):
            kinds.add("image")
    return kinds


def _pricing_signals(execution_result: dict) -> tuple[bool, list[str]]:
    """Достать из метаданных сигналы для тарификации: сложность и инструменты.

    Инструментов может быть НЕСКОЛЬКО за один запрос: мульти-интент запускает под-агенты
    разных категорий (web_search + pptx_gen + …), каждый со своей надбавкой. Раньше
    считался только top-level `routing.tool` — а для мульти-интента это «general», поэтому
    надбавки под-задач (web_search 1.5₽, image_gen/pptx_gen 5₽ и т.д.) не билли́лись вовсе.
    Собираем и top-level маршрут, и категории под-задач (`metadata["steps"]`), списком —
    PricingService суммирует надбавку на КАЖДЫЙ элемент (два поиска = две надбавки).

    🔴 ⚠️ НАДБАВКА ЗА АРТЕФАКТ — ТОЛЬКО ПРИ АРТЕФАКТЕ. Живая жалоба: «изобрази…» дала
    картинку и tool=none — надбавки НЕ было (83 кр); а follow-up, где картинка НЕ
    сгенерировалась (провайдер вернул ответ без изображения → текстовый промпт-фолбэк),
    имела tool=image_gen — и надбавка 5₽×маржа = 4166 кредитов легла на пользователя за
    изображение, которого он не получил. Надбавка `image_gen`/`pptx_gen` берётся по
    РЕШЕНИЮ РОУТЕРА, но платой за файл она может быть только когда файл создан.
    ⚠️ Для мульти-интента гейт грубый (есть хоть один артефакт → разрешены все
    artifact-надбавки шага): один провалившийся pptx рядом с удавшимся не вычтется. Это
    редкий край; одиночный путь — самый частый — теперь честен.
    """
    metadata = execution_result.get("metadata") or {}
    routing = metadata.get("model_routing") or {}
    is_complex = str(routing.get("complexity") or "").lower() == "high"
    kinds = _artifact_kinds(execution_result, metadata)

    def _billable(cat: str) -> bool:
        need = _ARTIFACT_TOOLS.get(cat)
        if need is not None and need not in kinds:
            return False  # надбавка за файл ЭТОГО типа, а его нет
        return True

    # 🔴 ИСТОЧНИК — ФАКТ ИСПОЛНЕНИЯ, А НЕ НАМЕРЕНИЕ РОУТЕРА. `agent_type` кладёт
    # ROUTING_COMPLETE одиночного пути: это агент, который РЕАЛЬНО отработал (он же
    # выбирается форсом — тумблером веб-поиска/ресерча или route_override). А
    # `model_routing.tool` — лишь мнение авто-роутера, и в manual-ветке его НЕТ ВОВСЕ:
    # выбрал пользователь конкретную модель — роутер возвращает `source:"manual"` без
    # `tool`. Живой прогон: один и тот же запрос с тумблером поиска давал ['web_search']
    # на модели `auto` и ПУСТО на выбранной модели — поиск отрабатывал одинаково, а
    # надбавка бралась только в первом случае. Систематический недобилл по точке входа.
    #
    # Факт важнее и в обратную сторону: если авто-роутер сказал image_gen, а пользователь
    # форсировал поиск, отработал ТОЛЬКО поиск — брать обе надбавки было бы перебиллом.
    # Поэтому `agent_type` (когда он есть) ЗАМЕЩАЕТ мнение роутера, а не дополняет его.
    # Мульти-интент и мультимодальный путь `agent_type` не эмитят (у них свои сигналы:
    # `steps` ниже и general соответственно), поэтому там поведение прежнее.
    tools: list[str] = []
    executed = metadata.get("agent_type")
    tool = executed if executed else routing.get("tool")
    if tool and str(tool) not in ("none", "general") and _billable(str(tool)):
        tools.append(str(tool))
    steps = metadata.get("steps")
    if isinstance(steps, list):
        tools.extend(
            str(c) for c in steps if c and str(c) not in ("none", "general") and _billable(str(c))
        )
    # 🔴 ИНСТРУМЕНТЫ ВНУТРИ `general` — ОТДЕЛЬНЫЙ СИГНАЛ. Надбавка выше берётся по
    # МАРШРУТУ (`agent_type`), а веб-поиск, который модель позвала сама по ходу обычного
    # ответа, маршрута не меняет: `agent_type` остаётся `general`, и без этой строки
    # поиск был бы бесплатным. Список приходит от сайдкара КУМУЛЯТИВНЫМ — метаданные
    # событий складываются перезаписью, и одиночное значение затёрлось бы вторым вызовом.
    billable_tools = metadata.get("billable_tools")
    if isinstance(billable_tools, list):
        # ⚠️ Сверяем с ПРАЙС-СПИСКОМ, а не пропускаем как есть. Список приходит от
        # сайдкара, а он может уехать вперёд: неизвестное имя дальше всё равно не найдёт
        # цены (`surcharge_map.get` вернёт None), но добавленное в `tools` оно попадёт в
        # `surcharged_tools` и покажется человеку в счёте как платная строка на ноль
        # кредитов. Отсекаем здесь, где ещё видно, почему.
        known = set(_surcharge_names())
        tools.extend(str(t) for t in billable_tools if t and str(t) in known and _billable(str(t)))
    return is_complex, tools
