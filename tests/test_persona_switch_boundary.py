"""Смена личности ПОСРЕДИ треда обязана быть отмечена явно.

🔴 Живой прогон: пользователь переключился с «таролога» на «учёного», и ответ остался в
жанре предыдущей роли — с прежней темой, прежней структурой и без единого следа новой
специализации. Причина не в текстах личности: личность живёт одной строкой в системной
инструкции, а в истории лежат предыдущие ходы, где ассистент УЖЕ показал другое
поведение, и весят они кратно больше. Инструкция не спорит с демонстрацией.

Здесь проверяется разрыв: сигнал «предыдущие ответы даны в другой роли». Признак
считает СТОРОНА ВЫЗОВА (у сайдкара истории с метаданными нет) и везёт полем контракта.
"""

from __future__ import annotations

from service.domain.persona.lens import SECTION_TITLE, PersonaLens
from service.domain.persona.schema import PersonaSpec

TAROT = PersonaSpec(
    id="tarot",
    label="Таролог",
    core={"identity": "Читаю символы.", "tone": "образно"},
    disclaimers=["Толкование — не предсказание."],
)

_NOTICE_MARK = "только что сменилась"
_OFF_MARK = "Специализация снята"


def test_switch_notice_appears_when_role_changed():
    section = PersonaLens([TAROT], switched=True).section()

    assert _NOTICE_MARK in section, "смена роли не отмечена — история перебьёт инструкцию"
    assert "Читаю символы." in section, "разрыв вытеснил саму роль"


def test_notice_precedes_the_role_description():
    """Разрыв стоит ДО описания роли: он объясняет, как читать всё остальное."""
    section = PersonaLens([TAROT], switched=True).section()

    assert section.index(_NOTICE_MARK) < section.index("Читаю символы.")
    assert section.startswith(SECTION_TITLE), "секция потеряла заголовок"


def test_no_notice_without_switch():
    """🔴 Без смены роли промпт прежний: разрыв на ровном месте вредит.

    Сказать «предыдущие ответы даны в другой роли», когда роль не менялась, — значит
    попросить модель не держать единый стиль там, где его как раз надо держать.
    """
    section = PersonaLens([TAROT], switched=False).section()

    assert _NOTICE_MARK not in section
    assert section == PersonaLens([TAROT]).section(), "умолчание перестало быть «не менялась»"


def test_removing_the_persona_is_also_a_switch():
    """Личность СНЯЛИ — разрыв нужен ровно так же: история с ролью никуда не делась."""
    section = PersonaLens([], switched=True).section()

    assert _OFF_MARK in section, "снятие личности прошло молча — прежний жанр потянется дальше"
    assert "Тон:" not in section, "снятая личность всё ещё диктует стиль"


def test_neutral_run_stays_byte_identical():
    """🔴 ГЛАВНЫЙ ИНВАРИАНТ: нет личности и нет смены — нет НИ ОДНОГО символа."""
    assert PersonaLens([]).section() == ""
    assert PersonaLens([], switched=False).section() == ""


def test_persona_budget_has_headroom_for_every_shipped_combination():
    """🔴 Секция ЛЮБОЙ допустимой связки обязана влезать в бюджет с запасом.

    Замер на прежнем значении: худшая пара давала 312 токенов при лимите 320 — восемь
    токенов до обрыва. Обрезается при этом ХВОСТ секции, то есть тон, формат ответа и
    оговорки: первой молча отваливается ровно та часть, ради которой личность и
    выбирают, а у таролога с финансистом она ещё и юридически значима.

    Запас 25%: связка «граница + две личности» — верхняя граница того, что вообще
    может собраться, и правка текстов не должна незаметно упереться в потолок.
    """
    from itertools import permutations

    from service.domain.persona.seed import DEFAULT_PERSONAS
    from service.settings import config
    from service.shared.token_budget import estimate_tokens

    budget = int(config.agents.persona_max_tokens)
    specs = {pid: PersonaSpec(**{"id": pid, **body}) for pid, body in DEFAULT_PERSONAS.items()}

    worst_tokens, worst_pair = 0, ()
    for pair in permutations(specs.values(), 2):
        # switched=True — самый длинный вариант: к секции добавляется разрыв.
        size = estimate_tokens(PersonaLens(list(pair), switched=True).section())
        if size > worst_tokens:
            worst_tokens, worst_pair = size, tuple(s.id for s in pair)

    assert worst_tokens <= budget * 0.8, (
        f"связка {worst_pair} занимает {worst_tokens} из {budget} токенов — запаса нет, "
        "любая правка текстов обрежет тон, формат и оговорки"
    )


