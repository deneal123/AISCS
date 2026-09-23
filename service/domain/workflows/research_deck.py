"""«Найди и сделай презентацию» — канонический двухшаговый сценарий.

Декомпозиция такой запрос разбирает и сама, но: платит вызовом модели, ошибается на
формулировках без союзов («сделай презентацию про рынок X по свежим данным») и даёт разный
результат на один и тот же текст. Объявленный маршрут детерминирован и бесплатен.

🔴 Дорогой (внутри `pptx_gen`), поэтому сам не запускается: `confirm_by_default` уводит его
на кнопку, а правило класса цены не даёт стартовать даже по догадке с пустым списком
подтверждения.
"""

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep

SPEC = WorkflowSpec(
    name="research_deck",
    label_ru="поиск и презентация",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    # Hidden compatibility route for one release cycle. New requests are routed
    # through research_pdf_presentation and produce an audited Beamer PDF.
    prompt_hint="",
    steps=(
        WorkflowStep(
            agent="web_search",
            instruction="Собери актуальные факты и источники по теме: {user_input}",
            independent=True,
        ),
        # ⚠️ Не independent: слайды строятся ПО НАЙДЕННОМУ, и без вывода первого шага
        # презентация получится из общих знаний модели — то есть без свежести, ради
        # которой сценарий и выбран.
        WorkflowStep(
            agent="pptx_gen",
            instruction="Сделай презентацию по собранным фактам. Исходная просьба: {user_input}",
        ),
    ),
)
