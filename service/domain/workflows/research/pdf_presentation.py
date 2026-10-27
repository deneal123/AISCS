"""Research followed by an audited, source-backed PDF presentation."""

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep

SPEC = WorkflowSpec(
    name="research_pdf_presentation",
    label_ru="исследование и PDF-презентация",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    prompt_hint=(
        "просят PDF-презентацию по свежим или проверяемым данным: сначала собрать "
        "источники, затем создать и проверить Beamer PDF"
    ),
    steps=(
        WorkflowStep(
            agent="deep_research",
            instruction=(
                "Собери evidence registry с проверяемыми источниками по теме: {user_input}"
            ),
            independent=True,
        ),
        WorkflowStep(
            agent="pdf_gen",
            instruction=(
                "Создай Beamer 16:9 PDF-презентацию только по собранным фактам и "
                "источникам. Исходная просьба: {user_input}"
            ),
        ),
    ),
)