def test_disclaimers_are_an_output_requirement_not_a_statement():
    """🔴 Оговорка обязана быть ТРЕБОВАНИЕМ К ВЫВОДУ.

    Живой диалог: у таролога и психолога оговорки объявлены в реестре, доезжают до
    промпта — и НИ РАЗУ не выведены. Голый текст среди описания роли читается моделью
    как ограничение собственного поведения, а не как строка для показа.
    """
    section = PersonaLens([TAROT]).section()

    assert "Толкование — не предсказание." in section
    assert "заверши" in section, "оговорка стоит утверждением — её не выведут"


# --------------------------------------------------------------------------- #
# Оговорка не зависит от сговорчивости модели                                  #
# --------------------------------------------------------------------------- #
def _postprocessed(reply: str) -> str:
    from service.application.use_cases.agent_execution_use_cases import _ensure_disclaimers

    return _ensure_disclaimers(reply)


def test_missing_disclaimer_is_appended_deterministically():
    """🔴 Просьба в промпте — НЕ гарантия. Живой прогон: gpt-4o-mini проигнорировал её
    и в мягкой, и в жёсткой формулировке. Юридически значимый текст не может зависеть
    от того, насколько сговорчива модель, доставшаяся по фейловеру."""
    from service.domain import persona

    разбор = (
        "Расклад из трёх карт. Первая — Туз Мечей: ясность и готовность спорить. "
        "Вторая — Королева Кубков: глубина чувств и осторожность в их предъявлении. "
        "Третья — Колесо Фортуны: многое решают внешние обстоятельства, и связь будет "
        "меняться вместе с ними. Прикладное прочтение: договаривайтесь о темпе заранее."
    )
    with persona.use_persona(PersonaLens([TAROT])):
        out = _postprocessed(разбор)

    assert "Толкование — не предсказание." in out, "оговорка не дописана"


def test_short_reply_gets_no_disclaimer():
    """🔴 Приветствию дисклеймить нечего.

    Живой диалог: «Привет! Чем могу помочь?» и следом строка о том, что толкование не
    является финансовым советом. Оговорка относится к ТОЛКОВАНИЮ; на приветствии и
    переспросе она превращается в шум, который перестают замечать — включая ответы,
    где она существенна.
    """
    from service.domain import persona

    with persona.use_persona(PersonaLens([TAROT])):
        out = _postprocessed("Привет! Чем могу помочь?")

    assert out == "Привет! Чем могу помочь?"


def test_disclaimer_is_not_duplicated():
    """Модель выполнила просьбу — второй копии быть не должно."""
    from service.domain import persona

    # ⚠️ Текст ДЛИННЫЙ намеренно: короткий отсекается порогом, и тест проходил бы
    # тривиально — не проверяя дедуп вовсе.
    said = (
        "Расклад из трёх карт: Туз Мечей, Королева Кубков, Колесо Фортуны. Разбор по "
        "позициям показывает, что ясность одного встречается с глубиной другой, а "
        "обстоятельства будут менять расстановку. Прикладное прочтение: держите темп.\n\n"
        "Толкование — не предсказание."
    )
    with persona.use_persona(PersonaLens([TAROT])):
        out = _postprocessed(said)

    assert len(said) > 220, "текст короче порога — тест проверял бы порог, а не дедуп"
    assert out.count("Толкование — не предсказание.") == 1


def test_no_persona_no_appendix():
    """🔴 Без личности ответ не трогаем ВООБЩЕ — даже длинный, мимо порога."""
    long_answer = "Обычный развёрнутый ответ без всякой специализации. " * 6

    assert len(long_answer) > 220, "короткий текст отсёк бы порог, а не отсутствие личности"
    assert _postprocessed(long_answer) == long_answer


def test_empty_reply_is_left_to_the_provider_error_path():
    """Пустой ответ уже подменён сообщением о недоступности провайдера — не портим его."""
    from service.domain import persona

    with persona.use_persona(PersonaLens([TAROT])):
        assert _postprocessed("") == ""
